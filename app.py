import os
import time
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

# ======================== 配置区 ========================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
THRESHOLD_SCORE = int(os.environ.get("THRESHOLD_SCORE", "30"))
SCAN_INTERVAL_MINUTES = int(os.environ.get("SCAN_INTERVAL_MINUTES", "30"))
PORT = int(os.environ.get("PORT", 10000))

# 数据存储文件（Render临时磁盘，每次重启会丢失，重启后重新扫描）
DATA_FILE = "/tmp/airdrop_data.json"

app = Flask(__name__)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# ======================== 状态变量 ========================
system_state = {
    "start_time": datetime.now().isoformat(),
    "scan_count": 0,
    "last_scan_time": None,
    "last_push_count": 0,
    "tracked_projects": {},  # protocol_id -> {info, score, pushed_at}
}

# ======================== 数据持久化 ========================
def save_state():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(system_state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[保存状态失败] {e}")

def load_state():
    global system_state
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                system_state.update(loaded)
    except Exception as e:
        print(f"[加载状态失败] {e}")

# ======================== 数据抓取 ========================
def fetch_defillama_protocols():
    """抓取DefiLlama所有协议数据"""
    url = "https://api.llama.fi/protocols"
    req = urllib.request.Request(url, headers={"User-Agent": "AirdropBot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data
    except Exception as e:
        print(f"[抓取失败] {e}")
        return []

def fetch_defillama_tvl(protocol_slug):
    """抓取单个协议的TVL历史数据"""
    url = f"https://api.llama.fi/tvl/{protocol_slug}"
    req = urllib.request.Request(url, headers={"User-Agent": "AirdropBot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data  # list of [timestamp, tvl]
    except Exception:
        return []

def calculate_score(protocol):
    """对项目进行多维度评分"""
    score = 0
    details = []

    # 1. TVL维度
    tvl = protocol.get("tvl", 0)
    if tvl > 100_000_000:
        score += 25
        details.append("TVL>$1亿 (+25)")
    elif tvl > 50_000_000:
        score += 20
        details.append("TVL>$5000万 (+20)")
    elif tvl > 10_000_000:
        score += 15
        details.append("TVL>$1000万 (+15)")
    elif tvl > 1_000_000:
        score += 10
        details.append("TVL>$100万 (+10)")

    # 2. 链上生态维度
    chains = protocol.get("chains", [])
    if len(chains) >= 5:
        score += 15
        details.append(f"多链部署({len(chains)}条) (+15)")
    elif len(chains) >= 2:
        score += 10
        details.append(f"多链部署({len(chains)}条) (+10)")

    # 3. 分类维度（DeFi核心协议加分）
    category = protocol.get("category", "").lower()
    if category in ["dexes", "lending", "yield", "derivatives", "bridge"]:
        score += 15
        details.append(f"核心DeFi赛道:{category} (+15)")
    elif category in ["yield aggregator", "options", "insurance"]:
        score += 10
        details.append(f"DeFi赛道:{category} (+10)")

    # 4. 名称/描述关键词（判断是否有代币）
    name = protocol.get("name", "").lower()
    description = str(protocol.get("description", "")).lower()
    token_mentions = ["token", "governance", "airdrop", "$", "tokenomics"]
    has_token_hint = any(kw in name or kw in description for kw in token_mentions)
    if not has_token_hint:
        score += 10
        details.append("无明显代币信息 (+10)")

    # 5. 社区/社交链接（有GitHub/Twitter说明项目活跃）
    if protocol.get("twitter"):
        score += 5
        details.append("有Twitter (+5)")
    if protocol.get("github"):
        score += 5
        details.append("有GitHub (+5)")
    if protocol.get("url"):
        score += 5
        details.append("有官网 (+5)")

    # 6. TVL趋势（最近7天增长加分）
    slug = protocol.get("slug", "")
    if slug:
        tvl_history = fetch_defillama_tvl(slug)
        if len(tvl_history) >= 14:
            current_tvl = tvl_history[-1][1]
            tvl_7d_ago = tvl_history[-7][1] if len(tvl_history) >= 7 else tvl_history[0][1]
            if tvl_7d_ago > 0:
                growth = (current_tvl - tvl_7d_ago) / tvl_7d_ago
                if growth > 0.5:
                    score += 20
                    details.append(f"7天TVL增长{growth*100:.0f}% (+20)")
                elif growth > 0.2:
                    score += 10
                    details.append(f"7天TVL增长{growth*100:.0f}% (+10)")
                elif growth < -0.2:
                    score -= 10
                    details.append(f"7天TVL下降{abs(growth)*100:.0f}% (-10)")

    return score, details

def format_project_message(protocol, score, details):
    """格式化项目推送消息"""
    name = protocol.get("name", "Unknown")
    category = protocol.get("category", "Unknown")
    tvl = protocol.get("tvl", 0)
    chains = protocol.get("chains", [])
    slug = protocol.get("slug", "")

    tvl_str = f"${tvl/1_000_000_000:.2f}B" if tvl >= 1_000_000_000 else f"${tvl/1_000_000:.0f}M"
    chains_str = ", ".join(chains[:5]) + (f" 等{len(chains)}条链" if len(chains) > 5 else "")
    twitter = f"https://twitter.com/{protocol.get('twitter')}" if protocol.get("twitter") else "无"
    website = protocol.get("url", "无")
    defillama_link = f"https://defillama.com/protocol/{slug}" if slug else "无"

    detail_str = "\n".join([f"  • {d}" for d in details])

    msg = (
        f"🚨 <b>新空投信号发现</b>\n\n"
        f"📌 <b>项目名称</b>：{name}\n"
        f"🏷️ <b>赛道分类</b>：{category}\n"
        f"💰 <b>TVL</b>：{tvl_str}\n"
        f"⛓️ <b>部署链</b>：{chains_str}\n"
        f"⭐ <b>综合评分</b>：<b>{score}</b> 分\n\n"
        f"📊 <b>评分明细</b>：\n{detail_str}\n\n"
        f"🔗 <b>相关链接</b>：\n"
        f"  • 官网：{website}\n"
        f"  • Twitter：{twitter}\n"
        f"  • DefiLlama：{defillama_link}"
    )
    return msg

# ======================== 核心扫描逻辑 ========================
async def run_scan():
    """执行一次完整扫描"""
    system_state["scan_count"] += 1
    system_state["last_scan_time"] = datetime.now().isoformat()
    save_state()

    protocols = fetch_defillama_protocols()
    if not protocols:
        return

    tracked = system_state.get("tracked_projects", {})
    pushed_count = 0

    for proto in protocols:
        pid = proto.get("id")
        if not pid:
            continue

        # 只处理无代币协议（DefiLlama上tvl>0且无明确代币标识）
        if proto.get("tvl", 0) == 0:
            continue

        score, details = calculate_score(proto)

        if score >= THRESHOLD_SCORE:
            if pid not in tracked:
                # 新项目，推送
                msg = format_project_message(proto, score, details)
                try:
                    await bot.send_message(
                        chat_id=TELEGRAM_CHAT_ID,
                        text=msg,
                        parse_mode="HTML"
                    )
                    tracked[pid] = {
                        "name": proto.get("name"),
                        "score": score,
                        "pushed_at": datetime.now().isoformat(),
                        "tvl": proto.get("tvl"),
                    }
                    pushed_count += 1
                except Exception as e:
                    print(f"[推送失败] {proto.get('name')}: {e}")
            else:
                # 已推送过的项目，检查分数变化
                old_score = tracked[pid].get("score", 0)
                if score > old_score + 10:
                    # 分数显著提升，重新推送
                    msg = (
                        f"📈 <b>项目评分显著提升</b>\n\n"
                        f"📌 {proto.get('name')} 评分 {old_score}→<b>{score}</b>\n"
                        f"💰 TVL: ${proto.get('tvl',0)/1_000_000:.0f}M\n"
                        f"📊 变化：{'、'.join(details[:3])}"
                    )
                    try:
                        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="HTML")
                        tracked[pid]["score"] = score
                        tracked[pid]["pushed_at"] = datetime.now().isoformat()
                        pushed_count += 1
                    except Exception as e:
                        print(f"[推送失败] {e}")
                tracked[pid]["score"] = score

    system_state["tracked_projects"] = tracked
    system_state["last_push_count"] = pushed_count
    save_state()

    if pushed_count > 0:
        print(f"[扫描完成] 推送了 {pushed_count} 个项目")
    else:
        print(f"[扫描完成] 无新项目，已追踪 {len(tracked)} 个项目")

# ======================== 定时任务 ========================
import asyncio

def start_background_scheduler():
    """启动后台定时扫描任务"""
    async def scheduler_loop():
        while True:
            try:
                await run_scan()
            except Exception as e:
                print(f"[定时任务异常] {e}")
            await asyncio.sleep(SCAN_INTERVAL_MINUTES * 60)

    asyncio.create_task(scheduler_loop())

# ======================== Telegram 命令 ========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 <b>Airdrop Bot 已就绪</b>\n\n"
        "欢迎使用私有空投情报系统。\n"
        "当前配置：\n"
        f"• 扫描频率：每 {SCAN_INTERVAL_MINUTES} 分钟\n"
        f"• 推送阈值：评分 ≥ {THRESHOLD_SCORE}\n\n"
        "输入 /menu 查看可用命令"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📋 <b>命令菜单</b>\n\n"
        "/start — 欢迎信息\n"
        "/status — 系统运行状态\n"
        "/scan — 手动触发一次扫描\n"
        "/projects — 查看已追踪的项目\n"
        "/threshold — 查看/修改推送阈值\n"
        "/help — 帮助说明"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = datetime.fromisoformat(system_state["start_time"])
    uptime = datetime.now() - start_time
    hours = int(uptime.total_seconds() // 3600)
    mins = int((uptime.total_seconds() % 3600) // 60)

    last_scan = system_state.get("last_scan_time")
    if last_scan:
        last_scan_str = datetime.fromisoformat(last_scan).strftime("%Y-%m-%d %H:%M:%S")
    else:
        last_scan_str = "尚未执行"

    msg = (
        "📊 <b>系统状态</b>\n\n"
        f"⏱ 运行时长：{hours}小时{mins}分钟\n"
        f"🔄 扫描次数：{system_state['scan_count']} 次\n"
        f"🕐 上次扫描：{last_scan_str}\n"
        f"📦 追踪项目：{len(system_state.get('tracked_projects', {}))} 个\n"
        f"📨 上次推送：{system_state.get('last_push_count', 0)} 条\n"
        f"⚙️ 扫描间隔：{SCAN_INTERVAL_MINUTES} 分钟\n"
        f"🎯 推送阈值：≥{THRESHOLD_SCORE} 分"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 正在手动触发扫描，请稍候...")
    try:
        await run_scan()
        pushed = system_state.get("last_push_count", 0)
        tracked = len(system_state.get("tracked_projects", {}))
        await update.message.reply_text(
            f"✅ 扫描完成\n"
            f"• 本次推送：{pushed} 条\n"
            f"• 已追踪项目：{tracked} 个",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 扫描失败：{str(e)}")

async def cmd_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tracked = system_state.get("tracked_projects", {})
    if not tracked:
        await update.message.reply_text("📭 暂无已追踪的项目，等待扫描中...")
        return

    # 按pushed_at排序，最新的在前
    sorted_projects = sorted(
        tracked.items(),
        key=lambda x: x[1].get("pushed_at", ""),
        reverse=True
    )

    lines = []
    for i, (pid, info) in enumerate(sorted_projects[:20], 1):
        pushed_at = info.get("pushed_at", "")
        if pushed_at:
            pushed_str = datetime.fromisoformat(pushed_at).strftime("%m-%d %H:%M")
        else:
            pushed_str = "未知"
        tvl_m = info.get("tvl", 0) / 1_000_000
        lines.append(
            f"{i}. <b>{info.get('name', 'Unknown')}</b> "
            f"| 评分{info.get('score', '?')} "
            f"| TVL${tvl_m:.0f}M "
            f"| {pushed_str}"
        )

    total = len(sorted_projects)
    showing = min(total, 20)
    msg = (
        f"📦 <b>已追踪项目</b>（共{total}个，显示最新{showing}个）\n\n"
        + "\n".join(lines)
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def cmd_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args:
        try:
            new_threshold = int(args[0])
            global THRESHOLD_SCORE
            THRESHOLD_SCORE = new_threshold
            os.environ["THRESHOLD_SCORE"] = str(new_threshold)
            save_state()
            msg = f"✅ 推送阈值已更新为 ≥ <b>{new_threshold}</b> 分"
        except ValueError:
            msg = "❌ 请输入有效的数字，例如：/threshold 30"
    else:
        msg = f"🎯 当前推送阈值：≥ <b>{THRESHOLD_SCORE}</b> 分\n\n修改方法：<code>/threshold 新数值</code>"
    await update.message.reply_text(msg, parse_mode="HTML")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💡 <b>帮助说明</b>\n\n"
        "本Bot自动监控DefiLlama上的无代币DeFi协议，\n"
        "从TVL、多链部署、赛道类型、TVL增速等维度评分，\n"
        "达到阈值后自动推送到此对话。\n\n"
        "<b>可用命令</b>：\n"
        "/menu — 命令菜单\n"
        "/status — 查看系统状态\n"
        "/scan — 手动扫描\n"
        "/projects — 已追踪项目\n"
        "/threshold [数值] — 调整推送阈值\n"
        "/help — 帮助"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

# ======================== Flask 路由 ========================
@app.route("/")
def health_check():
    tracked_count = len(system_state.get("tracked_projects", {}))
    return jsonify({
        "status": "alive",
        "service": "Airdrop Bot",
        "uptime_hours": (datetime.now() - datetime.fromisoformat(system_state["start_time"])).total_seconds() / 3600,
        "scan_count": system_state["scan_count"],
        "tracked_projects": tracked_count,
        "threshold": THRESHOLD_SCORE,
        "scan_interval_minutes": SCAN_INTERVAL_MINUTES,
    })

@app.route("/webhook", methods=["POST"])
async def telegram_webhook():
    """处理Telegram的webhook回调"""
    update_data = request.json
    update = Update.de_json(update_data, bot)
    application = context.application if hasattr(context, 'application') else None

    # 手动分发update
    for handler in command_handlers:
        check, _ = await handler.check_update(update)
        if check:
            await handler.handle_update(update, None)
            break

    return jsonify({"status": "ok"})

command_handlers = []

def build_app():
    """构建并返回Telegram Application"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 注册所有命令
    commands = [
        ("start", cmd_start),
        ("menu", cmd_menu),
        ("status", cmd_status),
        ("scan", cmd_scan),
        ("projects", cmd_projects),
        ("threshold", cmd_threshold),
        ("help", cmd_help),
    ]

    global command_handlers
    for cmd_name, handler_func in commands:
        handler_obj = CommandHandler(cmd_name, handler_func)
        application.add_handler(handler_obj)
        command_handlers.append(handler_obj)

    return application

# 全局application实例
telegram_app = None

@app.before_request
def init_telegram_app():
    global telegram_app
    if telegram_app is None:
        telegram_app = build_app()

# ======================== 启动入口 ========================
if __name__ == "__main__":
    load_state()

    # 启动后台定时扫描
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(start_background_scheduler())

    # 初始化Telegram bot（使用轮询方式，不需要webhook）
    telegram_app = build_app()
    loop.create_task(telegram_app.initialize())
    loop.create_task(telegram_app.start())

    print(f"[启动] Airdrop Bot 运行在端口 {PORT}")
    print(f"[配置] 扫描间隔: {SCAN_INTERVAL_MINUTES}分钟, 推送阈值: {THRESHOLD_SCORE}")

    # 启动Flask（在后台线程中运行）
    import threading
    flask_thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT, threaded=True),
        daemon=True
    )
    flask_thread.start()

    # 主线程运行Telegram轮询
    loop.run_until_complete(telegram_app.updater.start_polling())
    loop.run_forever()