import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv
from pybit.unified_trading import HTTP

load_dotenv()

_session = HTTP(
    testnet=False,
    demo=True,
    api_key=os.getenv("BYBIT_API_KEY"),
    api_secret=os.getenv("BYBIT_API_SECRET"),
)

TP1_FILE = "tp1_hit.json"
TP1_PCT = 0.30  # 30% ক্লোজ


def _load_tp1():
    if Path(TP1_FILE).exists():
        try:
            with open(TP1_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_tp1(data):
    with open(TP1_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _decimals_from_step(step):
    s = f"{step:.10f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


def _round_step(value, step):
    if step <= 0:
        return value
    d = _decimals_from_step(step)
    return round(round(value / step) * step, d)


def _format_qty(qty, step):
    d = _decimals_from_step(step)
    return f"{_round_step(qty, step):.{d}f}"


def _format_price(price, tick):
    d = _decimals_from_step(tick)
    return f"{_round_step(price, tick):.{d}f}"


def _get_instrument_info(symbol):
    try:
        r = _session.get_instruments_info(category="linear", symbol=symbol)
        if r["retCode"] != 0 or not r["result"]["list"]:
            return None
        info = r["result"]["list"][0]
        lot = info.get("lotSizeFilter", {})
        price = info.get("priceFilter", {})
        return {
            "qtyStep": float(lot.get("qtyStep", "0.001")),
            "minOrderQty": float(lot.get("minOrderQty", "0.001")),
            "tickSize": float(price.get("tickSize", "0.01")),
        }
    except Exception:
        return None


def _get_open_positions():
    try:
        r = _session.get_positions(category="linear", settleCoin="USDT")
        if r["retCode"] != 0:
            return []
        return [p for p in r["result"]["list"] if float(p.get("size", 0)) > 0]
    except Exception:
        return []


def _partial_close(symbol, side, qty_str):
    opposite = "Sell" if side == "Buy" else "Buy"
    try:
        r = _session.place_order(
            category="linear",
            symbol=symbol,
            side=opposite,
            orderType="Market",
            qty=qty_str,
            reduceOnly=True,
            timeInForce="IOC",
        )
        return r["retCode"] == 0, r.get("retMsg", "")
    except Exception as e:
        return False, str(e)[:80]


def _move_sl_to_breakeven(symbol, entry_price, tick_size):
    sl_str = _format_price(entry_price, tick_size)
    try:
        r = _session.set_trading_stop(
            category="linear",
            symbol=symbol,
            stopLoss=sl_str,
            slTriggerBy="LastPrice",
            positionIdx=0,
        )
        return r["retCode"] == 0, r.get("retMsg", "")
    except Exception as e:
        return False, str(e)[:80]


def manage_positions(log_func=None):
    """
    প্রতিটি খোলা পজিশনের জন্য:
    - 1:1 RR লেভেল হিসাব করো
    - দাম সেখানে পৌঁছালে:
      * 30% পজিশন ক্লোজ করো
      * SL এন্ট্রিতে সরাও (breakeven)
    - tp1_hit.json-এ ট্র্যাক করো
    """
    def _log(msg):
        if log_func:
            log_func(msg)
        else:
            print(msg)

    positions = _get_open_positions()
    tp1_hit = _load_tp1()
    changed = False

    # Closed positions এর entry মুছে ফেলো
    open_symbols = {p["symbol"] for p in positions}
    for sym in list(tp1_hit.keys()):
        if sym not in open_symbols:
            del tp1_hit[sym]
            changed = True
            _log(f"TP1 state cleared for {sym} (position closed)")

    if not positions:
        if changed:
            _save_tp1(tp1_hit)
        return

    for pos in positions:
        symbol = pos["symbol"]
        side = pos["side"]
        size = float(pos["size"])
        entry = float(pos["avgPrice"])
        sl = float(pos.get("stopLoss", 0) or 0)
        current = float(pos.get("markPrice", 0) or 0)

        if entry == 0 or sl == 0 or current == 0:
            continue

        if tp1_hit.get(symbol, {}).get("done"):
            continue

        # SL আগেই breakeven-এ থাকলে skip
        if abs(sl - entry) / entry < 0.001:
            tp1_hit[symbol] = {"done": True, "reason": "sl_already_be"}
            changed = True
            continue

        risk = abs(entry - sl)
        if side == "Buy":
            target = entry + risk
            reached = current >= target
        else:
            target = entry - risk
            reached = current <= target

        if not reached:
            continue

        _log(f"TP1 reached for {symbol} @ {current} (target {target:.6f})")

        info = _get_instrument_info(symbol)
        if not info:
            _log(f"  {symbol}: instrument info unavailable")
            continue

        # 1. Partial close 30%
        partial_qty = _round_step(size * TP1_PCT, info["qtyStep"])
        if partial_qty < info["minOrderQty"]:
            _log(f"  {symbol}: partial qty too small ({partial_qty}), skip close")
        else:
            qty_str = _format_qty(partial_qty, info["qtyStep"])
            ok, msg = _partial_close(symbol, side, qty_str)
            if ok:
                _log(f"  {symbol}: closed {qty_str} ({int(TP1_PCT*100)}%)")
            else:
                _log(f"  {symbol}: partial close failed - {msg}")

        # 2. Move SL to entry
        time.sleep(0.4)
        ok, msg = _move_sl_to_breakeven(symbol, entry, info["tickSize"])
        if ok:
            _log(f"  {symbol}: SL moved to entry (${entry})")
        else:
            _log(f"  {symbol}: SL move failed - {msg}")

        tp1_hit[symbol] = {
            "done": True,
            "entry": entry,
            "tp1_price": target,
            "closed_pct": TP1_PCT,
        }
        changed = True
        time.sleep(0.3)

    if changed:
        _save_tp1(tp1_hit)


if __name__ == "__main__":
    print("Position Manager Test\n")
    manage_positions()
