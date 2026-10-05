import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

API = f"https://api.telegram.org/bot{TOKEN}"


def send_message(text, parse_mode="Markdown"):
    if not TOKEN or not CHAT_ID:
        print(f"[telegram disabled] {text[:80]}")
        return False
    try:
        r = requests.post(
            f"{API}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if r.status_code != 200:
            print(f"telegram status {r.status_code}: {r.text[:80]}")
        return r.status_code == 200
    except Exception as e:
        print(f"telegram send error: {str(e)[:60]}")
        return False


def alert_trade_opened(symbol, bias, entry, sl, tp, qty, confidence):
    emoji = "🟢" if bias == "long" else "🔴"
    text = (
        f"{emoji} *NEW TRADE*\n\n"
        f"Symbol: `{symbol}`\n"
        f"Side: *{bias.upper()}*\n"
        f"Confidence: `{confidence}%`\n\n"
        f"Entry: `${entry}`\n"
        f"SL: `${sl}`\n"
        f"TP: `${tp}`\n"
        f"Qty: `{qty}`"
    )
    return send_message(text)


def alert_trade_closed(symbol, pnl, reason):
    emoji = "✅" if pnl >= 0 else "❌"
    text = (
        f"{emoji} *TRADE CLOSED*\n\n"
        f"Symbol: `{symbol}`\n"
        f"PnL: `{pnl:+.2f} USDT`\n"
        f"Reason: `{reason}`"
    )
    return send_message(text)


def alert_cycle_summary(signals, balance):
    lines = [f"🤖 *Cycle Summary*", ""]
    lines.append(f"Balance: `${balance:.2f}`")
    lines.append("")
    for sym, data in signals.items():
        c = data.get("consensus", {})
        lines.append(f"`{sym}`: {c.get('bias', '?')} ({c.get('confidence', 0)}%)")
    return send_message("\n".join(lines))


def alert_error(message):
    return send_message(f"⚠️ *ERROR*\n\n`{message[:300]}`")


if __name__ == "__main__":
    print("Testing Telegram...")
    ok = send_message(
        f"🤖 *AI Trading Bot*\n\nTelegram integration is working!\n\n"
        f"Time: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
    )
    if ok:
        print("✅ Message sent! Check Telegram.")
    else:
        print("❌ Failed. Check TOKEN and CHAT_ID in .env")




# ============ ENHANCED NOTIFICATIONS (FIXED) ============

def _fmt_price(p):
    try:
        p = float(p)
        if p >= 1000:
            return "${:,.2f}".format(p)
        elif p >= 1:
            return "${:.4f}".format(p)
        else:
            return "${:.6f}".format(p)
    except Exception:
        return str(p)


def alert_trade_opened(symbol, bias, entry, sl, tp, qty, confidence):
    try:
        entry = float(entry)
        sl = float(sl)
        risk_pct = abs(entry - sl) / entry * 100
        side_emoji = "\U0001F7E2" if bias == "long" else "\U0001F534"
        side_text = bias.upper()

        if bias == "long":
            tp1 = entry + (entry - sl) * 1.0
            tp2 = entry + (entry - sl) * 1.5
            tp3 = entry + (entry - sl) * 2.0
        else:
            tp1 = entry - (sl - entry) * 1.0
            tp2 = entry - (sl - entry) * 1.5
            tp3 = entry - (sl - entry) * 2.0

        try:
            notional = entry * float(qty)
        except Exception:
            notional = 0

        msg = (
            side_emoji + " TRADE OPENED - " + side_text + "\n\n"
            + "Symbol:  " + symbol + "\n"
            + "Entry:   " + _fmt_price(entry) + "\n"
            + "SL:      " + _fmt_price(sl) + "  (-" + "{:.2f}".format(risk_pct) + "%)\n"
            + "TP1:     " + _fmt_price(tp1) + "  (+" + "{:.2f}".format(risk_pct*1.0) + "%)  40%\n"
            + "TP2:     " + _fmt_price(tp2) + "  (+" + "{:.2f}".format(risk_pct*1.5) + "%)  30%\n"
            + "TP3:     " + _fmt_price(tp3) + "  (+" + "{:.2f}".format(risk_pct*2.0) + "%)  30%\n\n"
            + "Qty:     " + str(qty) + "\n"
            + "Notional: ~" + _fmt_price(notional) + "\n"
            + "Leverage: 3x Isolated\n"
            + "Risk:    2.0% of balance\n"
            + "AI Conf: " + str(confidence) + "%\n"
        )
        send_message(msg)
    except Exception as e:
        try:
            send_message("TRADE OPENED: " + symbol + " " + bias + " @ " + str(entry))
        except Exception:
            pass


def alert_cycle_summary(signals, balance):
    try:
        lines = []
        lines.append("AI CYCLE SUMMARY")
        lines.append("")
        lines.append("Balance: $" + "{:.2f}".format(balance))
        lines.append("")
        for sym, d in signals.items():
            groq_s = d.get("groq") or {}
            gem_s = d.get("gemini") or {}
            cons = d.get("consensus") or {}
            g_b = (groq_s.get("bias") or "-")[:1].upper()
            gm_b = (gem_s.get("bias") or "-")[:1].upper()
            c_b = (cons.get("bias") or "-").upper()
            c_c = cons.get("confidence", 0)
            rsi = d.get("rsi_15m", "-")
            try:
                chg = float(d.get("change_24h", 0))
                chg_s = "{:+.2f}".format(chg)
            except Exception:
                chg_s = "?"
            if c_b == "LONG":
                emoji = "\U0001F7E2"
            elif c_b == "SHORT":
                emoji = "\U0001F534"
            else:
                emoji = "\u26AA"
            lines.append(
                emoji + " " + sym + ": " + c_b + " " + str(c_c) + "% "
                + "[G=" + g_b + " Gm=" + gm_b + "] "
                + "RSI=" + str(rsi) + " 24h=" + chg_s + "%"
            )
        send_message("\n".join(lines))
    except Exception as e:
        try:
            send_message("Cycle summary error: " + str(e)[:80])
        except Exception:
            pass

