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
        self._token_expiry: Optional[datetime.datetime] = None

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
            
            # 获取 token 和过期时间
            token_data = data["data"]["obtainKrakenToken"]
            self._token = token_data["token"]
            
            # 解析 token payload 来获取过期时间
            # JWT 的第二部分是 payload，包含过期时间
            # 但为了简单起见，我们设置一个保守的过期时间（比如 50 分钟）
            # 因为 Octopus 的 token 通常是 1 小时有效
            self._token_expiry = datetime.datetime.now() + datetime.timedelta(minutes=50)
            _LOGGER.debug(f"Token obtained, expires at {self._token_expiry}")
            
            return self._token
    
    async def _ensure_valid_token(self):
        """确保 token 有效，如果需要则刷新"""
        if self._token is None or self._token_expiry is None:
            _LOGGER.debug("No token found, requesting new one")
            await self.async_get_token()
        elif datetime.datetime.now() >= self._token_expiry:
            _LOGGER.debug("Token expired or about to expire, refreshing")
            await self.async_get_token()

    async def async_get_account_number(self) -> str:
        """获取账户号码 (来自 octopus.py)"""
        # 确保 token 有效
        await self._ensure_valid_token()

        headers = {"authorization": f"JWT {self._token}"}
        payload = {"query": GET_ACCOUNT_BODY}
        
        _LOGGER.debug("Requesting account number")
        async with self._session.post(self._api_url, json=payload, headers=headers) as resp:
            data = await resp.json()
            
            # 检查是否有 JWT 过期错误
            if "errors" in data:
                for error in data["errors"]:
                    if "JWT has expired" in error.get("message", "") or "KT-CT-1124" in error.get("extensions", {}).get("errorCode", ""):
                        _LOGGER.info("Token expired, refreshing and retrying")
                        await self.async_get_token()
                        headers = {"authorization": f"JWT {self._token}"}
                        # 重试请求
                        async with self._session.post(self._api_url, json=payload, headers=headers) as retry_resp:
                            data = await retry_resp.json()
                        break
            
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
        # 确保 token 有效
        await self._ensure_valid_token()

        headers = {"authorization": f"JWT {self._token}"}
        variables = {
            "accountNumber": account_number,
            "startTime": start_time.isoformat(),
            "endTime": end_time.isoformat(),
        }
        payload = {"query": COMPREHENSIVE_ACCOUNT_QUERY, "variables": variables}

        _LOGGER.debug(f"Requesting comprehensive data for {account_number}")
        
        # 最多重试一次（如果遇到 token 过期错误）
        for attempt in range(2):
            async with self._session.post(self._api_url, json=payload, headers=headers) as resp:
                data = await resp.json()
                
                # 检查是否有 JWT 过期错误（可能在响应体中）
                if "errors" in data:
                    has_jwt_error = False
                    for error in data["errors"]:
                        error_msg = error.get("message", "")
                        error_code = error.get("extensions", {}).get("errorCode", "")
                        
                        if "JWT has expired" in error_msg or "Signature of the JWT has expired" in error_msg or error_code == "KT-CT-1124":
                            has_jwt_error = True
                            break
                    
                    if has_jwt_error and attempt == 0:
                        _LOGGER.info("Token expired (detected from error response), refreshing and retrying")
                        await self.async_get_token()
                        headers = {"authorization": f"JWT {self._token}"}
                        continue  # 重试
                    elif has_jwt_error:
                        # 第二次还是失败，抛出异常
                        raise Exception(f"Failed to get comprehensive data after token refresh: {data['errors']}")
                    else:
                        # 其他类型的错误
                        raise Exception(f"Failed to get comprehensive data: {data['errors']}")
                
                # 检查 HTTP 状态码
                if resp.status == 401 and attempt == 0:
                    _LOGGER.info("Got 401 status, refreshing token and retrying")
                    await self.async_get_token()
                    headers = {"authorization": f"JWT {self._token}"}
                    continue  # 重试
                elif resp.status >= 400:
                    _LOGGER.error("Failed to get comprehensive data: %s", data)
                    resp.raise_for_status()
                
                # 成功获取数据
                break
        
        # 返回 'account' 键下的所有数据
        return data["data"]["account"]
