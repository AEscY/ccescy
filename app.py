from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import os
import time
from datetime import datetime

app = Flask(__name__)

# ========== 配置 ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN')
TG_API = f'https://api.telegram.org/bot{BOT_TOKEN}'
CHAT_ID = os.environ.get('CHAT_ID', 'YOUR_CHAT_ID')

THRESHOLD = int(os.environ.get('THRESHOLD', '30'))
SCAN_INTERVAL = 30  # 分钟
PAUSED = False

# 运行统计
stats = {
    'start_time': time.time(),
    'total_scans': 0,
    'total_pushed': 0,
    'last_scan': None,
    'tracked_projects': set()
}

# 项目数据存储
project_scores = {}

# ========== 工具函数 ==========
def send_message(text):
    url = f'{TG_API}/sendMessage'
    data = {'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
    try:
        requests.post(url, json=data, timeout=10)
    except:
        pass

def format_runtime(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}小时{minutes}分钟"

# ========== 评分逻辑 ==========
def calculate_score(project):
    score = 0
    details = []
    
    name = project.get('name', 'Unknown')
    tvl = project.get('tvlUsd', 0)
    chain_count = len(project.get('chains', []))
    
    # TVL评分
    if tvl > 100_000_000:
        score += 30
        details.append(f"💰 TVL>${tvl/1e6:.0f}M → +30")
    elif tvl > 10_000_000:
        score += 20
        details.append(f"💰 TVL>${tvl/1e6:.0f}M → +20")
    elif tvl > 1_000_000:
        score += 10
        details.append(f"💰 TVL>${tvl/1e6:.0f}M → +10")
    else:
        details.append(f"💰 TVL<${tvl/1e6:.2f}M → +0")
    
    # 多链部署
    if chain_count >= 5:
        score += 15
        details.append(f"🔗 {chain_count}条链 → +15")
    elif chain_count >= 2:
        score += 8
        details.append(f"🔗 {chain_count}条链 → +8")
    else:
        details.append(f"🔗 单链 → +0")
    
    # 分类加分
    category = project.get('category', '')
    if category in ['Dexes', 'Lending', 'Bridge', 'Liquid Staking']:
        score += 10
        details.append(f"📂 {category}赛道 → +10")
    
    details.append(f"\n🎯 总分: {score}")
    return score, details

# ========== 扫描逻辑 ==========
def scan_defillama():
    global stats, PAUSED
    
    if PAUSED:
        return
    
    stats['total_scans'] += 1
    stats['last_scan'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    url = 'https://api.llama.fi/protocols'
    try:
        response = requests.get(url, timeout=30)
        protocols = response.json()
    except:
        send_message("⚠️ DefiLlama API请求失败")
        return
    
    # 筛选无代币协议
    no_token_protocols = [p for p in protocols if not p.get('token') and p.get('tvlUsd', 0) > 0]
    
    new_projects = []
    for p in no_token_protocols:
        name = p.get('name')
        if not name:
            continue
        
        score, details = calculate_score(p)
        project_scores[name] = {'score': score, 'details': details, 'data': p}
        
        if score >= THRESHOLD:
            if name not in stats['tracked_projects']:
                stats['tracked_projects'].add(name)
                new_projects.append((name, score, details, p))
    
    # 推送新项目
    for name, score, details, p in new_projects:
        chain_list = ', '.join(p.get('chains', ['Unknown'])[:5])
        tvl_m = p.get('tvlUsd', 0) / 1e6
        category = p.get('category', 'Unknown')
        
        msg = (
            f"🚨 <b>新空投发现</b>\n\n"
            f"📌 名称: {name}\n"
            f"📂 赛道: {category}\n"
            f"🔗 链: {chain_list}\n"
            f"💰 TVL: ${tvl_m:.2f}M\n"
            f"🎯 评分: <b>{score}</b> (阈值:{THRESHOLD})\n\n"
            f"<b>评分明细:</b>\n" + '\n'.join(details) + "\n\n"
            f"🔗 <a href='https://defillama.com/protocol/{name.lower().replace(' ', '-')}'>DefiLlama</a>"
        )
        send_message(msg)
        stats['total_pushed'] += 1
        time.sleep(1)  # 防TG限流

# ========== Flask路由 ==========
@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'status': 'alive',
        'bot': 'EVE_iPhone_bot',
        'uptime': format_runtime(time.time() - stats['start_time']),
        'threshold': THRESHOLD,
        'paused': PAUSED
    })

@app.route(f'/webhook/{BOT_TOKEN}', methods=['POST'])
def webhook():
    global PAUSED, THRESHOLD
    
    update = request.json
    if not update or 'message' not in update:
        return 'ok'
    
    msg = update['message']
    chat_id = msg.get('chat', {}).get('id')
    text = msg.get('text', '').strip()
    cmd = text.split()[0].lower() if text else ''
    args = text.split()[1:] if len(text.split()) > 1 else []
    
    if chat_id != int(CHAT_ID):
        return 'ok'
    
    # 命令路由
    if cmd == '/start':
        send_message(
            f"🤖 <b>欢迎使用 Airdrop Bot</b>\n\n"
            f"这是一个全自动空投情报追踪系统。\n\n"
            f"📡 数据源: DefiLlama\n"
            f"⏰ 扫描频率: 每{SCAN_INTERVAL}分钟\n"
            f"🎯 推送阈值: 评分≥{THRESHOLD}\n\n"
            f"输入 /help 查看所有命令"
        )
    
    elif cmd == '/help':
        send_message(
            "📖 <b>命令列表</b>\n\n"
            "/status - 查看Bot运行状态\n"
            "/scan - 手动触发扫描\n"
            "/list - 查看追踪项目列表\n"
            "/project [名称] - 查询项目评分详情\n"
            "/threshold [数字] - 调整推送阈值\n"
            "/pause - 暂停推送\n"
            "/resume - 恢复推送\n"
            "/help - 显示此帮助"
        )
    
    elif cmd == '/status':
        uptime = format_runtime(time.time() - stats['start_time'])
        send_message(
            f"📊 <b>Bot运行状态</b>\n\n"
            f"⏱ 在线时长: {uptime}\n"
            f"🔄 累计扫描: {stats['total_scans']}次\n"
            f"📬 累计推送: {stats['total_pushed']}条\n"
            f"👁 追踪项目: {len(stats['tracked_projects'])}个\n"
            f"🎯 当前阈值: {THRESHOLD}\n"
            f"⏸ 推送状态: {'暂停' if PAUSED else '运行中'}\n"
            f"🕐 最后扫描: {stats['last_scan'] or '尚未扫描'}"
        )
    
    elif cmd == '/scan':
        send_message("🔄 正在手动扫描...")
        scan_defillama()
        send_message("✅ 扫描完成")
    
    elif cmd == '/list':
        if not project_scores:
            send_message("📭 暂无追踪项目，等待首次扫描...")
        else:
            sorted_projects = sorted(
                [(n, d['score']) for n, d in project_scores.items() if d['score'] >= THRESHOLD],
                key=lambda x: x[1], reverse=True
            )
            if not sorted_projects:
                send_message(f"📭 暂无评分≥{THRESHOLD}的项目")
            else:
                lines = [f"📋 <b>高分项目列表</b> (≥{THRESHOLD})\n"]
                for i, (name, score) in enumerate(sorted_projects[:20], 1):
                    lines.append(f"{i}. {name} — ⭐{score}")
                if len(sorted_projects) > 20:
                    lines.append(f"\n...还有{len(sorted_projects)-20}个")
                send_message('\n'.join(lines))
    
    elif cmd == '/project':
        if not args:
            send_message("⚠️ 用法: /project [项目名称]\n例如: /project Uniswap")
        else:
            query = ' '.join(args).lower()
            found = [(n, d) for n, d in project_scores.items() if query in n.lower()]
            if not found:
                send_message(f"🔍 未找到匹配 '{' '.join(args)}' 的项目")
            else:
                for name, data in found:
                    p = data['data']
                    tvl_m = p.get('tvlUsd', 0) / 1e6
                    chains = ', '.join(p.get('chains', [])[:5])
                    msg = (
                        f"📌 <b>{name}</b>\n"
                        f"⭐ 评分: {data['score']}\n"
                        f"💰 TVL: ${tvl_m:.2f}M\n"
                        f"🔗 链: {chains}\n"
                        f"📂 赛道: {p.get('category', 'Unknown')}\n\n"
                        f"评分明细:\n" + '\n'.join(data['details'])
                    )
                    send_message(msg)
    
    elif cmd == '/threshold':
        if not args:
            send_message(f"⚠️ 用法: /threshold [数字]\n当前阈值: {THRESHOLD}")
        else:
            try:
                new_val = int(args[0])
                THRESHOLD = new_val
                send_message(f"✅ 推送阈值已更新为: <b>{THRESHOLD}</b>")
            except:
                send_message("⚠️ 请输入有效数字")
    
    elif cmd == '/pause':
        PAUSED = True
        send_message("⏸ 推送已暂停。Bot仍在扫描，但不会发送消息。")
    
    elif cmd == '/resume':
        PAUSED = False
        send_message("▶️ 推送已恢复。")
    
    return 'ok'

# ========== 定时任务 ==========
scheduler = BackgroundScheduler()
scheduler.add_job(scan_defillama, 'interval', minutes=SCAN_INTERVAL)
scheduler.start()

# 启动时立即扫描一次
scan_defillama()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))