from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import time
from typing import Callable
from urllib import error, parse, request


class BitgetError(RuntimeError):
    pass


@dataclass(frozen=True)
class BitgetCredentials:
    api_key: str
    api_secret: str
    passphrase: str

    def validate(self) -> None:
        if not all((self.api_key, self.api_secret, self.passphrase)):
            raise ValueError("Bitget demo API key, secret, and passphrase are required")


def sign_request(timestamp: str, method: str, path: str, query: str, body: str, secret: str) -> str:
    suffix = f"?{query}" if query else ""
    message = f"{timestamp}{method.upper()}{path}{suffix}{body}"
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


Transport = Callable[[str, str, dict[str, str], bytes | None, float], dict]


def urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> dict:
    req = request.Request(url, data=body, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read())
    except error.HTTPError as exc:
        safe = exc.read(4096).decode(errors="replace")
        raise BitgetError(f"Bitget HTTP {exc.code}: {safe}") from exc
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise BitgetError(f"Bitget transport failed: {exc}") from exc


class BitgetDemoClient:
    """Authenticated UTA V3 client. Every private request is forced into demo mode."""

    def __init__(self, credentials: BitgetCredentials, base_url: str = "https://api.bitget.com",
                 transport: Transport = urllib_transport, timeout: float = 15.0,
                 clock: Callable[[], float] = time.time) -> None:
        credentials.validate()
        if not base_url.startswith("https://"):
            raise ValueError("Bitget base URL must use HTTPS")
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.timeout = timeout
        self.clock = clock

    def request(self, method: str, path: str, *, query: dict | None = None, payload: dict | None = None) -> dict:
        query_string = parse.urlencode(sorted((query or {}).items()))
        body_text = json.dumps(payload, separators=(",", ":"), sort_keys=True) if payload is not None else ""
        timestamp = str(int(self.clock() * 1000))
        headers = {
            "ACCESS-KEY": self.credentials.api_key,
            "ACCESS-SIGN": sign_request(timestamp, method, path, query_string, body_text, self.credentials.api_secret),
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.credentials.passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
            "paptrading": "1",
            "User-Agent": "TESSERA/0.1",
        }
        url = f"{self.base_url}{path}" + (f"?{query_string}" if query_string else "")
        result = self.transport(method.upper(), url, headers, body_text.encode() if body_text else None, self.timeout)
        if str(result.get("code")) != "00000":
            raise BitgetError(f"Bitget rejected request: code={result.get('code')} msg={result.get('msg')}")
        return result

    def get_assets(self) -> dict:
        return self.request("GET", "/api/v3/account/assets")

    def get_positions(self, category: str = "USDT-FUTURES", symbol: str | None = None) -> dict:
        query = {"category": category}
        if symbol:
            query["symbol"] = symbol
        return self.request("GET", "/api/v3/position/current-position", query=query)

    def get_order(self, *, order_id: str | None = None, client_oid: str | None = None) -> dict:
        if not order_id and not client_oid:
            raise ValueError("order_id or client_oid is required")
        query = {"orderId": order_id} if order_id else {"clientOid": client_oid}
        return self.request("GET", "/api/v3/trade/order-info", query=query)

    def place_order(self, *, symbol: str, side: str, quantity: float, order_type: str = "market",
                    price: float | None = None, category: str = "SPOT", client_oid: str) -> dict:
        if side.lower() not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if order_type not in {"market", "limit"}:
            raise ValueError("order_type must be market or limit")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        payload = {
            "category": category, "symbol": symbol, "side": side.lower(), "orderType": order_type,
            "qty": format(quantity, "g"), "clientOid": client_oid[:32],
        }
        if order_type == "limit":
            if price is None or price <= 0:
                raise ValueError("positive price is required for limit orders")
            payload.update({"price": format(price, "g"), "timeInForce": "gtc"})
        path = "/api/v3/trade/place-reality-order" if symbol.startswith("r") else "/api/v3/trade/place-order"
        return self.request("POST", path, payload=payload)

    def cancel_order(self, *, symbol: str, order_id: str | None = None, client_oid: str | None = None,
                     category: str = "SPOT") -> dict:
        if not order_id and not client_oid:
            raise ValueError("order_id or client_oid is required")
        payload = {"category": category, "symbol": symbol}
        payload["orderId" if order_id else "clientOid"] = order_id or client_oid
        path = "/api/v3/trade/cancel-reality-order" if symbol.startswith("r") else "/api/v3/trade/cancel-order"
        return self.request("POST", path, payload=payload)
