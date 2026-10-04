import os
import json
import time
import datetime
from pathlib import Path

from dotenv import load_dotenv
from pybit.unified_trading import HTTP

from ai_providers import get_all_signals
from consensus import consensus
from telegram_bot import (
    alert_trade_opened,
    alert_cycle_summary,
    alert_error,
    send_message,
)
from position_manager import manage_positions

load_dotenv()

session = HTTP(
    testnet=False,
    demo=True,
    api_key=os.getenv("BYBIT_API_KEY"),
    api_secret=os.getenv("BYBIT_API_SECRET"),
)

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

RISK_PER_TRADE_PCT = 2.0
MIN_CONSENSUS_CONFIDENCE = 60
MAX_OPEN_POSITIONS = 3
DAILY_LOSS_LIMIT_PCT = 10.0
LEVERAGE = 3

# ??? ?????
POSITION_CHECK_INTERVAL_SEC = 300   # 5 ????? — ???? position management
AI_CYCLE_INTERVAL_SEC = 900         # 15 ????? — AI ???????? + ???? ?????

SL_PCT = 0.008
TP_PCT = 0.016

STATE_FILE = "state.json"
LOG_FILE = "bot.log"
INSTRUMENT_CACHE = {}


def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state():
    today = str(datetime.date.today())
    if Path(STATE_FILE).exists():
        try:
            with open(STATE_FILE) as f:
                s = json.load(f)
            if s.get("date") != today:
                s = {"date": today, "start_balance": None, "trades_today": 0}
            return s
        except Exception:
            pass
    return {"date": today, "start_balance": None, "trades_today": 0}


def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


def get_instrument_info(symbol):
    if symbol in INSTRUMENT_CACHE:
        return INSTRUMENT_CACHE[symbol]
    try:
        r = session.get_instruments_info(category="linear", symbol=symbol)
        if r["retCode"] != 0 or not r["result"]["list"]:
            return None
        info = r["result"]["list"][0]
        lot = info.get("lotSizeFilter", {})
        price = info.get("priceFilter", {})
        parsed = {
            "qtyStep": float(lot.get("qtyStep", "0.001")),
            "minOrderQty": float(lot.get("minOrderQty", "0.001")),
            "minNotional": float(lot.get("minNotionalValue", "5")),
            "tickSize": float(price.get("tickSize", "0.01")),
        }
        INSTRUMENT_CACHE[symbol] = parsed
        return parsed
    except Exception as e:
        log(f"instrument_info {symbol}: {str(e)[:60]}")
        return None


def decimals_from_step(step):
    s = f"{step:.10f}".rstrip("0")
    if "." in s:
        return len(s.split(".")[1])
    return 0


def round_step(value, step):
    if step <= 0:
        return value
    d = decimals_from_step(step)
    return round(round(value / step) * step, d)


def format_qty(qty, step):
    d = decimals_from_step(step)
    return f"{round_step(qty, step):.{d}f}"


def format_price(price, tick):
    d = decimals_from_step(tick)
    return f"{round_step(price, tick):.{d}f}"


def get_balance():
    try:
        r = session.get_wallet_balance(accountType="UNIFIED")
        if r["retCode"] != 0:
            return None
        for c in r["result"]["list"][0]["coin"]:
            if c["coin"] == "USDT":
                return float(c["walletBalance"])
    except Exception as e:
        log(f"balance error: {e}")
    return None


def get_open_positions():
    try:
        r = session.get_positions(category="linear", settleCoin="USDT")
        if r["retCode"] != 0:
            return {}
        return {p["symbol"]: p for p in r["result"]["list"] if float(p.get("size", 0)) > 0}
    except Exception as e:
        log(f"positions error: {e}")
        return {}


def get_rsi(symbol, interval="15", period=14):
    try:
        k = session.get_kline(category="linear", symbol=symbol, interval=interval, limit=30)
        candles = list(reversed(k["result"]["list"]))
        closes = [float(c[4]) for c in candles]
        gains, losses = [], []
        for i in range(1, len(closes)):
            d = closes[i] - closes[i - 1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        ag = sum(gains[-period:]) / period
        al = sum(losses[-period:]) / period
        if al == 0:
            return 100.0
        return round(100 - (100 / (1 + ag / al)), 2)
    except Exception:
        return None


def get_market_data(symbol):
    try:
        t = session.get_tickers(category="linear", symbol=symbol)
        if t["retCode"] != 0:
            return None
        ticker = t["result"]["list"][0]
        return {
            "price": float(ticker["lastPrice"]),
            "change_24h": round(float(ticker["price24hPcnt"]) * 100, 2),
            "funding_rate": round(float(ticker.get("fundingRate", 0)) * 100, 4),
            "rsi_15m": get_rsi(symbol),
        }
    except Exception as e:
        log(f"market_data {symbol}: {str(e)[:50]}")
        return None


def calculate_position(symbol, signal, balance):
    bias = signal.get("bias")
    confidence = signal.get("confidence", 0)
    entry = signal.get("price")

    if bias not in ("long", "short"):
        return None
    if confidence < MIN_CONSENSUS_CONFIDENCE:
        return None
    if not entry:
        return None

    info = get_instrument_info(symbol)
    if not info:
        log(f"{symbol}: instrument info unavailable")
        return None

    if bias == "long":
        sl = entry * (1 - SL_PCT)
        tp = entry * (1 + TP_PCT)
    else:
        sl = entry * (1 + SL_PCT)
        tp = entry * (1 - TP_PCT)

    sl = round_step(sl, info["tickSize"])
    tp = round_step(tp, info["tickSize"])

    risk_usd = balance * (RISK_PER_TRADE_PCT / 100)
    price_risk = abs(entry - sl)
    if price_risk <= 0:
        return None

    raw_qty = risk_usd / price_risk
    qty = round_step(raw_qty, info["qtyStep"])

    if qty < info["minOrderQty"]:
        qty = info["minOrderQty"]
        log(f"{symbol}: qty raised to minOrderQty {info['minOrderQty']}")

    notional = qty * entry
    if notional < info["minNotional"]:
        log(f"{symbol}: notional ${notional:.2f} < ${info['minNotional']}, skip")
        return None

    return {
        "symbol": symbol,
        "bias": bias,
        "confidence": confidence,
        "entry": round(entry, 8),
        "sl": sl,
        "tp": tp,
        "qty": qty,
        "qty_str": format_qty(qty, info["qtyStep"]),
        "notional": round(notional, 2),
        "risk_usd": round(risk_usd, 2),
        "tickSize": info["tickSize"],
        "qtyStep": info["qtyStep"],
    }


def set_leverage(symbol):
    try:
        r = session.set_leverage(
            category="linear", symbol=symbol,
            buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE),
        )
        return r["retCode"] in (0, 110043)
    except Exception:
        return False


def place_order(t):
    try:
        side = "Buy" if t["bias"] == "long" else "Sell"
        r = session.place_order(
            category="linear",
            symbol=t["symbol"],
            side=side,
            orderType="Market",
            qty=t["qty_str"],
            takeProfit=format_price(t["tp"], t["tickSize"]),
            stopLoss=format_price(t["sl"], t["tickSize"]),
            tpTriggerBy="LastPrice",
            slTriggerBy="LastPrice",
            timeInForce="IOC",
        )
        if r["retCode"] != 0:
            return {"ok": False, "error": r["retMsg"]}
        return {"ok": True, "order_id": r["result"]["orderId"]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:80]}


# ========================================================
# Position Check — ????? ? ??????
# ========================================================
def position_check():
    """???? position management — TP1 hit? SL ????? ????"""
    try:
        manage_positions(log_func=log)
    except Exception as e:
        log(f"position manager error: {str(e)[:80]}")


# ========================================================
# AI Cycle — ????? ?? ??????
# ========================================================
def ai_cycle():
    """AI ???????? + ???? ?????"""
    log("=" * 50)
    log("AI Cycle started")

    state = load_state()
    balance = get_balance()
    if balance is None:
        log("balance fetch failed, skip AI cycle")
        return

    if state["start_balance"] is None:
        state["start_balance"] = balance
        save_state(state)

    daily_pnl_pct = ((balance - state["start_balance"]) / state["start_balance"]) * 100
    log(f"Balance: ${balance:.2f} | Daily PnL: {daily_pnl_pct:+.2f}%")

    if daily_pnl_pct <= -DAILY_LOSS_LIMIT_PCT:
        log(f"Daily loss limit hit ({daily_pnl_pct:.2f}%), skip")
        try:
            msg = "KILL SWITCH\n\nDaily loss limit hit: " + f"{daily_pnl_pct:.2f}%"
            send_message(msg)
        except Exception:
            pass
        return

    positions = get_open_positions()
    log(f"Open positions: {len(positions)} -> {list(positions.keys())}")

    if len(positions) >= MAX_OPEN_POSITIONS:
        log("Max positions reached, skip new trades")
        return

    signals_snapshot = {}

    for symbol in COINS:
        if symbol in positions:
            log(f"{symbol}: already have position, skip")
            continue

        data = get_market_data(symbol)
        if not data:
            log(f"{symbol}: no data")
            continue

        raw_signals = get_all_signals(symbol, data)
        result = consensus(raw_signals)
        result["price"] = data["price"]
        result["rsi_15m"] = data["rsi_15m"]

        signals_snapshot[symbol] = {
            "price": data["price"],
            "rsi_15m": data["rsi_15m"],
            "change_24h": data["change_24h"],
            "funding_rate": data["funding_rate"],
            "groq": raw_signals.get("groq"),
            "gemini": raw_signals.get("gemini"),
            "consensus": result,
        }

        g_bias = (raw_signals.get("groq") or {}).get("bias", "-")
        gm_bias = (raw_signals.get("gemini") or {}).get("bias", "-")
        log(
            f"{symbol}: groq={g_bias} gemini={gm_bias} -> consensus={result['bias']} ({result['confidence']}%)"
        )

        trade = calculate_position(symbol, result, balance)
        if not trade:
            continue

        set_leverage(symbol)
        time.sleep(0.3)

        res = place_order_with_tps(trade)
        if res["ok"]:
            log(
                f"{symbol}: ORDER PLACED {res['order_id']} | qty={trade['qty_str']} "
                f"entry=${trade['entry']} SL=${trade['sl']} TP=${trade['tp']} "
                f"notional=${trade['notional']} confidence={trade['confidence']}%"
            )
            state["trades_today"] += 1
            save_state(state)
            try:
                alert_trade_opened(
                    symbol, trade["bias"], trade["entry"], trade["sl"],
                    trade["tp"], trade["qty_str"], trade["confidence"],
                )
            except Exception as e:
                log(f"telegram alert failed: {str(e)[:50]}")
            if len(positions) + state["trades_today"] >= MAX_OPEN_POSITIONS:
                break
        else:
            log(f"{symbol}: order failed - {res['error']}")
        time.sleep(0.5)

    try:
        if signals_snapshot:
            alert_cycle_summary(signals_snapshot, balance)
    except Exception as e:
        log(f"summary alert failed: {str(e)[:50]}")

    with open("signals.json", "w") as f:
        json.dump(signals_snapshot, f, indent=2, default=str)

    log("AI Cycle ended")


# backward-compat: ????? ???
def run_once():
    position_check()
    ai_cycle()


def main():
    log("=" * 50)
    log("BOT STARTED (5m position check + 15m AI cycle)")
    log(f"Coins: {COINS}")
    log(f"Risk/trade: {RISK_PER_TRADE_PCT}% | Max positions: {MAX_OPEN_POSITIONS}")
    log(f"Position check: every {POSITION_CHECK_INTERVAL_SEC}s ({POSITION_CHECK_INTERVAL_SEC//60}m)")
    log(f"AI cycle: every {AI_CYCLE_INTERVAL_SEC}s ({AI_CYCLE_INTERVAL_SEC//60}m)")

    try:
        send_message("BOT STARTED\n\n5m position check + 15m AI cycle")
    except Exception:
        pass

    last_ai = 0

    while True:
        try:
            now = time.time()

            # ?. ?????? position check (? ??????)
            position_check()

            # ?. AI cycle ???? ?? ????? ???
            if now - last_ai >= AI_CYCLE_INTERVAL_SEC:
                ai_cycle()
                last_ai = now
            else:
                log(f"Position check only. Next AI cycle in {int(AI_CYCLE_INTERVAL_SEC - (now - last_ai))}s")

        except KeyboardInterrupt:
            log("Stopped by user")
            break
        except Exception as e:
            log(f"Loop error: {str(e)[:120]}")

        log(f"Sleeping {POSITION_CHECK_INTERVAL_SEC}s...")
        time.sleep(POSITION_CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        position_check()
        ai_cycle()
    elif len(sys.argv) > 1 and sys.argv[1] == "position":
        position_check()
    else:
        main()
def place_order_with_tps(t):
    """
    Market entry + SL + 3 limit TPs (reduceOnly)?
    TP1 @ 1:1 = 40%, TP2 @ 1.5:1 = 30%, TP3 @ 2:1 = 30%
    """
    symbol = t["symbol"]
    side = t["bias"]
    entry = t["entry"]
    sl = t["sl"]
    qty = t["qty"]
    tick = t["tickSize"]
    step = t["qtyStep"]

    buy_side = "Buy" if side == "long" else "Sell"
    close_side = "Sell" if side == "long" else "Buy"

    risk = abs(entry - sl)
    if risk <= 0:
        return {"ok": False, "error": "invalid risk"}

    # TP ?????
    if side == "long":
        tp1 = round_step(entry + risk * 1.0, tick)
        tp2 = round_step(entry + risk * 1.5, tick)
        tp3 = round_step(entry + risk * 2.0, tick)
    else:
        tp1 = round_step(entry - risk * 1.0, tick)
        tp2 = round_step(entry - risk * 1.5, tick)
        tp3 = round_step(entry - risk * 2.0, tick)

    # Qty ???
    info = get_instrument_info(symbol)
    if not info:
        return {"ok": False, "error": "no instrument info"}

    qty1 = round_step(qty * 0.40, step)
    qty2 = round_step(qty * 0.30, step)
    qty3 = round_step(qty - qty1 - qty2, step)

    # Min check
    if qty1 < info["minOrderQty"] or qty2 < info["minOrderQty"] or qty3 < info["minOrderQty"]:
        # TP ??? ??? single TP fallback
        log(f"{symbol}: TPs too small for split, using single TP")
        return place_order(t)

    try:
        # 1. Entry + SL (main position)
        r = session.place_order(
            category="linear",
            symbol=symbol,
            side=buy_side,
            orderType="Market",
            qty=format_qty(qty, step),
            stopLoss=format_price(sl, tick),
            slTriggerBy="LastPrice",
            timeInForce="IOC",
        )
        if r["retCode"] != 0:
            return {"ok": False, "error": r["retMsg"]}

        order_id = r["result"]["orderId"]

        # 2. ????? TP limit order (reduceOnly)
        tp_results = []
        for label, tp_price, tp_qty in [
            ("TP1", tp1, qty1),
            ("TP2", tp2, qty2),
            ("TP3", tp3, qty3),
        ]:
            time.sleep(0.25)
            tr = session.place_order(
                category="linear",
                symbol=symbol,
                side=close_side,
                orderType="Limit",
                qty=format_qty(tp_qty, step),
                price=format_price(tp_price, tick),
                reduceOnly=True,
                timeInForce="GTC",
            )
            if tr["retCode"] == 0:
                tp_results.append(f"{label}={format_price(tp_price, tick)} qty={format_qty(tp_qty, step)}")
            else:
                tp_results.append(f"{label}=FAIL({tr['retMsg'][:30]})")

        log(f"{symbol}: TPs set -> {' | '.join(tp_results)}")
        return {"ok": True, "order_id": order_id, "tps": tp_results}

    except Exception as e:
        return {"ok": False, "error": str(e)[:80]}

