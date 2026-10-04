import json
import math

ACCOUNT_BALANCE = 1000.0
RISK_PER_TRADE_PCT = 2.0
FEE_RATE = 0.00055
DAILY_LOSS_LIMIT_PCT = 10.0
MIN_CONFIDENCE = 60


def calculate_position(signal, balance, risk_pct=2.0):
    bias = signal.get("bias")
    confidence = signal.get("confidence", 0)
    entry = signal.get("price")

    if bias not in ("long", "short"):
        return {"skip": True, "reason": f"bias={bias}"}

    if confidence < MIN_CONFIDENCE:
        return {"skip": True, "reason": f"confidence {confidence} < {MIN_CONFIDENCE}"}

    if not entry:
        return {"skip": True, "reason": "no entry price"}

    if bias == "long":
        sl_pct = 0.008
        tp_pct = 0.016
        sl = entry * (1 - sl_pct)
        tp = entry * (1 + tp_pct)
    else:
        sl_pct = 0.008
        tp_pct = 0.016
        sl = entry * (1 + sl_pct)
        tp = entry * (1 - tp_pct)

    risk_usd = balance * (risk_pct / 100)
    price_risk = abs(entry - sl)
    qty = round(risk_usd / price_risk, 4)
    notional = qty * entry

    if notional < 5:
        return {"skip": True, "reason": f"notional ${notional:.2f} too small"}

    fee_cost = notional * FEE_RATE * 2
    potential_loss = qty * price_risk + fee_cost
    potential_profit = qty * abs(tp - entry) - fee_cost

    return {
        "skip": False,
        "symbol": signal.get("symbol", "?"),
        "bias": bias,
        "confidence": confidence,
        "entry": round(entry, 6),
        "sl": round(sl, 6),
        "tp": round(tp, 6),
        "qty": qty,
        "notional": round(notional, 2),
        "risk_usd": round(potential_loss, 2),
        "reward_usd": round(potential_profit, 2),
        "rr_ratio": round(potential_profit / potential_loss, 2) if potential_loss else 0,
        "sl_pct": round(sl_pct * 100, 3),
        "tp_pct": round(tp_pct * 100, 3),
    }


print("Risk Manager Test")
print(f"Account: ${ACCOUNT_BALANCE} | Risk: {RISK_PER_TRADE_PCT}% | Max daily loss: {DAILY_LOSS_LIMIT_PCT}%")
print()

try:
    with open("signals.json") as f:
        signals = json.load(f)
except FileNotFoundError:
    print("signals.json missing, run ai_signal.py first")
    exit(1)

trades = []
skipped = []

for symbol, sig in signals.items():
    sig["symbol"] = symbol
    result = calculate_position(sig, ACCOUNT_BALANCE, RISK_PER_TRADE_PCT)

    if result.get("skip"):
        skipped.append((symbol, result["reason"]))
        print(f"SKIP {symbol}: {result['reason']}")
    else:
        trades.append(result)
        print(f"{symbol}")
        print(f"   Bias:      {result['bias'].upper()} ({result['confidence']}%)")
        print(f"   Entry:     ${result['entry']}")
        print(f"   SL:        ${result['sl']} (-{result['sl_pct']}%)")
        print(f"   TP:        ${result['tp']} (+{result['tp_pct']}%)")
        print(f"   Qty:       {result['qty']}")
        print(f"   Notional:  ${result['notional']}")
        print(f"   Risk:      ${result['risk_usd']}")
        print(f"   Reward:    ${result['reward_usd']}")
        print(f"   R:R:       {result['rr_ratio']}")
        print()

print()
print("Summary:")
print(f"   Trade:  {len(trades)}")
print(f"   Skip:   {len(skipped)}")
print(f"   Total risk:   ${sum(t['risk_usd'] for t in trades):.2f}")
print(f"   Total reward: ${sum(t['reward_usd'] for t in trades):.2f}")

with open("trades.json", "w") as f:
    json.dump(trades, f, indent=2)

print()
print("trades.json saved")
print("Phase 5 OK")
