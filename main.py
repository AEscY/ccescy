from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
import subprocess
import datetime
import os

app = FastAPI()

# 存储最后一次运行结果
last_run = {"status": "等待首次运行", "time": None}

def run_scan():
    """执行监控脚本"""
    global last_run
    print(f"🔄 开始扫描 {datetime.datetime.now()}")
    try:
        result = subprocess.run(
            ["python", "airdrop_monitor.py"],
            capture_output=True,
            text=True,
            timeout=300  # 5分钟超时
        )
        last_run = {
            "status": "成功" if result.returncode == 0 else f"失败 (退出码 {result.returncode})",
            "time": datetime.datetime.now().isoformat(),
            "stdout": result.stdout[-500:],  # 只保存最后500字符
            "stderr": result.stderr[-500:]
        }
        print(f"✅ 扫描完成: {result.stdout[:100]}")
    except Exception as e:
        last_run = {
            "status": f"异常: {str(e)}",
            "time": datetime.datetime.now().isoformat()
        }
        print(f"❌ 扫描异常: {e}")

# 启动后台调度器
scheduler = BackgroundScheduler()
scheduler.add_job(run_scan, 'interval', hours=6, id='scan_job', next_run_time=datetime.datetime.now())
scheduler.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()

@app.get("/")
def root():
    return {
        "status": "Airdrop Monitor 24/7 运行中",
        "上次运行": last_run,
        "下次运行": scheduler.get_job('scan_job').next_run_time.isoformat() if scheduler.get_job('scan_job') else "未知"
    }

@app.post("/run")
def manual_run():
    """手动触发扫描"""
    run_scan()
    return {"message": "手动扫描已触发", "结果": last_run}

@app.get("/status")
def status():
    return last_run