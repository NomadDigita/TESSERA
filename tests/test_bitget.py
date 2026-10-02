import base64
import hashlib
import hmac
import json
import unittest

from tessera.bitget import BitgetCredentials, BitgetDemoClient, BitgetError, sign_request
from tessera.domain import OrderIntent
from tessera.services import BitgetDemoBroker, CapitalOrchestrator


class RecordingTransport:
    def __init__(self, response=None):
        self.response = response or {"code": "00000", "msg": "success", "data": {"orderId": "42", "clientOid": "tessera-1"}}
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body, "timeout": timeout})
        return self.response


class BitgetTests(unittest.TestCase):
    def test_signature_matches_official_hmac_construction(self):
        message = '1700000000000POST/api/v3/trade/place-order{"a":1}'
        expected = base64.b64encode(hmac.new(b"secret", message.encode(), hashlib.sha256).digest()).decode()
        self.assertEqual(sign_request("1700000000000", "POST", "/api/v3/trade/place-order", "", '{"a":1}', "secret"), expected)

    def test_every_private_request_forces_demo_header_and_signature(self):
        transport = RecordingTransport()
        client = BitgetDemoClient(BitgetCredentials("key", "secret", "pass"), transport=transport, clock=lambda: 1700000000)
        client.get_positions(symbol="BTCUSDT")
        call = transport.calls[0]
        self.assertEqual(call["headers"]["paptrading"], "1")
        self.assertEqual(call["headers"]["ACCESS-TIMESTAMP"], "1700000000000")
        self.assertTrue(call["headers"]["ACCESS-SIGN"])
        self.assertIn("category=USDT-FUTURES&symbol=BTCUSDT", call["url"])

    def test_reality_stock_uses_dedicated_endpoint(self):
        transport = RecordingTransport()
        client = BitgetDemoClient(BitgetCredentials("key", "secret", "pass"), transport=transport)
        client.place_order(symbol="rAAPLUSDT", side="buy", quantity=1, client_oid="tessera-1")
        call = transport.calls[0]
        self.assertTrue(call["url"].endswith("/api/v3/trade/place-reality-order"))
        self.assertEqual(json.loads(call["body"])["category"], "SPOT")

    def test_limit_order_requires_price(self):
        client = BitgetDemoClient(BitgetCredentials("key", "secret", "pass"), transport=RecordingTransport())
        with self.assertRaises(ValueError):
            client.place_order(symbol="BTCUSDT", side="buy", quantity=1, order_type="limit", client_oid="x")

    def test_exchange_error_is_not_treated_as_success(self):
        transport = RecordingTransport({"code": "40001", "msg": "invalid signature", "data": None})
        client = BitgetDemoClient(BitgetCredentials("key", "secret", "pass"), transport=transport)
        with self.assertRaises(BitgetError):
            client.get_assets()

    def test_non_https_base_url_is_rejected(self):
        with self.assertRaises(ValueError):
            BitgetDemoClient(BitgetCredentials("key", "secret", "pass"), base_url="http://api.bitget.com")

    def test_demo_broker_keeps_submission_separate_from_fill(self):
        class FakeClient:
            def get_assets(self): return {"data": []}
            def get_positions(self): return {"data": []}
            def place_order(self, **kwargs): return {"data": {"orderId": "42", "clientOid": kwargs["client_oid"]}}
            def get_order(self, **kwargs): return {"data": {"orderStatus": "filled", "avgPrice": "149.5"}}

        broker = BitgetDemoBroker(FakeClient())
        system = CapitalOrchestrator(broker=broker)
        run = system.create_run({"title": "Demo submission", "symbols": ["rAAPLUSDT"]})
        submitted = system.approve(run.run_id)
        self.assertEqual(submitted.status, "SUBMITTED")
        self.assertIsNone(submitted.autopsy)
        reconciled = system.reconcile(run.run_id)
        self.assertEqual(reconciled.status, "EXECUTED")
        self.assertEqual(reconciled.order["fill_price"], 149.5)
        self.assertIsNotNone(reconciled.autopsy)


if __name__ == "__main__":
    unittest.main()
