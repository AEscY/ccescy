import os
import subprocess
import datetime
import time
import threading
import json
import re
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler

app = FastAPI()

# 存储最后一次运行结果
last_run = {
    "status": "等待首次运行",
    "time": None,
    "stdout": "",
    "stderr": ""
}

# 存储当天所有高分项目（用于每日汇总）
daily_projects = []
daily_lock = threading.Lock()

# 每日汇总推送函数
def send_daily_summary():
    global daily_projects
    with daily_lock:
        if not daily_projects:
            push_message("📊 今日汇总：未发现任何高分项目")
            return
        # 按评分降序排序
        sorted_projects = sorted(daily_projects, key=lambda x: x['score'], reverse=True)
        # 构建消息
        lines = ["📈 **今日空投汇总**", f"📅 {datetime.datetime.now().strftime('%Y-%m-%d')}\n"]
        for idx, p in enumerate(sorted_projects[:10], 1):
            name = p.get('name', 'Unknown')
            score = p.get('score', 0)
            tvl = p.get('tvl', 0)
            chains = ', '.join(p.get('chains', [])[:3])
            url = p.get('url', '')
            lines.append(f"{idx}. **{name}** 评分: {score}/100")
            lines.append(f"   TVL: ${tvl:,.0f} | 链: {chains}")
            if url:
                lines.append(f"   🔗 {url}")
            lines.append("")
        if len(sorted_projects) > 10:
            lines.append(f"... 共 {len(sorted_projects)} 个项目")
        msg = "\n".join(lines)
        push_message(msg)
        # 清空当日列表
        daily_projects.clear()
        print("✅ 每日汇总已发送并清空列表")

def push_message(message):
    """推送消息到 Telegram（通过 Worker）"""
    push_url = os.getenv("PUSH_URL")
    push_secret = os.getenv("PUSH_SECRET")
    if not push_url or not push_secret:
        print("❌ PUSH_URL 或 PUSH_SECRET 未设置")
        return
    headers = {"Content-Type": "application/json", "X-Auth-Token": push_secret}
    try:
        resp = requests.post(push_url, json={"message": message}, headers=headers, timeout=10)
        print(f"推送结果: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"推送异常: {e}")

def run_scan():
    """执行监控脚本并记录结果，同时收集高分项目"""
    global last_run, daily_projects
    now = datetime.datetime.now().isoformat()
    print(f"🔄 开始扫描 {now}")

    try:
        result = subprocess.run(
            ["python", "airdrop_monitor.py"],
            capture_output=True,
            text=True,
            timeout=300
        )
        last_run = {
            "status": "成功" if result.returncode == 0 else f"失败 (退出码 {result.returncode})",
            "time": now,
            "stdout": result.stdout[-1000:],
            "stderr": result.stderr[-1000:]
        }
        print(f"✅ 扫描完成 (返回码 {result.returncode})")
        if result.stdout:
            print(result.stdout[-200:])
        if result.stderr:
            print("⚠️ 错误输出:", result.stderr[-200:])

        # 解析 stdout 中的 JSON 数据，收集高分项目
        # 匹配 ###GOOD_PROJECTS_START### 和 ###GOOD_PROJECTS_END### 之间的内容
        pattern = r"###GOOD_PROJECTS_START###(.*?)###GOOD_PROJECTS_END###"
        match = re.search(pattern, result.stdout, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
            try:
                projects = json.loads(json_str)
                if projects:
                    with daily_lock:
                        daily_projects.extend(projects)
                    print(f"📥 收集到 {len(projects)} 个项目用于每日汇总")
                else:
                    print("ℹ️ 本次扫描无高分项目")
            except json.JSONDecodeError as e:
                print(f"⚠️ 解析 JSON 失败: {e}")
        else:
            print("ℹ️ 未找到项目 JSON 数据")
    except subprocess.TimeoutExpired:
        last_run = {
            "status": "超时 (超过300秒)",
            "time": now,
            "stdout": "",
            "stderr": ""
        }
        print("❌ 扫描超时")
    except Exception as e:
        last_run = {
            "status": f"异常: {str(e)}",
            "time": now,
            "stdout": "",
            "stderr": ""
        }
        print(f"❌ 扫描异常: {e}")

def send_startup_notification():
    push_message("🚀 空投监控系统已启动，24/7 运行中")

# 启动后台调度器
scheduler = BackgroundScheduler()
# 每6小时执行一次扫描（立即执行第一次）
scheduler.add_job(
    run_scan,
    'interval',
    hours=6,
    id='scan_job',
    next_run_time=datetime.datetime.now()
)
# 每天 8:00 和 20:00 发送汇总简报
scheduler.add_job(
    send_daily_summary,
    'cron',
    hour=8,
    minute=0,
    id='daily_summary_8'
)
scheduler.add_job(
    send_daily_summary,
    'cron',
    hour=20,
    minute=0,
    id='daily_summary_20'
)
scheduler.start()

# 发送启动通知
threading.Thread(target=send_startup_notification, daemon=True).start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()

@app.get("/")
def root():
    next_run = scheduler.get_job('scan_job')
    return {
        "status": "Airdrop Monitor 24/7 运行中",
        "上次运行": last_run,
        "下次扫描": next_run.next_run_time.isoformat() if next_run else "未知"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.api_route("/run", methods=["GET", "POST"])
def manual_run():
    """手动触发扫描"""
    threading.Thread(target=run_scan, daemon=True).start()
    return {
        "message": "手动扫描已触发，请稍后查看结果",
        "当前状态": last_run
    }

@app.get("/status")
def status():
    return last_run

@app.get("/today")
def today_summary():
    """查看今日已收集的项目（不发送推送）"""
    with daily_lock:
        return {"count": len(daily_projects), "projects": daily_projects}