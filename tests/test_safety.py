import unittest
from unittest.mock import patch

from consensus import consensus


class ConsensusTests(unittest.TestCase):
    def test_missing_provider_is_neutral(self):
        result = consensus({"groq": {"bias": "long", "confidence": 90, "reason": "up"}, "gemini": None})
        self.assertEqual(result["bias"], "neutral")

    def test_disagreement_is_neutral(self):
        signals = {
            "groq": {"bias": "long", "confidence": 80, "reason": "up"},
            "gemini": {"bias": "short", "confidence": 90, "reason": "down"},
        }
        self.assertEqual(consensus(signals)["bias"], "neutral")


class TradingGuardTests(unittest.TestCase):
    def test_position_api_failure_returns_unknown_not_empty(self):
        from main import get_open_positions
        with patch("main.session.get_positions", return_value={"retCode": 10001, "retMsg": "fail"}):
            self.assertIsNone(get_open_positions())

    def test_minimum_quantity_never_increases_risk(self):
        from main import calculate_position
        info = {"qtyStep": 1.0, "minOrderQty": 10.0, "minNotional": 5.0, "tickSize": 0.01}
        with patch("main.get_instrument_info", return_value=info):
            trade = calculate_position("BTCUSDT", {"bias": "long", "confidence": 80, "price": 100.0}, 10.0)
            self.assertIsNone(trade)

    def test_fill_check_unknown_returns_none(self):
        from main import verify_entry_fill
        with patch("main.session.get_order_history", return_value={"retCode": 10001}), patch("main.time.sleep"):
            self.assertIsNone(verify_entry_fill("BTCUSDT", "order-id", 0.001))


if __name__ == "__main__":
    unittest.main()
