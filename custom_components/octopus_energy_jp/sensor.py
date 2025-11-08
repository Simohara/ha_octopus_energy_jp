"""Platform for sensor integration."""
from __future__ import annotations

import datetime
import decimal
import logging
from typing import Any
import calendar

import pytz
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
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
            OctopusYesterdayConsumptionSensor(coordinator, device_info, account_number),
            OctopusCurrentMonthConsumptionSensor(coordinator, device_info, account_number),  # 当月累计用电
            OctopusCurrentMonthCostSensor(coordinator, device_info, account_number),  # 当月累计电费
            OctopusLastMonthConsumptionSensor(coordinator, device_info, account_number),
            OctopusMonthlyEstimateSensor(coordinator, device_info, account_number), # (本月预计)
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
        
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._tz = get_tokyo_tz() # 获取东京时区

    @property
    def native_value(self) -> decimal.Decimal | None:
        """返回今日累计用电量"""
        if not self.coordinator.data:
            return None
            
        try:
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


class OctopusYesterdayConsumptionSensor(OctopusBaseSensor):
    """
    传感器：昨日累计用电量
    """
    def __init__(self, coordinator, device_info, account_number):
        super().__init__(coordinator, device_info, account_number, "yesterday_consumption")
        self._attr_name = f"Octopus Yesterday Consumption {account_number}"
        
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        # 这是一个已完成的、固定的值，所以使用 TOTAL
        self._attr_state_class = SensorStateClass.TOTAL 
        self._tz = get_tokyo_tz()

    @property
    def native_value(self) -> decimal.Decimal | None:
        """返回昨日累计用电量"""
        if not self.coordinator.data:
            return None
            
        try:
            all_readings = self.coordinator.data["properties"][0]["electricitySupplyPoints"][0]["halfHourlyReadings"]
            
            total_consumption = decimal.Decimal(0)
            today_date = datetime.datetime.now(tz=self._tz).date()
            yesterday_date = today_date - datetime.timedelta(days=1)

            for reading in all_readings:
                start_at_utc = datetime.datetime.fromisoformat(reading["startAt"])
                start_at_tokyo = start_at_utc.astimezone(self._tz)
                
                if start_at_tokyo.date() == yesterday_date:
                    total_consumption += decimal.Decimal(reading["value"])
            
            return total_consumption

        except (KeyError, IndexError, TypeError):
            return None


class OctopusCurrentMonthConsumptionSensor(OctopusBaseSensor):
    """
    传感器：当月累计用电量
    """
    def __init__(self, coordinator, device_info, account_number):
        super().__init__(coordinator, device_info, account_number, "current_month_consumption")
        self._attr_name = f"Octopus Current Month Consumption {account_number}"
        
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._tz = get_tokyo_tz()

    @property
    def native_value(self) -> decimal.Decimal | None:
        """返回当月累计用电量"""
        if not self.coordinator.data:
            return None
            
        try:
            all_readings = self.coordinator.data["properties"][0]["electricitySupplyPoints"][0]["halfHourlyReadings"]
            
            total_consumption = decimal.Decimal(0)
            today_date = datetime.datetime.now(tz=self._tz).date()
            target_year = today_date.year
            target_month = today_date.month

            for reading in all_readings:
                start_at_utc = datetime.datetime.fromisoformat(reading["startAt"])
                start_at_tokyo = start_at_utc.astimezone(self._tz)
                reading_date = start_at_tokyo.date()
                
                if reading_date.year == target_year and reading_date.month == target_month:
                    total_consumption += decimal.Decimal(reading["value"])
            
            return total_consumption

        except (KeyError, IndexError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """返回额外属性"""
        if self.native_value is not None:
            today_date = datetime.datetime.now(tz=self._tz).date()
            days_so_far = today_date.day
            daily_average = self.native_value / days_so_far if days_so_far > 0 else 0
            
            return {
                "days_so_far": days_so_far,
                "daily_average": f"{daily_average:.2f}"
            }
        return {}


class OctopusCurrentMonthCostSensor(OctopusBaseSensor):
    """
    传感器：当月累计电费（到目前为止实际产生的费用）
    """
    def __init__(self, coordinator, device_info, account_number):
        super().__init__(coordinator, device_info, account_number, "current_month_cost")
        self._attr_name = f"Octopus Current Month Cost {account_number}"
        self._attr_native_unit_of_measurement = "JPY"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = "mdi:cash"
        self._tz = get_tokyo_tz()

    def _calculate_cost_for_kwh(self, total_kwh: decimal.Decimal, product_data: dict) -> decimal.Decimal:
        """计算给定电量的费用（不含基本费）"""
        # 获取电价结构
        fuel_adj_per_kwh = decimal.Decimal(product_data["fuelCostAdjustment"]["pricePerUnit"])
        consumption_steps = product_data["consumptionCharges"]
        
        # 计算阶梯电价
        consumption_cost = decimal.Decimal(0)
        remaining_kwh = total_kwh
        sorted_steps = sorted(consumption_steps, key=lambda x: x["stepStart"])

        for step in sorted_steps:
            price = decimal.Decimal(step["pricePerUnit"])
            step_start = decimal.Decimal(step["stepStart"])
            step_end = decimal.Decimal(step["stepEnd"]) if step["stepEnd"] is not None else decimal.Decimal('Infinity')
            
            step_width = step_end - step_start
            kwh_on_this_step = min(remaining_kwh, step_width)
            
            if kwh_on_this_step > 0:
                consumption_cost += kwh_on_this_step * price
                remaining_kwh -= kwh_on_this_step
            
            if remaining_kwh <= 0:
                break

        # 计算燃料调整费
        fuel_cost = total_kwh * fuel_adj_per_kwh
        
        return consumption_cost + fuel_cost

    @property
    def native_value(self) -> decimal.Decimal | None:
        """返回当月到目前为止的累计电费"""
        if not self.coordinator.data:
            return None
        
        try:
            # 1. 获取所有读数和产品数据
            all_readings = self.coordinator.data["properties"][0]["electricitySupplyPoints"][0]["halfHourlyReadings"]
            product_data = self.coordinator.data["properties"][0]["electricitySupplyPoints"][0]["agreements"][0]["product"]
            
            # 2. 计算本月总用电量
            total_kwh = decimal.Decimal(0)
            today_date = datetime.datetime.now(tz=self._tz).date()
            target_year = today_date.year
            target_month = today_date.month

            for r in all_readings:
                start_at_utc = datetime.datetime.fromisoformat(r["startAt"])
                start_at_tokyo = start_at_utc.astimezone(self._tz)
                reading_date = start_at_tokyo.date()
                
                if reading_date.year == target_year and reading_date.month == target_month:
                    total_kwh += decimal.Decimal(r["value"])

            # 3. 计算电费（用电费用 + 燃料调整费）
            usage_cost = self._calculate_cost_for_kwh(total_kwh, product_data)
            
            # 4. 计算基本料金（按实际天数）
            standing_charge_per_day = decimal.Decimal(product_data["standingCharges"][0]["pricePerUnit"])
            days_so_far = today_date.day
            standing_cost = standing_charge_per_day * days_so_far
            
            # 5. 总费用
            total_cost = usage_cost + standing_cost
            
            # 保存详情到属性
            self._attr_extra_state_attributes = {
                "total_kwh": f"{total_kwh:.2f}",
                "usage_cost": f"{usage_cost:.2f}",
                "standing_cost": f"{standing_cost:.2f}",
                "days_so_far": days_so_far,
            }
            
            return round(total_cost, 2)
            
        except (KeyError, IndexError, TypeError, decimal.InvalidOperation) as e:
            _LOGGER.error("Could not calculate current month cost: %s", e)
            return None


class OctopusLastMonthConsumptionSensor(OctopusBaseSensor):
    """
    传感器：上个月累计用电量
    """
    def __init__(self, coordinator, device_info, account_number):
        super().__init__(coordinator, device_info, account_number, "last_month_consumption")
        self._attr_name = f"Octopus Last Month Consumption {account_number}"
        
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        # 这是一个已完成的、固定的值，所以使用 TOTAL
        self._attr_state_class = SensorStateClass.TOTAL
        self._tz = get_tokyo_tz()

    @property
    def native_value(self) -> decimal.Decimal | None:
        """返回上个月累计用电量"""
        if not self.coordinator.data:
            return None
            
        try:
            all_readings = self.coordinator.data["properties"][0]["electricitySupplyPoints"][0]["halfHourlyReadings"]
            
            total_consumption = decimal.Decimal(0)
            
            # 计算上个月的年份和月份
            today_date = datetime.datetime.now(tz=self._tz).date()
            start_of_current_month = today_date.replace(day=1)
            last_day_of_prev_month = start_of_current_month - datetime.timedelta(days=1)
            target_year = last_day_of_prev_month.year
            target_month = last_day_of_prev_month.month

            for reading in all_readings:
                start_at_utc = datetime.datetime.fromisoformat(reading["startAt"])
                start_at_tokyo = start_at_utc.astimezone(self._tz)
                reading_date = start_at_tokyo.date()
                
                if reading_date.year == target_year and reading_date.month == target_month:
                    total_consumption += decimal.Decimal(reading["value"])
            
            return total_consumption

        except (KeyError, IndexError, TypeError):
            return None


class OctopusMonthlyEstimateSensor(OctopusBaseSensor):
    """传感器：本月预计电费（基于日均电费 × 当月天数）"""
    def __init__(self, coordinator, device_info, account_number):
        super().__init__(coordinator, device_info, account_number, "monthly_estimate")
        self._attr_name = f"Octopus Monthly Estimate {account_number}"
        self._attr_native_unit_of_measurement = "JPY"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:cash-clock"
        self._tz = get_tokyo_tz()

    def _calculate_cost_for_kwh(self, total_kwh: decimal.Decimal, product_data: dict) -> decimal.Decimal:
        """计算给定电量的费用（不含基本费）"""
        # 获取电价结构
        fuel_adj_per_kwh = decimal.Decimal(product_data["fuelCostAdjustment"]["pricePerUnit"])
        consumption_steps = product_data["consumptionCharges"]
        
        # 计算阶梯电价
        consumption_cost = decimal.Decimal(0)
        remaining_kwh = total_kwh
        sorted_steps = sorted(consumption_steps, key=lambda x: x["stepStart"])

        for step in sorted_steps:
            price = decimal.Decimal(step["pricePerUnit"])
            step_start = decimal.Decimal(step["stepStart"])
            step_end = decimal.Decimal(step["stepEnd"]) if step["stepEnd"] is not None else decimal.Decimal('Infinity')
            
            step_width = step_end - step_start
            kwh_on_this_step = min(remaining_kwh, step_width)
            
            if kwh_on_this_step > 0:
                consumption_cost += kwh_on_this_step * price
                remaining_kwh -= kwh_on_this_step
            
            if remaining_kwh <= 0:
                break

        # 计算燃料调整费
        fuel_cost = total_kwh * fuel_adj_per_kwh
        
        return consumption_cost + fuel_cost

    @property
    def native_value(self) -> decimal.Decimal | None:
        """返回预估的本月总费用（基于日均）"""
        if not self.coordinator.data:
            return None
        
        try:
            # 1. 获取所有读数和产品数据
            all_readings = self.coordinator.data["properties"][0]["electricitySupplyPoints"][0]["halfHourlyReadings"]
            product_data = self.coordinator.data["properties"][0]["electricitySupplyPoints"][0]["agreements"][0]["product"]
            
            # 2. 计算本月到目前为止的总用电量
            total_kwh_so_far = decimal.Decimal(0)
            today_date = datetime.datetime.now(tz=self._tz).date()
            target_year = today_date.year
            target_month = today_date.month

            for r in all_readings:
                start_at_utc = datetime.datetime.fromisoformat(r["startAt"])
                start_at_tokyo = start_at_utc.astimezone(self._tz)
                reading_date = start_at_tokyo.date()
                
                if reading_date.year == target_year and reading_date.month == target_month:
                    total_kwh_so_far += decimal.Decimal(r["value"])

            # 3. 计算日均用电量
            days_so_far = today_date.day
            if days_so_far == 0:
                return decimal.Decimal(0)
            
            daily_avg_kwh = total_kwh_so_far / days_so_far
            
            # 4. 获取当月总天数
            days_in_month = calendar.monthrange(target_year, target_month)[1]
            
            # 5. 预测整月用电量
            estimated_month_kwh = daily_avg_kwh * days_in_month
            
            # 6. 计算预测的电费
            estimated_usage_cost = self._calculate_cost_for_kwh(estimated_month_kwh, product_data)
            
            # 7. 计算整月基本料金
            standing_charge_per_day = decimal.Decimal(product_data["standingCharges"][0]["pricePerUnit"])
            standing_cost = standing_charge_per_day * days_in_month
            
            # 8. 总预计费用
            estimated_total = estimated_usage_cost + standing_cost
            
            # 将详情存入属性
            self._attr_extra_state_attributes = {
                "total_kwh_so_far": f"{total_kwh_so_far:.2f}",
                "daily_avg_kwh": f"{daily_avg_kwh:.2f}",
                "estimated_month_kwh": f"{estimated_month_kwh:.2f}",
                "estimated_usage_cost": f"{estimated_usage_cost:.2f}",
                "standing_cost": f"{standing_cost:.2f}",
                "days_so_far": days_so_far,
                "days_in_month": days_in_month,
            }
            
            return round(estimated_total, 2)
            
        except (KeyError, IndexError, TypeError, decimal.InvalidOperation) as e:
            _LOGGER.error("Could not calculate monthly estimate: %s", e)
            return None


class OctopusBalanceSensor(OctopusBaseSensor):
    """传感器：当前账户余额"""
    def __init__(self, coordinator, device_info, account_number):
        super().__init__(coordinator, device_info, account_number, "balance")
        self._attr_name = f"Octopus Balance {account_number}"
        self._attr_native_unit_of_measurement = "JPY"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = None
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
        self._attr_native_unit_of_measurement = "JPY"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = None
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
        self._attr_native_unit_of_measurement = "JPY"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = None
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