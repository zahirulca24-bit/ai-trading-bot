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
