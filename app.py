import os
import time
import json
import urllib.request
from datetime import datetime
from flask import Flask
from telegram import Bot
from telegram.ext import Application, CommandHandler

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PORT = int(os.environ.get("PORT", 10000))

DATA_FILE = "/tmp/airdrop_data.json"
app = Flask(__name__)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

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
    return {"known_ids": []}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

def fetch_protocols():
    url = "https://api.llama.fi/protocols"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    response = urllib.request.urlopen(req, timeout=30)
    return json.loads(response.read().decode())

def calc_score(p):
    score = 0
    tvl = p.get("tvl", 0)
    if tvl > 10000000:
        score += 30
    elif tvl > 1000000:
        score += 20
    elif tvl > 100000:
        score += 10
    chains = p.get("chains", [])
    if len(chains) >= 3:
        score += 15
    elif len(chains) >= 1:
        score += 5
    name = p.get("name", "")
    category = p.get("category", "")
    if "defi" in category.lower() or "dex" in category.lower():
        score += 10
    if tvl > 0 and len(chains) > 0:
        score += 5
    return score

def build_message(p, score):
    name = p.get("name", "Unknown")
    tvl = p.get("tvl", 0)
    chains = p.get("chains", [])
    category = p.get("category", "Unknown")
    chain_str = ", ".join(chains[:5]) if chains else "None"
    tvl_str = f"${tvl:,.0f}" if tvl > 0 else "N/A"
    msg = f"\ud83d\udea8 *新空投信号*\n\n"
    msg += f"\ud83d\udccc 名称: {name}\n"
    msg += f"\ud83d\udcca TVL: {tvl_str}\n"
    msg += f"\ud83d\udd17 链: {chain_str}\n"
    msg += f"\ud83c\udff7 分类: {category}\n"
    msg += f"\u2b50 评分: {score}\n"
    msg += f"\n\ud83d\udc49 建议立即交互锁定资格！"
    return msg

async def send_to_telegram(msg):
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception as e:
        print(f"TG send error: {e}")

async def cmd_start(update, context):
    msg = "\ud83e\udd16 *Airdrop Bot 已启动*\n\n"
    msg += "\u23f1 扫描间隔: 30分钟\n"
    msg += f"\ud83c\udfaf 推送阈值: 评分\N{GREATER-THAN OR EQUAL TO}{THRESHOLD_SCORE}\n"
    msg += f"\ud83d\udce1 已启动: {state['start_time']}\n"
    msg += f"\ud83d\udd0d 扫描次数: {state['scan_count']}\n"
    msg += f"\u2705 发现项目: {state['total_found']}"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_status(update, context):
    msg = "\ud83d\udcca *系统状态*\n\n"
    msg += f"\u23f1 运行时间: {state['start_time']}\n"
    msg += f"\ud83d\udd0d 累计扫描: {state['scan_count']} 次\n"
    msg += f"\ud83d\udce2 推送项目: {state['total_found']} 个\n"
    last = state['last_scan'] or "尚未扫描"
    msg += f"\u23f0 最后扫描: {last}"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_scan(update, context):
    await update.message.reply_text("\ud83d\udd0d 正在手动扫描，请稍候...")
    await run_scan()
    await update.message.reply_text("\u2705 手动扫描完成")

async def cmd_help(update, context):
    msg = "\ud83d\udcda *可用命令*\n\n"
    msg += "/start - 启动信息\n"
    msg += "/status - 查看系统状态\n"
    msg += "/scan - 手动触发扫描\n"
    msg += "/help - 显示此帮助"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def run_scan():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始扫描...")
    state['scan_count'] += 1
    state['last_scan'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = load_data()
    known = set(data.get("known_ids", []))
    try:
        protocols = fetch_protocols()
    except Exception as e:
        print(f"Fetch error: {e}")
        return
    new_count = 0
    for p in protocols:
        name = p.get("name", "")
        pid = p.get("id", "")
        if not pid:
            continue
        token = p.get("token")
        if token is not None:
            continue
        score = calc_score(p)
        if score >= THRESHOLD_SCORE:
            if pid not in known:
                known.add(pid)
                msg = build_message(p, score)
                await send_to_telegram(msg)
                state['total_found'] += 1
                new_count += 1
                print(f"  \u27a4 新发现: {name} (评分{score})")
    data["known_ids"] = list(known)
    save_data(data)
    print(f"  \u2192 本轮新增: {new_count}, 已知: {len(known)}")

def scan_loop():
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        try:
            loop.run_until_complete(run_scan())
        except Exception as e:
            print(f"Scan error: {e}")
        time.sleep(SCAN_INTERVAL_MINUTES * 60)

@app.route("/")
def index():
    return jsonify({"status": "ok", "scans": state['scan_count'], "found": state['total_found']})

if __name__ == "__main__":
    import threading
    t = threading.Thread(target=scan_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=PORT)
