import os
import time
import json
import urllib.request
from datetime import datetime
from flask import Flask, jsonify, request
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PORT = int(os.environ.get("PORT", 10000))
DATA_FILE = "/tmp/airdrop_data.json"

app = Flask(__name__)

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
    return {"seen_projects": [], "pushed_projects": []}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

def send_tg(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TG未配置，跳过推送")
        return
    try:
        b = Bot(token=TELEGRAM_BOT_TOKEN)
        b.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
    except Exception as e:
        print(f"TG发送失败: {e}")

def scan_airdrops():
    state["scan_count"] += 1
    state["last_scan"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        req = urllib.request.Request(
            "https://api.llama.fi/protocols",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            protocols = json.loads(resp.read().decode())
    except Exception as e:
        print(f"扫描失败: {e}")
        return

    data = load_data()
    seen = set(data.get("seen_projects", []))
    pushed = set(data.get("pushed_projects", []))
    new_items = []

    for p in protocols:
        name = p.get("name", "Unknown")
        if name in seen:
            continue
        seen.add(name)
        if p.get("token") or p.get("tokenSymbol"):
            continue
        tvl = p.get("tvl", 0) or 0
        score = 0
        if tvl > 1000000000:
            score += 30
        elif tvl > 100000000:
            score += 20
        elif tvl > 10000000:
            score += 10
        chains = p.get("chains", [])
        if len(chains) >= 3:
            score += 15
        elif len(chains) >= 1:
            score += 5
        if score >= 30 and name not in pushed:
            pushed.add(name)
            new_items.append((name, score, tvl))
            state["total_found"] += 1

    data["seen_projects"] = list(seen)
    data["pushed_projects"] = list(pushed)
    save_data(data)

    for name, score, tvl in new_items:
        msg = f"🔔 新空投机会\n项目: {name}\n评分: {score}\nTVL: ${tvl:,.0f}"
        send_tg(msg)

def scan_loop():
    while True:
        scan_airdrops()
        time.sleep(1800)

async def cmd_start(update, context):
    await update.message.reply_text(
        "🤖 Airdrop Bot 已启动\n"
        f"⏰ 每30分钟扫描\n"
        f"🎯 评分≥30自动推送\n"
        f"📅 启动: {state['start_time']}"
    )

async def cmd_status(update, context):
    data = load_data()
    msg = (
        "📊 运行状态\n"
        f"启动时间: {state['start_time']}\n"
        f"扫描次数: {state['scan_count']}\n"
        f"上次扫描: {state['last_scan'] or '暂无'}\n"
        f"累计发现: {state['total_found']}\n"
        f"已推送: {len(data.get('pushed_projects', []))}"
    )
    await update.message.reply_text(msg)

async def cmd_scan(update, context):
    await update.message.reply_text("🔄 正在扫描...")
    scan_airdrops()
    await update.message.reply_text("✅ 扫描完成")

async def cmd_reset(update, context):
    save_data({"seen_projects": [], "pushed_projects": []})
    state["scan_count"] = 0
    state["last_scan"] = None
    state["total_found"] = 0
    await update.message.reply_text("✅ 数据已重置")

async def cmd_help(update, context):
    await update.message.reply_text(
        "📋 命令列表:\n"
        "/start - 启动信息\n"
        "/status - 运行状态\n"
        "/scan - 手动扫描\n"
        "/reset - 重置数据\n"
        "/help - 帮助"
    )

@app.route("/")
def index():
    return jsonify({
        "status": "running",
        "scans": state["scan_count"],
        "found": state["total_found"]
    })

@app.route("/trigger", methods=["GET"])
def trigger():
    scan_airdrops()
    return jsonify({"status": "scanned"})

if __name__ == "__main__":
    import threading
    threading.Thread(target=scan_loop, daemon=True).start()

    if TELEGRAM_BOT_TOKEN:
        tg_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        tg_app.add_handler(CommandHandler("start", cmd_start))
        tg_app.add_handler(CommandHandler("status", cmd_status))
        tg_app.add_handler(CommandHandler("scan", cmd_scan))
        tg_app.add_handler(CommandHandler("reset", cmd_reset))
        tg_app.add_handler(CommandHandler("help", cmd_help))
        threading.Thread(
            target=tg_app.run_polling,
            kwargs={"drop_pending_updates": True},
            daemon=True
        ).start()

    app.run(host="0.0.0.0", port=PORT)