import os
import json
import time
import math
import datetime
from pathlib import Path

from dotenv import load_dotenv
from pybit.unified_trading import HTTP
from groq import Groq

load_dotenv()

session = HTTP(
    testnet=False,
    demo=True,
    api_key=os.getenv("BYBIT_API_KEY"),
    api_secret=os.getenv("BYBIT_API_SECRET"),
)
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]

RISK_PER_TRADE_PCT = 2.0
MIN_CONFIDENCE = 60
MAX_OPEN_POSITIONS = 3
DAILY_LOSS_LIMIT_PCT = 10.0
LEVERAGE = 3
LOOP_INTERVAL_SEC = 900
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
    """Bybit থেকে qtyStep, minOrderQty, tickSize, minNotional আনো (cached)"""
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
    """step থেকে দশমিকের সংখ্যা বের করো"""
    s = f"{step:.10f}".rstrip("0")
    if "." in s:
        return len(s.split(".")[1])
    return 0


def round_step(value, step):
    """value-কে step-এর নিকটতম গুণিতকে round করো"""
    if step <= 0:
        return value
    d = decimals_from_step(step)
    return round(round(value / step) * step, d)


def format_qty(qty, step):
    """qty-কে string-এ রূপান্তর, step-এর precision মেনে"""
    d = decimals_from_step(step)
    return f"{round_step(qty, step):.{d}f}"


def format_price(price, tick):
    """price-কে tick-এর গুণিতকে round করে string"""
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


def extract_json(text):
    if not text:
        raise ValueError("empty")
    text = text.strip()
    if "```" in text:
        for p in text.split("```"):
            p = p.replace("json", "").strip()
            if p.startswith("{"):
                text = p
                break
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i+1])
                    except Exception:
                        break
    raise ValueError(f"no json: {text[:60]}")


def get_ai_signal(symbol, data):
    prompt = f"""You are a professional crypto intraday trader.
Analyze this 15-minute data and give ONE trading signal.

Symbol: {symbol}
Price: {data['price']}
24h Change: {data['change_24h']}%
Funding Rate: {data['funding_rate']}%
RSI (15m): {data['rsi_15m']}

Rules:
- Confidence below 60 -> bias must be "neutral"
- RSI > 70 -> consider short
- RSI < 30 -> consider long

Output a single JSON object on ONE line. No markdown.
Format: {{"bias": "long", "confidence": 72, "reason": "short text"}}
"""
    for model in MODELS:
        for attempt in range(2):
            try:
                r = groq_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Reply ONLY with single-line JSON object."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=200,
                )
                return extract_json(r.choices[0].message.content)
            except Exception:
                continue
    return {"bias": "neutral", "confidence": 0, "reason": "ai unavailable"}


def calculate_position(symbol, signal, balance):
    """Position হিসাব + symbol-এর step মেনে round"""
    bias = signal.get("bias")
    confidence = signal.get("confidence", 0)
    entry = signal.get("price")

    if bias not in ("long", "short") or confidence < MIN_CONFIDENCE or not entry:
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

    # দাম tickSize মেনে round করো
    sl = round_step(sl, info["tickSize"])
    tp = round_step(tp, info["tickSize"])

    risk_usd = balance * (RISK_PER_TRADE_PCT / 100)
    price_risk = abs(entry - sl)
    if price_risk <= 0:
        return None

    # qty হিসাব + qtyStep মেনে round
    raw_qty = risk_usd / price_risk
    qty = round_step(raw_qty, info["qtyStep"])

    # minOrderQty চেক
    if qty < info["minOrderQty"]:
        qty = info["minOrderQty"]
        log(f"{symbol}: qty raised to minOrderQty {info['minOrderQty']}")

    notional = qty * entry

    # minNotionalValue চেক
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


def run_once():
    log("=" * 50)
    log("Cycle started")

    state = load_state()
    balance = get_balance()
    if balance is None:
        log("balance fetch failed, skip cycle")
        return

    if state["start_balance"] is None:
        state["start_balance"] = balance
        save_state(state)

    daily_pnl_pct = ((balance - state["start_balance"]) / state["start_balance"]) * 100
    log(f"Balance: ${balance:.2f} | Daily PnL: {daily_pnl_pct:+.2f}%")

    if daily_pnl_pct <= -DAILY_LOSS_LIMIT_PCT:
        log(f"Daily loss limit hit ({daily_pnl_pct:.2f}%), skip")
        return

    positions = get_open_positions()
    log(f"Open positions: {len(positions)} -> {list(positions.keys())}")

    if len(positions) >= MAX_OPEN_POSITIONS:
        log("Max positions reached, skip new trades")
        return

    for symbol in COINS:
        if symbol in positions:
            log(f"{symbol}: already have position, skip")
            continue

        data = get_market_data(symbol)
        if not data:
            log(f"{symbol}: no data")
            continue

        signal = get_ai_signal(symbol, data)
        signal["price"] = data["price"]
        bias = signal.get("bias", "?")
        conf = signal.get("confidence", 0)
        log(f"{symbol}: {bias} ({conf}%) - {signal.get('reason', '')[:50]}")

        trade = calculate_position(symbol, signal, balance)
        if not trade:
            continue

        set_leverage(symbol)
        time.sleep(0.3)

        res = place_order(trade)
        if res["ok"]:
            log(f"{symbol}: ORDER PLACED {res['order_id']} | qty={trade['qty_str']} (step={trade['qtyStep']}) entry=${trade['entry']} SL=${trade['sl']} TP=${trade['tp']} notional=${trade['notional']}")
            state["trades_today"] += 1
            save_state(state)
            if len(positions) + state["trades_today"] >= MAX_OPEN_POSITIONS:
                break
        else:
            log(f"{symbol}: order failed - {res['error']}")
        time.sleep(0.5)

    log("Cycle ended")


def main():
    log("=" * 50)
    log("BOT STARTED")
    log(f"Coins: {COINS}")
    log(f"Risk/trade: {RISK_PER_TRADE_PCT}% | Max positions: {MAX_OPEN_POSITIONS}")
    log(f"Loop interval: {LOOP_INTERVAL_SEC}s")

    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            log("Stopped by user")
            break
        except Exception as e:
            log(f"Cycle error: {str(e)[:100]}")
        log(f"Sleeping {LOOP_INTERVAL_SEC}s...")
        time.sleep(LOOP_INTERVAL_SEC)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        run_once()
    else:
        main()
