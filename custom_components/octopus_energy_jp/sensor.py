"""Platform for sensor integration."""
from __future__ import annotations

import datetime
import decimal
import logging
from typing import Any

import pytz
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor.const import CURRENCY_YEN,ENERGY_KILO_WATT_HOUR
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import get_tokyo_tz # (导入时区辅助函数)
from .const import COORDINATOR, DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    
    # 从 hass.data 中获取协调器和账户ID
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = entry_data[COORDINATOR]
    account_number = entry_data["account_number"]
    
    # 创建设备信息 (所有传感器将归于此设备下)
    device_info = DeviceInfo(
        identifiers={(DOMAIN, account_number)},
        name=f"Octopus Account {account_number}",
        manufacturer=MANUFACTURER,
        model="Kraken API Account",
    )

    # 添加传感器实体
    async_add_entities(
        [
            OctopusTodayConsumptionSensor(coordinator, device_info, account_number),
            OctopusMonthlyEstimateSensor(coordinator, device_info, account_number), # (本月预估)
            OctopusBalanceSensor(coordinator, device_info, account_number),
            OctopusOverdueBalanceSensor(coordinator, device_info, account_number),
            OctopusLastBillSensor(coordinator, device_info, account_number), # (上月账单)
            OctopusProductSensor(coordinator, device_info, account_number),
        ]
    )


class OctopusBaseSensor(CoordinatorEntity, SensorEntity):
    """Octopus Energy 传感器的基类"""

    def __init__(self, coordinator, device_info, account_number, sensor_key):
        super().__init__(coordinator)
        self._attr_device_info = device_info
        # 确保 unique_id 不变
        self._attr_unique_id = f"{account_number}_{sensor_key}"
        self._account_number = account_number


class OctopusTodayConsumptionSensor(OctopusBaseSensor):
    """
    传感器：今日累计用电量 (你的核心需求)
    """
    def __init__(self, coordinator, device_info, account_number):
        super().__init__(coordinator, device_info, account_number, "today_consumption")
        self._attr_name = f"Octopus Today Consumption {account_number}"
        
        self._attr_native_unit_of_measurement = ENERGY_KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._tz = get_tokyo_tz() # 获取东京时区

    @property
    def native_value(self) -> decimal.Decimal | None:
        """返回今日累计用电量"""
        if not self.coordinator.data:
            return None
            
        try:
            # (这个传感器的值是在 __init__.py 的 async_update_data 中预先计算好的)
            # 修正: 我们在这里实时计算 "今日" 用电量
            all_readings = self.coordinator.data["properties"][0]["electricitySupplyPoints"][0]["halfHourlyReadings"]
            
            total_consumption_today = decimal.Decimal(0)
            today_date = datetime.datetime.now(tz=self._tz).date()

            for reading in all_readings:
                start_at_utc = datetime.datetime.fromisoformat(reading["startAt"])
                start_at_tokyo = start_at_utc.astimezone(self._tz)
                
                if start_at_tokyo.date() == today_date:
                    total_consumption_today += decimal.Decimal(reading["value"])
            
            return total_consumption_today

        except (KeyError, IndexError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """返回上次更新的时间 (调试用)"""
        if self.coordinator.data:
            try:
                readings = self.coordinator.data["properties"][0]["electricitySupplyPoints"][0]["halfHourlyReadings"]
                if readings:
                    return {"last_reading_at": readings[-1]["endAt"]}
            except (KeyError, IndexError):
                pass
        return {}


class OctopusMonthlyEstimateSensor(OctopusBaseSensor):
    """传感器：本月预估电费"""
    def __init__(self, coordinator, device_info, account_number):
        super().__init__(coordinator, device_info, account_number, "monthly_estimate")
        self._attr_name = f"Octopus Monthly Estimate {account_number}"
        self._attr_native_unit_of_measurement = CURRENCY_YEN
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:cash-clock"
        self._tz = get_tokyo_tz()

    @property
    def native_value(self) -> decimal.Decimal | None:
        """返回预估的本月总费用"""
        if not self.coordinator.data:
            return None
        
        try:
            # 1. 获取所有读数和产品数据
            all_readings = self.coordinator.data["properties"][0]["electricitySupplyPoints"][0]["halfHourlyReadings"]
            product_data = self.coordinator.data["properties"][0]["electricitySupplyPoints"][0]["agreements"][0]["product"]
            
            # 2. 计算总用电量 (coordinator 已经获取了本月至今的全部读数)
            total_kWh_so_far = sum(decimal.Decimal(r["value"]) for r in all_readings)
            
            # 3. 获取电价结构
            standing_charge_per_day = decimal.Decimal(product_data["standingCharges"][0]["pricePerUnit"])
            fuel_adj_per_kwh = decimal.Decimal(product_data["fuelCostAdjustment"]["pricePerUnit"])
            consumption_steps = product_data["consumptionCharges"]
            
            # 4. 计算阶梯电价 (Consumption Cost)
            consumption_cost = decimal.Decimal(0)
            remaining_kwh = total_kWh_so_far
            sorted_steps = sorted(consumption_steps, key=lambda x: x["stepStart"])

            for step in sorted_steps:
                price = decimal.Decimal(step["pricePerUnit"])
                step_start = decimal.Decimal(step["stepStart"])
                step_end = decimal.Decimal(step["stepEnd"]) if step["stepEnd"] is not None else decimal.Decimal('Infinity')
                
                kwh_on_this_step = 0
                if remaining_kwh > 0:
                    step_width = step_end - step_start
                    kwh_on_this_step = min(remaining_kwh, step_width)
                    consumption_cost += kwh_on_this_step * price
                    remaining_kwh -= kwh_on_this_step

            # 5. 计算燃料调整费 (Fuel Adjustment Cost)
            fuel_cost = total_kWh_so_far * fuel_adj_per_kwh
            
            # 6. 计算基本料金 (Standing Charge)
            days_so_far = datetime.datetime.now(tz=self._tz).day
            standing_cost = standing_charge_per_day * days_so_far
            
            # 7. 总预估费用
            estimated_total = consumption_cost + fuel_cost + standing_cost
            
            # (将详情存入属性)
            self._attr_extra_state_attributes = {
                "total_kwh_so_far": f"{total_kWh_so_far:.2f}",
                "consumption_cost": f"{consumption_cost:.2f}",
                "fuel_cost": f"{fuel_cost:.2f}",
                "standing_cost": f"{standing_cost:.2f}",
                "days_so_far": days_so_far,
            }
            
            return round(estimated_total, 2) # 返回四舍五入到2位小数
            
        except (KeyError, IndexError, TypeError, decimal.InvalidOperation) as e:
            _LOGGER.error("Could not calculate monthly estimate: %s", e)
            return None


class OctopusBalanceSensor(OctopusBaseSensor):
    """传感器：当前账户余额"""
    def __init__(self, coordinator, device_info, account_number):
        super().__init__(coordinator, device_info, account_number, "balance")
        self._attr_name = f"Octopus Balance {account_number}"
        self._attr_native_unit_of_measurement = CURRENCY_YEN
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:cash"

    @property
    def native_value(self) -> decimal.Decimal | None:
        if self.coordinator.data:
            return self.coordinator.data.get("balance")
        return None


class OctopusOverdueBalanceSensor(OctopusBaseSensor):
    """传感器：逾期未付余额"""
    def __init__(self, coordinator, device_info, account_number):
        super().__init__(coordinator, device_info, account_number, "overdue_balance")
        self._attr_name = f"Octopus Overdue Balance {account_number}"
        self._attr_native_unit_of_measurement = CURRENCY_YEN
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:cash-remove"

    @property
    def native_value(self) -> decimal.Decimal | None:
        if self.coordinator.data:
            return self.coordinator.data.get("overdueBalance")
        return None


class OctopusLastBillSensor(OctopusBaseSensor):
    """传感器：上一张账单金额"""
    def __init__(self, coordinator, device_info, account_number):
        super().__init__(coordinator, device_info, account_number, "last_bill")
        self._attr_name = f"Octopus Last Bill {account_number}"
        self._attr_native_unit_of_measurement = CURRENCY_YEN
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:receipt-text"

    @property
    def native_value(self) -> decimal.Decimal | None:
        """返回上一张账单的总额 (Gross)"""
        if not self.coordinator.data:
            return None
        
        try:
            bill = self.coordinator.data["bills"]["edges"][0]["node"]
            bill_type = bill.get("__typename")
            
            # --- 最终修正 ---
            # 根据你的成功JSON
            if bill_type == "PeriodBasedDocumentType":
                return bill['totalCharges']['grossTotal']
            elif bill_type == "InvoiceType":
                return bill.get("grossAmount")
            elif bill_type == "StatementType":
                return bill['totalCharges']['grossTotal']
                
        except (KeyError, IndexError, TypeError):
            # (如果 "edges" 列表为空, 即没有账单, 返回 None)
            return None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """将账单详情作为属性"""
        if not self.coordinator.data:
            return {}
            
        try:
            bill = self.coordinator.data["bills"]["edges"][0]["node"]
            bill_type = bill.get("__typename")
            attrs = {"bill_id": bill.get("id"), "bill_type": bill_type}

            if bill_type == "PeriodBasedDocumentType":
                attrs["issued_date"] = bill.get("issuedDate")
            elif bill_type == "InvoiceType":
                attrs["issued_date"] = bill.get("issuedDate")
                attrs["due_date"] = bill.get("toDate")
            elif bill_type == "StatementType":
                attrs["issued_date"] = bill.get("issuedDate")
                attrs["due_date"] = bill.get("paymentDueDate")
            
            return attrs
            
        except (KeyError, IndexError, TypeError):
            pass
        return {}


class OctopusProductSensor(OctopusBaseSensor):
    """传感器：当前电价套餐"""
    def __init__(self, coordinator, device_info, account_number):
        super().__init__(coordinator, device_info, account_number, "product")
        self._attr_name = f"Octopus Product {account_number}"
        self._attr_icon = "mdi:file-document"

    @property
    def native_value(self) -> str | None:
        """返回套餐名称"""
        if self.coordinator.data:
            try:
                return self.coordinator.data["properties"][0]["electricitySupplyPoints"][0]["agreements"][0]["product"]["displayName"]
            except (KeyError, IndexError, TypeError):
                return "Unknown"
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """将电价详情作为属性"""
        if self.coordinator.data:
            try:
                product = self.coordinator.data["properties"][0]["electricitySupplyPoints"][0]["agreements"][0]["product"]
                attrs = {}
                
                if charges := product.get("standingCharges"):
                    attrs["standing_charge"] = charges[0].get("pricePerUnit")
                
                if adjustment := product.get("fuelCostAdjustment"):
                    attrs["fuel_cost_adjustment"] = adjustment.get("pricePerUnit")
                
                if cons_charges := product.get("consumptionCharges"):
                    sorted_steps = sorted(cons_charges, key=lambda x: x["stepStart"])
                    if len(sorted_steps) == 1 and "stepStart" not in sorted_steps[0]:
                        attrs["unit_rate"] = sorted_steps[0].get("pricePerUnit")
                    else:
                        for i, step in enumerate(sorted_steps):
                            attrs[f"unit_rate_step_{i+1}"] = f"({step.get('stepStart')}~{step.get('stepEnd')}): {step.get('pricePerUnit')}"
                
                return attrs
                
            except (KeyError, IndexError, TypeError):
                pass

        return {}

