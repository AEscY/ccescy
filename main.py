import os
import subprocess
import datetime
import time
import threading
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

def run_scan():
    """执行监控脚本并记录结果"""
    global last_run
    now = datetime.datetime.now().isoformat()
    print(f"🔄 开始扫描 {now}")

    try:
        # 执行 airdrop_monitor.py，超时 300 秒
        result = subprocess.run(
            ["python", "airdrop_monitor.py"],
            capture_output=True,
            text=True,
            timeout=300
        )
        last_run = {
            "status": "成功" if result.returncode == 0 else f"失败 (退出码 {result.returncode})",
            "time": now,
            "stdout": result.stdout[-1000:],  # 保留最后 1000 字符
            "stderr": result.stderr[-1000:]
        }
        print(f"✅ 扫描完成 (返回码 {result.returncode})")
        if result.stdout:
            print(result.stdout[-200:])
        if result.stderr:
            print("⚠️ 错误输出:", result.stderr[-200:])
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
    """发送启动通知到 Telegram"""
    push_url = os.getenv("PUSH_URL")
    push_secret = os.getenv("PUSH_SECRET")
    if not push_url or not push_secret:
        print("⚠️ 未设置 PUSH_URL 或 PUSH_SECRET，跳过启动通知")
        return
    try:
        import requests
        resp = requests.post(
            push_url,
            json={"message": "🚀 空投监控系统已启动，24/7 运行中"},
            headers={"X-Auth-Token": push_secret},
            timeout=10
        )
        if resp.status_code == 200:
            print("✅ 启动通知已发送")
        else:
            print(f"⚠️ 启动通知发送失败，状态码: {resp.status_code}")
    except Exception as e:
        print(f"⚠️ 启动通知发送异常: {e}")

# 启动后台调度器
scheduler = BackgroundScheduler()
# 添加任务：每6小时执行一次，立即执行第一次
scheduler.add_job(
    run_scan,
    'interval',
    hours=6,
    id='scan_job',
    next_run_time=datetime.datetime.now()  # 立即运行
)
scheduler.start()

# 发送启动通知（在独立线程中执行，避免阻塞启动）
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
        "下次运行": next_run.next_run_time.isoformat() if next_run else "未知"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.api_route("/run", methods=["GET", "POST"])
def manual_run():
    """手动触发扫描（支持浏览器 GET 或 POST）"""
    # 在新线程中执行，避免阻塞响应
    thread = threading.Thread(target=run_scan, daemon=True)
    thread.start()
    return {
        "message": "手动扫描已触发，请稍后查看结果",
        "当前状态": last_run
    }

@app.get("/status")
def status():
    return last_run