"""The Octopus Energy Japan integration."""
import datetime
import logging
from asyncio import timeout
from decimal import Decimal

import pytz
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import aiohttp # (需要导入 aiohttp 用于异常处理)

from .api import OctopusEnergyJpApiClient, get_midnight_in_tokyo, get_tokyo_tz
from .const import (
    CONF_API_URL,
    COORDINATOR,
    DOMAIN,
    MANUFACTURER,
    TIMEZONE,
)

_LOGGER = logging.getLogger(__name__)

# 定义平台 (目前只有 sensor)
PLATFORMS: list[Platform] = [Platform.SENSOR]

# 协调器的更新间隔 (每30分钟)
UPDATE_INTERVAL = datetime.timedelta(minutes=30)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Octopus Energy Japan from a config entry."""

    # 创建 API 客户端实例
    session = async_get_clientsession(hass)
    api_client = OctopusEnergyJpApiClient(
        session,
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        entry.data[CONF_API_URL],
    )

    try:
        # 在设置协调器之前，我们必须先获取账户ID
        # 因为后续的统一查询需要 account_number
        account_number = await api_client.async_get_account_number()
    except Exception as e:
        _LOGGER.error("Failed to get account number, setup aborted: %s", e)
        return False # 设置失败

    async def async_update_data():
        """Fetch data from API endpoint."""
        _LOGGER.debug("Coordinator update started")
        try:
            # --- 修改开始: 扩大数据获取范围 ---
            # 我们需要获取从“上个月1号”到“现在”的数据，以支持“上月总览”和“昨日”传感器
            tz = get_tokyo_tz()
            now = datetime.datetime.now(tz=tz)
            
            # 找到本月1号的午夜
            start_of_current_month = get_midnight_in_tokyo(now.date().replace(day=1))
            
            # 找到上月1号的午夜 (通过本月1号往前推1天，找到上个月的最后一天，再取该月1号)
            last_day_of_prev_month = start_of_current_month - datetime.timedelta(days=1)
            start_of_last_month = get_midnight_in_tokyo(last_day_of_prev_month.date().replace(day=1))
            
            # --- 修改结束 ---

            async with timeout(30): # 30秒超时
                data = await api_client.async_get_data(
                    account_number=account_number,
                    start_time=start_of_last_month, # (修改: 从上月1号开始)
                    end_time=now,
                )
                
                return data

        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error communicating with API: {err}")
        except Exception as err:
            _LOGGER.exception("Unexpected error during data update")
            raise UpdateFailed(f"Unexpected error: {err}")

    # 创建 DataUpdateCoordinator
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{account_number}",
        update_method=async_update_data,
        update_interval=UPDATE_INTERVAL,
    )

    # 立即执行第一次刷新，以确保数据可用且配置正确
    await coordinator.async_config_entry_first_refresh()

    # 将 coordinator 存储在 hass.data 中，以便 sensor 平台访问
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        COORDINATOR: coordinator,
        "account_number": account_number
    }

    # 加载 sensor 平台
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # 卸载 sensor 平台
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    # 移除 hass.data 中的数据
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)


    return unload_ok