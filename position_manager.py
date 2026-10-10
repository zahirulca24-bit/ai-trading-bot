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

STATE_FILE = "pm_state.json"

# SL advance threshold — 0.3:1 হিট হলেই SL entry+fees এ সরাবে
SL_LOCK_RR = 0.3
FEE_BUFFER_PCT = 0.0015  # 0.15% (entry+exit fee + slippage)


def _load_state():
    if Path(STATE_FILE).exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _decimals(step):
    s = f"{step:.10f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


def _round_step(value, step):
    if step <= 0:
        return value
    return round(round(value / step) * step, _decimals(step))


def _fmt_price(price, tick):
    return f"{_round_step(price, tick):.{_decimals(tick)}f}"


def _info(symbol):
    try:
        r = _session.get_instruments_info(category="linear", symbol=symbol)
        if r["retCode"] != 0 or not r["result"]["list"]:
            return None
        i = r["result"]["list"][0]
        lot = i.get("lotSizeFilter", {})
        prc = i.get("priceFilter", {})
        return {
            "qtyStep": float(lot.get("qtyStep", "0.001")),
            "minOrderQty": float(lot.get("minOrderQty", "0.001")),
            "tickSize": float(prc.get("tickSize", "0.01")),
        }
    except Exception:
        return None


def _positions():
    try:
        r = _session.get_positions(category="linear", settleCoin="USDT")
        if r["retCode"] != 0:
            return None
        return [p for p in r["result"]["list"] if float(p.get("size", 0)) > 0]
    except Exception:
        return None


def _set_sl(symbol, sl_price, tick):
    try:
        r = _session.set_trading_stop(
            category="linear", symbol=symbol,
            stopLoss=_fmt_price(sl_price, tick),
            slTriggerBy="LastPrice", positionIdx=0,
        )
        return r["retCode"] == 0, r.get("retMsg", "")
    except Exception as e:
        return False, str(e)[:80]


def manage_positions(log_func=None):
    """
    Pure Python, no AI.
    কাজ: 0.3:1 hit হলে SL entry+fees-এ সরাও।
    Multiple TP Bybit নিজে handle করে — এখানে কিছু করতে হয় না।
    """
    def _log(m):
        (log_func or print)(m)

    positions = _positions()
    if positions is None:
        (log_func or print)("[PM] positions API unavailable; preserving state")
        return
    state = _load_state()
    changed = False

    # Closed position গুলোর state মুছো
    open_syms = {p["symbol"] for p in positions}
    for s in list(state.keys()):
        if s not in open_syms:
            del state[s]
            changed = True
            _log(f"[PM] {s}: cleared (position closed)")

    if not positions:
        if changed:
            _save_state(state)
        return

    for pos in positions:
        symbol = pos["symbol"]
        side = pos["side"]
        entry = float(pos["avgPrice"])
        sl = float(pos.get("stopLoss", 0) or 0)
        current = float(pos.get("markPrice", 0) or 0)

        if entry == 0 or sl == 0 or current == 0:
            continue

        st = state.setdefault(symbol, {
            "entry": entry,
            "side": side,
            "original_sl": sl,
            "locked": False,
        })

        if st.get("side") != side or abs(float(st.get("entry") or 0) - entry) > max(entry * 0.000001, 1e-8):
            st = {"entry": entry, "side": side, "original_sl": sl, "locked": False}
            state[symbol] = st
            changed = True
        if st.get("locked"):
            continue

        risk = abs(entry - st["original_sl"])
        if risk <= 0:
            continue

        # 0.3:1 threshold
        if side == "Buy":
            threshold = entry + risk * SL_LOCK_RR
            reached = current >= threshold
        else:
            threshold = entry - risk * SL_LOCK_RR
            reached = current <= threshold

        if not reached:
            continue

        info = _info(symbol)
        if not info:
            continue

        # SL = entry ± fees buffer
        if side == "Buy":
            locked_sl = entry * (1 + FEE_BUFFER_PCT)
            if locked_sl <= sl:
                continue  # ইতিমধ্যে আরও ভালো
        else:
            locked_sl = entry * (1 - FEE_BUFFER_PCT)
            if locked_sl >= sl:
                continue

        ok, msg = _set_sl(symbol, locked_sl, info["tickSize"])
        if ok:
            _log(f"[PM] {symbol}: 0.3:1 hit @ {current:.6f} -> SL locked at {locked_sl:.6f} (entry+fees)")
            st["locked"] = True
            st["locked_sl"] = locked_sl
            changed = True
        else:
            _log(f"[PM] {symbol}: SL lock failed - {msg}")

    if changed:
        _save_state(state)


if __name__ == "__main__":
    print("Position Manager (pure Python, no AI)\n")
    manage_positions()
