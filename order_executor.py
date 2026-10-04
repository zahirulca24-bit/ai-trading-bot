import os
import json
import time
from dotenv import load_dotenv
from pybit.unified_trading import HTTP

load_dotenv()

session = HTTP(
    testnet=False,
    demo=True,
    api_key=os.getenv("BYBIT_API_KEY"),
    api_secret=os.getenv("BYBIT_API_SECRET"),
)


def set_leverage(symbol, leverage=3):
    """লিভারেজ সেট করো"""
    try:
        r = session.set_leverage(
            category="linear",
            symbol=symbol,
            buyLeverage=str(leverage),
            sellLeverage=str(leverage),
        )
        # 110043 = already set, সমস্যা নয়
        if r["retCode"] in (0, 110043):
            print(f"   Leverage {leverage}x set for {symbol}")
            return True
        print(f"   Leverage fail: {r['retMsg']}")
        return False
    except Exception as e:
        print(f"   Leverage error: {str(e)[:60]}")
        return False


def place_order(symbol, side, qty, sl, tp, entry):
    """
    symbol: BTCUSDT
    side:   "Buy" (long) বা "Sell" (short)
    qty:    quantity
    sl:     stop loss price
    tp:     take profit price
    """
    try:
        r = session.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=str(qty),
            takeProfit=str(tp),
            stopLoss=str(sl),
            tpTriggerBy="LastPrice",
            slTriggerBy="LastPrice",
            timeInForce="IOC",
        )
        if r["retCode"] != 0:
            return {"ok": False, "error": r["retMsg"]}
        return {
            "ok": True,
            "order_id": r["result"]["orderId"],
            "symbol": symbol,
            "side": side,
            "qty": qty,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:80]}


def close_position(symbol):
    """পজিশন বন্ধ করো (মার্কেট অর্ডার দিয়ে)"""
    try:
        # পজিশন আছে কি না দেখো
        pos = session.get_positions(category="linear", symbol=symbol)
        if pos["retCode"] != 0:
            return False
        positions = pos["result"]["list"]
        if not positions or float(positions[0].get("size", 0)) == 0:
            return False

        side = "Sell" if positions[0]["side"] == "Buy" else "Buy"
        qty = positions[0]["size"]

        r = session.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=qty,
            reduceOnly=True,
            timeInForce="IOC",
        )
        return r["retCode"] == 0
    except Exception as e:
        print(f"   Close error: {str(e)[:60]}")
        return False


# ==========================================
# লাইভ ট্রেড এক্সিকিউশন
# ==========================================
def execute_trades(trades_file="trades.json", dry_run=False):
    """trades.json থেকে ট্রেড নিয়ে Bybit Demo-তে অর্ডার দাও"""
    try:
        with open(trades_file) as f:
            trades = json.load(f)
    except FileNotFoundError:
        print(f"{trades_file} নেই, আগে risk_manager.py চালান")
        return []

    if not trades:
        print("কোনো ট্রেড নেই (সব neutral ছিল)")
        return []

    results = []
    for t in trades:
        symbol = t["symbol"]
        side = "Buy" if t["bias"] == "long" else "Sell"

        print(f"\n{side} {symbol}")
        print(f"   Qty: {t['qty']} | Entry ~${t['entry']} | SL ${t['sl']} | TP ${t['tp']}")

        if dry_run:
            print(f"   [DRY RUN] অর্ডার পাঠানো হয়নি")
            results.append({"ok": True, "dry_run": True, "symbol": symbol})
            continue

        set_leverage(symbol, leverage=3)
        time.sleep(0.3)

        res = place_order(symbol, side, t["qty"], t["sl"], t["tp"], t["entry"])
        if res["ok"]:
            print(f"   Order placed: {res['order_id']}")
            t["order_id"] = res["order_id"]
            t["status"] = "placed"
        else:
            print(f"   Order failed: {res['error']}")
            t["status"] = "failed"
            t["error"] = res["error"]

        results.append(res)
        time.sleep(0.5)

    # আপডেট হওয়া trades সেভ করো
    with open(trades_file, "w") as f:
        json.dump(trades, f, indent=2)

    return results


# ==========================================
# টেস্ট মোড: ভুয়া সিগন্যাল দিয়ে কোড যাচাই
# ==========================================
def test_order():
    """ছোট একটা long অর্ডার দিয়ে সাথে সাথে বন্ধ করি"""
    symbol = "BTCUSDT"
    print(f"\n🧪 TEST: {symbol} ছোট long অর্ডার দেব, তারপর বন্ধ করব\n")

    # ১. লিভারেজ সেট
    set_leverage(symbol, leverage=3)
    time.sleep(1)

    # ২. বর্তমান দাম
    t = session.get_tickers(category="linear", symbol=symbol)
    if t["retCode"] != 0:
        print(f"   Price fetch failed: {t['retMsg']}")
        return
    price = float(t["result"]["list"][0]["lastPrice"])
    print(f"   Current price: ${price}")

    # ৩. ছোট qty (মিনিমাম $5 notional)
    qty = 0.001  # BTC-র জন্য মিনিমাম
    notional = qty * price
    print(f"   Qty: {qty} (notional ~${notional:.2f})")

    # ৪. SL/TP হিসাব
    sl = round(price * 0.99, 2)   # ১% নিচে
    tp = round(price * 1.02, 2)   # ২% উপরে
    print(f"   SL: ${sl} | TP: ${tp}")

    # ৫. অর্ডার দাও
    print(f"\n   🔄 Placing test long order...")
    res = place_order(symbol, "Buy", qty, sl, tp, price)
    print(f"   Result: {res}")

    if res["ok"]:
        order_id = res["order_id"]
        print(f"   ✅ Order placed: {order_id}")

        # ৬. ২ সেকেন্ড অপেক্ষা
        time.sleep(2)

        # ৭. পজিশন দেখো
        pos = session.get_positions(category="linear", symbol=symbol)
        if pos["retCode"] == 0 and pos["result"]["list"]:
            p = pos["result"]["list"][0]
            print(f"\n   Position:")
            print(f"      Size:  {p.get('size')}")
            print(f"      Side:  {p.get('side')}")
            print(f"      Entry: {p.get('avgPrice')}")
            print(f"      PnL:   {p.get('unrealisedPnl')}")

        # ৮. পজিশন বন্ধ করো
        print(f"\n   🔄 Closing test position...")
        if close_position(symbol):
            print(f"   ✅ Position closed")
        else:
            print(f"   ⚠️  Position not found or already closed")

        # ৯. খোলা অর্ডার বাতিল করো
        try:
            oo = session.get_open_orders(category="linear", symbol=symbol)
            if oo["retCode"] == 0 and oo["result"]["list"]:
                for o in oo["result"]["list"]:
                    session.cancel_order(
                        category="linear",
                        symbol=symbol,
                        orderId=o["orderId"],
                    )
                    print(f"   ✅ Cancelled leftover order {o['orderId']}")
        except Exception as e:
            print(f"   Cancel note: {str(e)[:50]}")

        print(f"\n✅ ফেজ ৬ সফল!")
    else:
        print(f"\n❌ Order failed: {res.get('error')}")


if __name__ == "__main__":
    print("=" * 50)
    print("ফেজ ৬: অর্ডার এক্সিকিউশন টেস্ট")
    print("=" * 50)

    # টেস্ট অর্ডার — ছোট, সাথে সাথে বন্ধ হবে
    test_order()
