"""API client for Octopus Energy Japan."""
import aiohttp
import datetime
import decimal
import logging
from typing import Any, List, Optional

import pytz
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from aiohttp import ClientSession

from .const import CONF_API_URL, TIMEZONE

_LOGGER = logging.getLogger(__name__)

# --- 来自你的 localtime.py 的逻辑 ---
def get_tokyo_tz() -> pytz.tzinfo:
    """获取东京时区对象"""
    return pytz.timezone(TIMEZONE)

def get_midnight_in_tokyo(date: Optional[datetime.date] = None) -> datetime.datetime:
    """获取指定日期在东京的午夜零点时间"""
    if date is None:
        date = datetime.datetime.now(tz=get_tokyo_tz()).date()
    naive_midnight = datetime.datetime.combine(date, datetime.datetime.min.time())
    return get_tokyo_tz().localize(naive_midnight, is_dst=True)
# --- 结束 ---


# --- 高效的、统一的 GraphQL 查询 (最终修正版) ---
COMPREHENSIVE_ACCOUNT_QUERY = """
query ComprehensiveAccountQuery($accountNumber: String!, $startTime: DateTime!, $endTime: DateTime!) {
  account(accountNumber: $accountNumber) {
    number
    balance
    overdueBalance
    
    bills(first: 1, orderBy: FROM_DATE_DESC) {
      edges {
        node {
          id
          __typename  # (我们保留这个，它对解析很有用)
          
          # --- 这是你刚刚确认成功的片段 ---
          ... on PeriodBasedDocumentType {
            issuedDate
            totalCharges {
              grossTotal
            }
          }
          
          # (保留其他类型作为备用)
          ... on InvoiceType {
            issuedDate
            toDate
            grossAmount
          }
          ... on StatementType {
            issuedDate
            paymentDueDate
            totalCharges {
              grossTotal
            }
          }
        }
      }
    }
    
    properties {
      electricitySupplyPoints {
        agreements(onlyActive: true) {
          product {
            ... on ProductInterface {
              displayName
              standingCharges {
                pricePerUnit
              }
              fuelCostAdjustment {
                pricePerUnit
              }
            }
            ... on ElectricitySingleStepProduct {
              consumptionCharges {
                pricePerUnit
              }
            }
            ... on ElectricitySteppedProduct {
              consumptionCharges {
                pricePerUnit
                stepStart
                stepEnd
              }
            }
          }
        }
        halfHourlyReadings(fromDatetime: $startTime, toDatetime: $endTime) {
          startAt
          endAt
          value
        }
      }
    }
  }
}
"""

# 来自你的 octopus.py
AUTH_BODY = """
mutation obtainKrakenToken($input: ObtainJSONWebTokenInput!) {
  obtainKrakenToken(input: $input) {
    refreshToken
    refreshExpiresIn
    payload
    token
  }
}
"""

# 来自你的 octopus.py
GET_ACCOUNT_BODY = """
query accountViewer {
  viewer {
    accounts {
      number
    }
  }
}
"""

class OctopusEnergyJpApiClient:
    """处理与 Octopus Energy Japan API 通信的类"""

    def __init__(
        self,
        session: ClientSession,
        email: str,
        password: str,
        api_url: str,
    ):
        self._session = session
        self._email = email
        self._password = password
        self._api_url = api_url
        self._token: Optional[str] = None

    async def async_get_token(self) -> str:
        """获取 (或刷新) 认证 token."""
        _LOGGER.debug("Requesting new auth token")
        payload = {
            "query": AUTH_BODY,
            "variables": {
                "input": {"email": self._email, "password": self._password}
            },
        }
        
        async with self._session.post(self._api_url, json=payload) as resp:
            data = await resp.json()
            if resp.status >= 400:
                _LOGGER.error("Failed to get token: %s", data)
                resp.raise_for_status()
            self._token = data["data"]["obtainKrakenToken"]["token"]
            return self._token

    async def async_get_account_number(self) -> str:
        """获取账户号码 (来自 octopus.py)"""
        if not self._token:
            await self.async_get_token()

        headers = {"authorization": f"JWT {self._token}"}
        payload = {"query": GET_ACCOUNT_BODY}
        
        _LOGGER.debug("Requesting account number")
        async with self._session.post(self._api_url, json=payload, headers=headers) as resp:
            data = await resp.json()
            if resp.status >= 400:
                _LOGGER.error("Failed to get account number: %s", data)
                resp.raise_for_status()
            
            try:
                return data["data"]["viewer"]["accounts"][0]["number"]
            except (KeyError, IndexError):
                raise Exception("Account number not found in API response")

    async def async_get_data(self, account_number: str, start_time: datetime.datetime, end_time: datetime.datetime) -> dict[str, Any]:
        """
        执行统一的 GraphQL 查询以获取所有数据。
        这是 DataUpdateCoordinator 将调用的主要方法。
        """
        if not self._token:
            await self.async_get_token()

        headers = {"authorization": f"JWT {self._token}"}
        variables = {
            "accountNumber": account_number,
            "startTime": start_time.isoformat(),
            "endTime": end_time.isoformat(),
        }
        payload = {"query": COMPREHENSIVE_ACCOUNT_QUERY, "variables": variables}

        _LOGGER.debug(f"Requesting comprehensive data for {account_number}")
        async with self._session.post(self._api_url, json=payload, headers=headers) as resp:
            # 令牌过期处理
            if resp.status == 401:
                _LOGGER.info("Token expired, requesting new one.")
                self._token = None # 清除旧 token
                await self.async_get_token() # 获取新 token
                headers = {"authorization": f"JWT {self._token}"} # 更新 headers
                # 重新发送请求
                async with self._session.post(self._api_url, json=payload, headers=headers) as retry_resp:
                    data = await retry_resp.json()
                    if retry_resp.status >= 400:
                        _LOGGER.error("Failed to get comprehensive data (on retry): %s", data)
                        retry_resp.raise_for_status()
            else:
                data = await resp.json()
                if resp.status >= 400:
                    _LOGGER.error("Failed to get comprehensive data: %s", data)
                    resp.raise_for_status()

        if "errors" in data:
            raise Exception(f"Failed to get comprehensive data: {data['errors']}")
        
        # 返回 'account' 键下的所有数据

        return data["data"]["account"]
