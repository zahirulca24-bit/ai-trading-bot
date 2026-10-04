import os
from dotenv import load_dotenv
from pybit.unified_trading import HTTP

load_dotenv()

api_key = os.getenv("BYBIT_API_KEY")
api_secret = os.getenv("BYBIT_API_SECRET")

if not api_key or not api_secret:
    print("❌ BYBIT_API_KEY / BYBIT_API_SECRET .env-এ নেই!")
    exit(1)

print(f"✅ Bybit Key loaded: {api_key[:8]}...")

# Demo টেস্টনেট ব্যবহার করছি
session = HTTP(
    testnet=False,
    demo=True,              # এটাই Demo
    api_key=api_key,
    api_secret=api_secret,
)

# ধাপ ১: Wallet Balance চেক
print("\n🔄 Wallet Balance আনছি...")
try:
    wallet = session.get_wallet_balance(
        accountType="UNIFIED",
    )
    if wallet["retCode"] != 0:
        print(f"❌ Bybit Error: {wallet['retMsg']}")
        exit(1)

    coins = wallet["result"]["list"][0]["coin"]
    print("\n💰 Wallet Coins:")
    for c in coins:
        eq = c.get("walletBalance", "0")
        if float(eq) > 0:
            print(f"  {c['coin']}: {eq}")

    usdt = next((c for c in coins if c["coin"] == "USDT"), None)
    if usdt:
        print(f"\n🎯 USDT Balance: ${usdt['walletBalance']}")
    else:
        print("\n⚠️  USDT ব্যালেন্স পাওয়া যায়নি")

    print("\n✅ ফেজ ২ সফল!")

except Exception as e:
    print(f"❌ Error: {e}")
