import os
import time
import json
import urllib.request
from datetime import datetime
from flask import Flask, jsonify
from telegram import Bot
from telegram.ext import Application, CommandHandler

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PORT = int(os.environ.get("PORT", 10000))
DATA_FILE = "/tmp/airdrop_data.json"

app = Flask(__name__)

if TELEGRAM_BOT_TOKEN:
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
else:
    bot = None

state = {
    "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "scan_count": 0,
    "last_scan": None,
    "total_found": 0
}

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

def send_tg(msg):
    if bot and TELEGRAM_CHAT_ID:
        try:
            bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
        except Exception as e:
            print(f"TG发送失败: {e}")
            @app.route("/")
def home():
    return jsonify(state)

async def start(update, context):
    await update.message.reply_text("运行中，一切正常。")

def run_bot():
    if bot:
        app_bot = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        app_bot.add_handler(CommandHandler("start", start))
        app_bot.run_polling()

if __name__ == "__main__":
    if bot:
        import threading
        threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)