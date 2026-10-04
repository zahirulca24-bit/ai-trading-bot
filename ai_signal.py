import os
import json
import re
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

# ✅ ঠিক করা মডেল ID
MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]


def get_market_data(symbol):
    t = session.get_tickers(category="linear", symbol=symbol)
    if t["retCode"] != 0:
        return None
    ticker = t["result"]["list"][0]

    k = session.get_kline(category="linear", symbol=symbol, interval="15", limit=30)
    candles = list(reversed(k["result"]["list"]))
    closes = [float(c[4]) for c in candles]

    period = 14
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    rsi = 100.0 if avg_loss == 0 else round(100 - (100 / (1 + avg_gain / avg_loss)), 2)

    return {
        "price": float(ticker["lastPrice"]),
        "change_24h": round(float(ticker["price24hPcnt"]) * 100, 2),
        "funding_rate": round(float(ticker.get("fundingRate", 0)) * 100, 4),
        "rsi_15m": rsi,
    }


def build_prompt(symbol, data):
    return f"""You are a professional crypto intraday trader.
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

Output must be a single JSON object on ONE LINE.
Do not add any text before or after.
Format: {{"bias": "long", "confidence": 72, "reason": "momentum up"}}
"""


def extract_json(text):
    """যেকোনো টেক্সট থেকে JSON বের করার আরও কড়া পদ্ধতি"""
    if not text:
        raise ValueError("Empty response")

    text = text.strip()

    # ১. markdown code block সরাও
    if "```" in text:
        for p in text.split("```"):
            p = p.replace("json", "").strip()
            if p.startswith("{"):
                text = p
                break

    # ২. সরাসরি parse চেষ্টা
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ৩. regex দিয়ে প্রথম {...} ধরো
    m = re.search(r"\{.*?\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # ৪. bracket count করে সঠিক JSON ব্লক বের করো
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i+1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"No valid JSON in: {text[:100]}")


def get_ai_signal(symbol, data):
    prompt = build_prompt(symbol, data)

    for model in MODELS:
        for attempt in range(3):  # ৩ বার চেষ্টা
            try:
                r = groq_client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You output only a single-line JSON object. No markdown. No explanation. No extra text.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=250,
                )
                raw = r.choices[0].message.content
                return extract_json(raw)
            except Exception as e:
                if attempt == 2:
                    print(f"   ⚠️ {model} failed: {str(e)[:60]}")

    return {"bias": "neutral", "confidence": 0, "reason": "ai unavailable"}


print("🔄 ৫ কয়েনে AI সিগন্যাল তৈরি করছি...\n")

all_signals = {}

for symbol in COINS:
    data = get_market_data(symbol)
    if not data:
        print(f"❌ {symbol}: ডেটা আসেনি")
        continue

    signal = get_ai_signal(symbol, data)
    all_signals[symbol] = {**data, **signal}

    emoji = {"long": "🟢", "short": "🔴", "neutral": "⚪"}.get(signal.get("bias"), "❓")

    print(f"{emoji} {symbol}")
    print(f"   Price:      ${data['price']}")
    print(f"   RSI (15m):  {data['rsi_15m']}")
    print(f"   Bias:       {str(signal.get('bias')).upper()}")
    print(f"   Confidence: {signal.get('confidence')}%")
    print(f"   Reason:     {signal.get('reason')}")
    print()

with open("signals.json", "w") as f:
    json.dump(all_signals, f, indent=2)

print(f"✅ {len(all_signals)}টা সিগন্যাল তৈরি, signals.json-এ সেভ হয়েছে")
print("\n✅ ফেজ ৪ সফল!")
