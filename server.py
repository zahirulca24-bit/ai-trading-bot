import os
import threading
import time
import datetime
from flask import Flask, jsonify

from main import run_once, get_balance, get_open_positions, log

app = Flask(__name__)

BOT_THREAD = None
BOT_RUNNING = False
LAST_CYCLE = None
LOOP_INTERVAL = 900  # 15 মিনিট


def bot_loop():
    global BOT_RUNNING, LAST_CYCLE
    BOT_RUNNING = True
    log("Background bot thread started")

    while True:
        try:
            run_once()
            LAST_CYCLE = datetime.datetime.now().isoformat()
        except Exception as e:
            log(f"bot_loop error: {str(e)[:120]}")
        log(f"Sleeping {LOOP_INTERVAL}s...")
        time.sleep(LOOP_INTERVAL)


def start_bot():
    global BOT_THREAD
    if BOT_THREAD is None or not BOT_THREAD.is_alive():
        BOT_THREAD = threading.Thread(target=bot_loop, daemon=True)
        BOT_THREAD.start()
        log("Bot thread created")


@app.route("/")
def root():
    return jsonify({
        "service": "ai-trading-bot",
        "status": "running" if BOT_RUNNING else "starting",
        "last_cycle": LAST_CYCLE,
        "time": datetime.datetime.now().isoformat(),
    })


@app.route("/healthz")
def healthz():
    return "OK", 200


@app.route("/status")
def status():
    try:
        balance = get_balance()
        positions = get_open_positions()
        return jsonify({
            "ok": True,
            "balance_usdt": balance,
            "open_positions": list(positions.keys()),
            "positions_count": len(positions),
            "bot_running": BOT_RUNNING,
            "last_cycle": LAST_CYCLE,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:100]}), 500


@app.route("/trigger")
def trigger():
    """ম্যানুয়ালি একটা সাইকেল চালাও (টেস্টের জন্য)"""
    try:
        threading.Thread(target=run_once, daemon=True).start()
        return jsonify({"ok": True, "message": "cycle triggered"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:100]}), 500


if __name__ == "__main__":
    start_bot()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
else:
    # Render-এ gunicorn দিয়ে চালালেও bot thread শুরু হবে
    start_bot()
