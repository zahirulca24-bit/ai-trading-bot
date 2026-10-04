from main import get_balance, get_market_data, calculate_position, set_leverage, place_order, log
import time

print("=" * 50)
print("FORCED TRADE TEST")
print("=" * 50)

balance = get_balance()
print(f"Balance: ${balance}")

# SOL-এর রিয়েল দাম আনো
data = get_market_data("SOLUSDT")
if not data:
    print("SOL data unavailable")
    exit(1)

print(f"SOL current price: ${data['price']}")

# জোর করে একটা long সিগন্যাল
forced = {
    "bias": "long",
    "confidence": 80,
    "price": data["price"],
}

trade = calculate_position("SOLUSDT", forced, balance)
if not trade:
    print("Trade calculation failed")
    exit(1)

print(f"\nCalculated:")
print(f"   Symbol: {trade['symbol']}")
print(f"   Bias:   {trade['bias']}")
print(f"   Entry:  ${trade['entry']}")
print(f"   SL:     ${trade['sl']}")
print(f"   TP:     ${trade['tp']}")
print(f"   Qty:    {trade['qty_str']} (step={trade['qtyStep']})")
print(f"   Notional: ${trade['notional']}")

print(f"\nPlacing order...")
set_leverage("SOLUSDT")
time.sleep(0.5)

res = place_order(trade)
print(f"Result: {res}")

if res["ok"]:
    print(f"\n✅ ORDER PLACED: {res['order_id']}")
    print("\nBybit Demo-তে চেক করুন: Positions ট্যাব")
else:
    print(f"\n❌ Failed: {res['error']}")
