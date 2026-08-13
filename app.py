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

DATA_FILE = "/tmp/airdrop_data.json"

app = Flask(__name__)

# 全局状态
system_state = {
    "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "total_scans": 0,
    "total_pushes": 0,
    "last_scan_time": "从未",
    "last_scan_count": 0,
    "is_scanning": False,
}

# 内存中的项目数据（Render重启后重新扫描）
known_projects = {}
scan_history = []


def load_data():
    global known_projects
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                known_projects = json.load(f)
            print(f"[加载] 已恢复 {len(known_projects)} 个项目记录")
        except:
            known_projects = {}


def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(known_projects, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[保存失败] {e}")


def fetch_defillama_protocols():
    """从 DefiLlama 获取所有无代币协议"""
    url = "https://api.llama.fi/protocols"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw_data = json.loads(response.read().decode("utf-8"))
            # 筛选无代币协议
            tokenless = [p for p in raw_data if p.get("token") is None or str(p.get("token")).lower() == "false"]
            return tokenless
    except Exception as e:
        print(f"[抓取失败] {e}")
        return []


def calculate_score(protocol):
    """计算项目空投评分"""
    score = 0
    details = []

    name = protocol.get("name", "Unknown")
    tvl = float(protocol.get("tvl", 0))
    category = protocol.get("category", "")
    chains = protocol.get("chains", [])
    change_1d = float(protocol.get("chainTvls", {}).get("all", {}).get("1d", 0)) if isinstance(protocol.get("chainTvls"), dict) else 0
    change_7d = float(protocol.get("chainTvls", {}).get("all", {}).get("7d", 0)) if isinstance(protocol.get("chainTvls"), dict) else 0

    # TVL 评分
    if tvl > 1_000_000_000:
        score += 30
        details.append(f"TVL超$10亿 (+30)")
    elif tvl > 100_000_000:
        score += 20
        details.append(f"TVL超$1亿 (+20)")
    elif tvl > 10_000_000:
        score += 10
        details.append(f"TVL超$1000万 (+10)")
    elif tvl > 1_000_000:
        score += 5
        details.append(f"TVL超$100万 (+5)")

    # 链数量评分
    if len(chains) >= 5:
        score += 10
        details.append(f"多链部署 {len(chains)}条 (+10)")
    elif len(chains) >= 2:
        score += 5
        details.append(f"多链部署 {len(chains)}条 (+5)")

    # 分类加成
    premium_categories = ["DEX", "Lending", "Bridge", "Liquid Staking", "Yield", "Options", "Derivatives"]
    if category in premium_categories:
        score += 10
        details.append(f"热门赛道 {category} (+10)")

    # 7天增长评分
    if change_7d > 0.5:
        score += 15
        details.append(f"7天TVL暴增 {change_7d*100:.0f}% (+15)")
    elif change_7d > 0.2:
        score += 8
        details.append(f"7天TVL增长 {change_7d*100:.0f}% (+8)")
    elif change_7d > 0.05:
        score += 3
        details.append(f"7天TVL增长 {change_7d*100:.0f}% (+3)")

    return score, details


async def send_telegram_message(text):
    """发送消息到 Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] 未配置 Token 或 Chat ID，跳过推送")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            if result.get("ok"):
                print(f"[Telegram] 消息发送成功")
                return True
            else:
                print(f"[Telegram] 发送失败: {result}")
                return False
    except Exception as e:
        print(f"[Telegram] 异常: {e}")
        return False


async def push_project(protocol, score, details):
    """推送单个项目到 Telegram"""
    name = protocol.get("name", "Unknown")
    url = protocol.get("url", "")
    tvl = float(protocol.get("tvl", 0))
    category = protocol.get("category", "Unknown")
    chains = protocol.get("chains", [])
    description = protocol.get("description", "暂无描述")
    twitter = protocol.get("twitter", "")
    github = protocol.get("github", "")
    audit_links = protocol.get("audit_links", [])
    gecko_id = protocol.get("gecko_id", "")
   cmcId = protocol.get("cmcId", "")

    tvl_str = f"${tvl:,.0f}" if tvl >= 1 else f"${tvl:,.2f}"

    links = []
    if url:
        links.append(f"🌐 官网: {url}")
    if twitter:
        links.append(f"🐦 Twitter: {twitter}")
    if github:
        links.append(f"💻 GitHub: {github}")
    if gecko_id:
        links.append(f"📊 CoinGecko: https://www.coingecko.com/en/coins/{gecko_id}")
    if cmcId:
        links.append(f"📊 CoinMarketCap: https://coinmarketcap.com/currencies/{cmcId}")
    if audit_links:
        links.append(f"🔒 审计: {audit_links[0]}")

    links_str = "\n".join(links) if links else "暂无公开链接"

    detail_str = "\n".join([f"  • {d}" for d in details])

    text = f"""🎯 <b>新空投机会发现</b>

<b>项目名称:</b> {name}
<b>赛道分类:</b> {category}
<b>TVL:</b> {tvl_str}
<b>部署链:</b> {", ".join(chains[:5])}{"..." if len(chains) > 5 else ""}
<b>空投评分:</b> ⭐ {score} 分

<b>评分明细:</b>
{detail_str}

<b>项目描述:</b>
{description[:200]}{"..." if len(description) > 200 else ""}

<b>相关链接:</b>
{links_str}

⏰ 发现时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}"""

    success = await send_telegram_message(text)
    if success:
        system_state["total_pushes"] += 1
    return success


async def do_scan():
    """执行一次完整扫描"""
    if system_state["is_scanning"]:
        print("[扫描] 上次扫描未完成，跳过")
        return

    system_state["is_scanning"] = True
    system_state["total_scans"] += 1

    print(f"\n{'='*60}")
    print(f"[扫描开始] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    protocols = fetch_defillama_protocols()
    if not protocols:
        print("[扫描] 未获取到数据")
        system_state["is_scanning"] = False
        system_state["last_scan_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return

    new_pushed = 0
    updated_pushed = 0
    scan_results = []

    for protocol in protocols:
        name = protocol.get("name", "Unknown")
        url = protocol.get("url", "")
        key = f"{name}_{url}"

        score, details = calculate_score(protocol)

        if score >= THRESHOLD_SCORE:
            # 判断是否为新项目
            if key not in known_projects:
                # 新项目
                known_projects[key] = {
                    "name": name,
                    "url": url,
                    "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "last_score": score,
                    "pushed": False
                }
                scan_results.append((protocol, score, details, "new"))
            else:
                # 已记录项目，检查评分是否有显著变化
                old_score = known_projects[key].get("last_score", 0)
                if score >= old_score + 10 or score >= old_score + 5:
                    scan_results.append((protocol, score, details, "updated"))
                known_projects[key]["last_score"] = score
                known_projects[key]["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 先推送更新的项目
    for protocol, score, details, status in scan_results:
        if status == "updated":
            await push_project(protocol, score, details)
            updated_pushed += 1

    # 再推送新项目（新项目更重要）
    for protocol, score, details, status in scan_results:
        if status == "new":
            await push_project(protocol, score, details)
            known_projects[f"{protocol.get('name', '')}_{protocol.get('url', '')}"]["pushed"] = True
            new_pushed += 1

    save_data()

    system_state["last_scan_count"] = len(protocols)
    system_state["last_scan_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    system_state["is_scanning"] = False

    print(f"[扫描完成] 扫描 {len(protocols)} 个项目, 推送新项目 {new_pushed} 个, 更新项目 {updated_pushed} 个")
    print(f"{'='*60}\n")


async def scan_loop():
    """后台定时扫描任务"""
    while True:
        try:
            await do_scan()
        except Exception as e:
            print(f"[扫描异常] {e}")
            system_state["is_scanning"] = False
        await asyncio.sleep(SCAN_INTERVAL_MINUTES * 60)


# ======================== Telegram 命令 ========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """启动命令"""
    text = f"""🤖 <b>Airdrop Bot 已上线</b>

⏰ 每 {SCAN_INTERVAL_MINUTES} 分钟扫描一次
🎯 评分≥{THRESHOLD_SCORE} 自动推送
📊 数据源: DefiLlama 无代币协议

可用命令：
/menu - 显示主菜单
/status - 查看系统运行状态
/scan - 手动触发一次扫描
/clear - 清除历史记录重新开始
/help - 查看帮助"""
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """主菜单"""
    text = f"""📋 <b>系统菜单</b>

当前配置：
• 扫描间隔: {SCAN_INTERVAL_MINUTES} 分钟
• 推送阈值: {THRESHOLD_SCORE} 分
• 已记录项目: {len(known_projects)} 个

可用命令：
• /status - 系统状态
• /scan - 手动扫描
• /clear - 清除历史
• /help - 帮助信息"""
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """系统状态"""
    uptime = ""
    try:
        start = datetime.strptime(system_state["start_time"], "%Y-%m-%d %H:%M:%S")
        delta = datetime.now() - start
        hours = int(delta.total_seconds() // 3600)
        mins = int((delta.total_seconds() % 3600) // 60)
        uptime = f"{hours}小时{mins}分钟"
    except:
        uptime = "未知"

    text = f"""📊 <b>系统运行状态</b>

🕐 启动时间: {system_state["start_time"]}
⏱️ 运行时长: {uptime}
🔄 累计扫描: {system_state["total_scans"]} 次
📤 累计推送: {system_state["total_pushes"]} 条
📋 记录项目: {len(known_projects)} 个
⏳ 上次扫描: {system_state["last_scan_time"]}
📦 上次扫描量: {system_state["last_scan_count"]} 个项目
🎯 评分阈值: ≥{THRESHOLD_SCORE} 分
⏰ 扫描间隔: {SCAN_INTERVAL_MINUTES} 分钟"""
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """手动扫描"""
    await update.message.reply_text("🔄 正在手动扫描，请稍候...", parse_mode="HTML")
    await do_scan()
    await update.message.reply_text("✅ 扫描完成！", parse_mode="HTML")


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清除历史记录"""
    global known_projects
    known_projects = {}
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    system_state["total_pushes"] = 0
    system_state["total_scans"] = 0
    await update.message.reply_text("🗑️ 已清除所有历史记录，下次扫描将重新推送所有符合条件的项目。", parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """帮助信息"""
    text = """📖 <b>帮助文档</b>

本 Bot 自动监控 DefiLlama 上的无代币 DeFi 协议，
对每个项目进行多维度评分，达到阈值自动推送。

评分维度：
• TVL 规模（最高+30分）
• 多链部署（最高+10分）
• 热门赛道（+10分）
• TVL增速（最高+15分）

命令列表：
• /start - 欢迎信息
• /menu - 主菜单
• /status - 系统状态
• /scan - 手动扫描
• /clear - 清除历史
• /help - 此帮助"""
    await update.message.reply_text(text, parse_mode="HTML")


# ======================== Flask 路由 ========================
@app.route("/")
def index():
    return jsonify({
        "status": "alive",
        "service": "Airdrop Bot",
        "start_time": system_state["start_time"],
        "total_scans": system_state["total_scans"],
        "total_pushes": system_state["total_pushes"],
        "known_projects": len(known_projects),
        "last_scan_time": system_state["last_scan_time"],
        "last_scan_count": system_state["last_scan_count"]
    }), 200


@app.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200


@app.route("/trigger_scan", methods=["POST"])
def trigger_scan():
    """外部触发扫描（UptimeRobot 可用）"""
    import asyncio
    asyncio.create_task(do_scan())
    return jsonify({"status": "scan_triggered"}), 200


# ======================== 启动 ========================
import asyncio

tg_app = None

def run_bot_async():
    """在后台线程运行 Telegram Bot"""
    global tg_app
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    tg_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(CommandHandler("menu", cmd_menu))
    tg_app.add_handler(CommandHandler("status", cmd_status))
    tg_app.add_handler(CommandHandler("scan", cmd_scan))
    tg_app.add_handler(CommandHandler("clear", cmd_clear))
    tg_app.add_handler(CommandHandler("help", cmd_help))

    tg_app.run_polling(allowed_updates=Update.ALL_TYPES)


@app.before_request
def before_request():
    global tg_app
    if tg_app is None and TELEGRAM_BOT_TOKEN:
        import threading
        thread = threading.Thread(target=run_bot_async, daemon=True)
        thread.start()
        time.sleep(2)


if __name__ == "__main__":
    load_data()
    print(f"[启动] Airdrop Bot 初始化完成")
    print(f"[配置] 扫描间隔: {SCAN_INTERVAL_MINUTES}分钟, 推送阈值: {THRESHOLD_SCORE}分")
    print(f"[数据] 已加载 {len(known_projects)} 个历史记录")

    if not TELEGRAM_BOT_TOKEN:
        print("[警告] TELEGRAM_BOT_TOKEN 未配置")
    if not TELEGRAM_CHAT_ID:
        print("[警告] TELEGRAM_CHAT_ID 未配置")

    app.run(host="0.0.0.0", port=PORT)