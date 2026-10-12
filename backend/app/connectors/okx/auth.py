"""OKX API v5 HMAC-SHA256 签名生成器与请求头封装"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone


def okx_iso_timestamp() -> str:
    """生成 OKX 要求的 ISO8601 UTC 时间戳，带毫秒，形如 2026-10-12T08:00:00.123Z"""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def generate_okx_signature(
    timestamp: str,
    method: str,
    request_path: str,
    body: str,
    secret_key: str,
) -> str:
    """计算 OKX HMAC-SHA256 签名（Base64 编码）

    Message: timestamp + method.upper() + request_path + body
    """
    message = f"{timestamp}{method.upper()}{request_path}{body or ''}"
    mac = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    return base64.b64encode(mac.digest()).decode("utf-8")


def build_okx_auth_headers(
    api_key: str,
    secret_key: str,
    passphrase: str,
    method: str,
    request_path: str,
    body: str = "",
    demo: bool = False,
    timestamp: str | None = None,
) -> dict[str, str]:
    """构造 OKX 私有接口请求头"""
    ts = timestamp or okx_iso_timestamp()
    sign = generate_okx_signature(ts, method, request_path, body, secret_key)
    headers = {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
    }
    if demo:
        headers["x-simulated-trading"] = "1"
    return headers
