"""Config flow for Octopus Energy Japan integration."""
import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OctopusEnergyJpApiClient
from .const import CONF_API_URL, DEFAULT_API_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# 配置界面的数据结构
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_API_URL, default=DEFAULT_API_URL): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Octopus Energy Japan."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # 获取一个 aiohttp session
            session = async_get_clientsession(self.hass)
            
            # 创建 API 客户端
            api = OctopusEnergyJpApiClient(
                session,
                user_input[CONF_EMAIL],
                user_input[CONF_PASSWORD],
                user_input[CONF_API_URL],
            )

            try:
                # 尝试获取 token 来验证凭据
                await api.async_get_token()
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            except Exception as e:
                _LOGGER.exception("Authentication failed: %s", e)
                errors["base"] = "invalid_auth"
            else:
                # 验证成功，创建配置条目
                # 使用 email 作为唯一ID，防止重复配置
                await self.async_set_unique_id(user_input[CONF_EMAIL])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input[CONF_EMAIL], data=user_input
                )

        # 显示配置表单
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )