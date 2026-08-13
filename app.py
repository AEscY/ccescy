import os
import time
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes

# ======================== 配置区 ========================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
THRESHOLD_SCORE = int(os.environ.get("THRESHOLD_SCORE", "30"))
SCAN_INTERVAL_MINUTES = int(os.environ.get("SCAN_INTERVAL_MINUTES", "30"))
PORT = int(os.environ.get("PORT", 10000))

DATA_FILE = "/tmp/airdrop_data.json"

app = Flask(__name__)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# ======================== 状态变量 ========================
system_state = {
    "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "scan_count": 0,
    "last_scan": None,
    "last_push": None,
    "projects_found": 0,
    "running": False,
}

known_projects = set()


# ======================== 数据持久化 ========================
def load_known_projects():
    global known_projects
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                known_projects = set(json.load(f))
        except Exception:
            known_projects = set()


def save_known_projects():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(list(known_projects), f)


# ======================== DefiLlama API ========================
def fetch_defillama_protocols():
    url = "https://api.llama.fi/protocols"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"API请求失败: {e}")
        return []


# ======================== 评分系统 ========================
def score_protocol(protocol):
    score = 0
    details = []

    name = protocol.get("name", "Unknown")
    tvl = protocol.get("tvl", 0)
    chain = protocol.get("chain", "")
    category = protocol.get("category", "")

    is_tokenlisted = protocol.get("token") or protocol.get("tokenSymbol")
    if is_tokenlisted:
        return -1, "已有代币"

    if tvl > 100_000_000:
        score += 30
        details.append(f"TVL超$1亿 (+30)")
    elif tvl > 10_000_000:
        score += 20
        details.append(f"TVL超$1000万 (+20)")
    elif tvl > 1_000_000:
        score += 10
        details.append(f"TVL超$100万 (+10)")
    elif tvl > 100_000:
        score += 5
        details.append(f"TVL超$10万 (+5)")

    chains = protocol.get("chains", [])
    if len(chains) >= 3:
        score += 10
        details.append(f"多链部署×{len(chains)} (+10)")
    elif len(chains) >= 2:
        score += 5
        details.append(f"双链部署 (+5)")

    if category in ["Dexs", "Lending", "Bridge", "Liquid Staking"]:
        score += 15
        details.append(f"热门赛道 {category} (+15)")
    elif category in ["Yield", "Derivatives", "NFT Marketplace"]:
        score += 10
        details.append(f"潜力赛道 {category} (+10)")

   cmcId = protocol.get("cmcId", "")
    if cmcId:
        score += 10
        details.append(f"已上CMC (cmcId:{cmcId}) (+10)")

    cgId = protocol.get("gecko_id", "")
    if cgId:
        score += 5
        details.append(f"已上CoinGecko (+5)")

    mcap = protocol.get("mcap", 0)
    if mcap and mcap > 100_000_000:
        score += 5
        details.append(f"市值超$1亿 (+5)")

    return score, details


# ======================== 推送消息 ========================
async def push_to_telegram(project_info):
    if not TELEGRAM_CHAT_ID:
        print("未配置CHAT_ID，跳过推送")
        return

    msg = (
        "🚨 <b>新空投机会发现</b>\n\n"
        f"📛 项目名称: {project_info['name']}\n"
        f"🔗 链: {project_info['chain']}\n"
        f"📂 赛道: {project_info['category']}\n"
        f"💰 TVL: ${project_info['tvl_formatted']}\n"
        f"⭐ 评分: <b>{project_info['score']}</b>\n\n"
        f"📊 评分详情:\n"
    )
    for d in project_info["details"]:
        msg += f"  • {d}\n"

    msg += f"\n🔗 DefiLlama: {project_info['url']}"

    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode="HTML"
        )
        print(f"✅ 已推送: {project_info['name']}")
    except Exception as e:
        print(f"推送失败: {e}")


# ======================== 主扫描逻辑 ========================
async def run_scan():
    system_state["scan_count"] += 1
    system_state["last_scan"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 第 {system_state['scan_count']} 次扫描...")

    protocols = fetch_defillama_protocols()
    if not protocols:
        print("未获取到数据")
        return

    new_projects = []

    for p in protocols:
        name = p.get("name", "")
        if not name:
            continue

        slug = p.get("slug", name)
        if slug in known_projects:
            continue

        score, details = score_protocol(p)

        if score >= THRESHOLD_SCORE:
            tvl_val = p.get("tvl", 0)
            if tvl_val >= 1_000_000_000:
                tvl_fmt = f"{tvl_val/1_000_000_000:.2f}B"
            elif tvl_val >= 1_000_000:
                tvl_fmt = f"{tvl_val/1_000_000:.2f}M"
            elif tvl_val >= 1_000:
                tvl_fmt = f"{tvl_val/1_000:.0f}K"
            else:
                tvl_fmt = f"{tvl_val:.0f}"

            project_info = {
                "slug": slug,
                "name": name,
                "chain": p.get("chains", ["Unknown"])[0] if p.get("chains") else "Unknown",
                "category": p.get("category", "Unknown"),
                "tvl_formatted": tvl_fmt,
                "score": score,
                "details": details,
                "url": f"https://defillama.com/protocol/{slug}",
            }
            new_projects.append(project_info)
            known_projects.add(slug)

    for proj in new_projects:
        await push_to_telegram(proj)

    if new_projects:
        system_state["last_push"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_state["projects_found"] += len(new_projects)
        save_known_projects()
        print(f"✅ 发现 {len(new_projects)} 个新项目并已推送")
    else:
        print("未发现符合条件的新项目")


# ======================== 定时任务 ========================
async def scan_loop():
    while True:
        await run_scan()
        await asyncio_sleep(SCAN_INTERVAL_MINUTES * 60)


async def asyncio_sleep(seconds):
    await __import__("asyncio").sleep(seconds)


def start_background_scan():
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    system_state["running"] = True
    loop.run_until_complete(scan_loop())


# ======================== Telegram 命令 ========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 <b>Airdrop Bot 已上线</b>\n\n"
        f"⏱ 每 <b>{SCAN_INTERVAL_MINUTES}</b> 分钟扫描一次\n"
        f"🎯 评分 ≥ <b>{THRESHOLD_SCORE}</b> 自动推送\n"
        f"📅 启动时间: {system_state['start_time']}\n\n"
        "输入 /menu 查看可用命令"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📋 <b>命令菜单</b>\n\n"
        "/status - 查看系统运行状态\n"
        "/scan - 手动触发一次扫描\n"
        "/projects - 查看已收录项目数\n"
        "/menu - 显示此菜单"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📊 <b>系统状态</b>\n\n"
        f"🟢 运行中: {'是' if system_state['running'] else '否'}\n"
        f"📅 启动时间: {system_state['start_time']}\n"
        f"🔄 已扫描: {system_state['scan_count']} 次\n"
        f"🕐 上次扫描: {system_state['last_scan'] or '暂无'}\n"
        f"📬 上次推送: {system_state['last_push'] or '暂无'}\n"
        f"📦 已收录: {len(known_projects)} 个项目\n"
        f"🎯 已推送: {system_state['projects_found']} 个项目\n"
        f"⏱ 扫描间隔: {SCAN_INTERVAL_MINUTES} 分钟\n"
        f"🎯 推送阈值: ≥{THRESHOLD_SCORE}分"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 正在扫描...", parse_mode="HTML")
    await run_scan()
    await update.message.reply_text("✅ 扫描完成", parse_mode="HTML")


async def cmd_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = f"📦 已收录项目总数: <b>{len(known_projects)}</b>"
    if known_projects:
        recent = list(known_projects)[-20:]
        msg += f"\n\n最近收录:\n"
        for slug in recent:
            msg += f"  • {slug}\n"
        if len(known_projects) > 20:
            msg += f"\n... 还有 {len(known_projects) - 20} 个"
    await update.message.reply_text(msg, parse_mode="HTML")


# ======================== Flask 路由 ========================
@app.route("/")
def index():
    return jsonify({
        "status": "alive",
        "bot": "Airdrop Bot",
        "start_time": system_state["start_time"],
        "scan_count": system_state["scan_count"],
        "last_scan": system_state["last_scan"],
        "projects_tracked": len(known_projects),
        "projects_pushed": system_state["projects_found"],
    })


@app.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200


# ======================== 启动 ========================
def main():
    load_known_projects()
    print(f"✅ 已加载 {len(known_projects)} 个已知项目")
    print(f"✅ 扫描间隔: {SCAN_INTERVAL_MINUTES} 分钟")
    print(f"✅ 推送阈值: ≥{THRESHOLD_SCORE} 分")

    app_builder = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app_builder.add_handler(CommandHandler("start", cmd_start))
    app_builder.add_handler(CommandHandler("menu", cmd_menu))
    app_builder.add_handler(CommandHandler("status", cmd_status))
    app_builder.add_handler(CommandHandler("scan", cmd_scan))
    app_builder.add_handler(CommandHandler("projects", cmd_projects))
    app_builder.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    import threading
    threading.Thread(target=start_background_scan, daemon=True).start()
    main()