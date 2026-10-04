import os
from dotenv import load_dotenv
from pybit.unified_trading import HTTP

load_dotenv()

session = HTTP(
    testnet=False,
    demo=True,
    api_key=os.getenv("BYBIT_API_KEY"),
    api_secret=os.getenv("BYBIT_API_SECRET"),
)

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

def get_ticker(symbol):
    """২৪ ঘণ্টার মার্কেট ডেটা"""
    r = session.get_tickers(category="linear", symbol=symbol)
    if r["retCode"] != 0:
        return None
    return r["result"]["list"][0]

def get_rsi(symbol, interval="15", period=14):
    """RSI হিসাব করো ১৫ মিনিটের ক্যান্ডেল থেকে"""
    r = session.get_kline(
        category="linear",
        symbol=symbol,
        interval=interval,
        limit=period + 20,
    )
    if r["retCode"] != 0 or len(r["result"]["list"]) < period + 1:
        return None

    # Bybit উল্টো ক্রমে দেয় — নতুন আগে
    candles = list(reversed(r["result"]["list"]))
    closes = [float(c[4]) for c in candles]

    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

print("🔄 ৫ কয়েনের ডেটা আনছি...\n")

results = {}
for symbol in COINS:
    ticker = get_ticker(symbol)
    if not ticker:
        print(f"❌ {symbol}: ডেটা আসেনি")
        continue

    price = float(ticker["lastPrice"])
    change_24h = float(ticker["price24hPcnt"]) * 100
    volume = float(ticker["volume24h"])
    funding = float(ticker.get("fundingRate", 0)) * 100
    rsi = get_rsi(symbol)

    results[symbol] = {
        "price": price,
        "change_24h": round(change_24h, 2),
        "volume_24h": round(volume, 2),
        "funding_rate": round(funding, 4),
        "rsi_15m": rsi,
    }

    print(f"📊 {symbol}")
    print(f"   Price:         ${price}")
    print(f"   24h Change:    {change_24h:+.2f}%")
    print(f"   Funding Rate:  {funding:+.4f}%")
    print(f"   RSI (15m):     {rsi}")
    print()

print(f"✅ মোট {len(results)}টা কয়েনের ডেটা পাওয়া গেছে")
print("\n✅ ফেজ ৩ সফল!")