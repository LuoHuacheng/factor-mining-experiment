"""OKX REST v5 客户端 —— 公开行情接口（无需鉴权）

私有接口（下单/持仓）不在本计划范围；Phase 3 扩展时在
本模块加签名（HMAC-SHA256 + passphrase）而非另起客户端。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("qihuo.okx.client")

OKX_BASE_URL = "https://www.okx.com"

# 模拟盘开关：OKX 用请求头而非独立域名
DEMO_HEADER = "x-simulated-trading"

# OKX 业务码：0 为成功
_OK_CODE = "0"


class OkxApiError(Exception):
    """OKX 返回非 0 业务码"""

    def __init__(self, code: str, msg: str) -> None:
        self.code = str(code)
        self.msg = str(msg)
        super().__init__(f"OKX {self.code}: {self.msg}")


class OkxRestClient:
    """薄封装：统一业务码校验与 data 提取"""

    def __init__(
        self,
        base_url: str = OKX_BASE_URL,
        demo: bool = False,
        timeout: float = 10.0,
    ) -> None:
        headers: dict[str, str] = {}
        if demo:
            headers[DEMO_HEADER] = "1"
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """GET 并返回 data 数组；业务码非 0 抛 OkxApiError"""
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        body = resp.json()
        code = str(body.get("code") or "")
        if code != _OK_CODE:
            raise OkxApiError(code, str(body.get("msg") or ""))
        data = body.get("data")
        return data if isinstance(data, list) else []
