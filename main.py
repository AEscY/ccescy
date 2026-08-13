from fastapi import FastAPI
import subprocess
import threading
import time
import os

app = FastAPI()

def run_scan():
    """执行监控脚本"""
    print(f"🔄 开始扫描 {time.strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        result = subprocess.run(
            ["python", "airdrop_monitor.py"],
            capture_output=True,
            text=True,
            timeout=300
        )
        print(f"✅ 扫描完成: {result.stdout[:200]}")
        if result.stderr:
            print(f"⚠️ 错误: {result.stderr[:200]}")
    except Exception as e:
        print(f"❌ 扫描异常: {e}")

@app.on_event("startup")
def startup_event():
    """应用启动后立即运行一次扫描，并在后台定时执行"""
    thread = threading.Thread(target=run_scan, daemon=True)
    thread.start()
    
    def schedule_scan():
        while True:
            time.sleep(6 * 3600)  # 每6小时执行一次
            run_scan()
    
    scheduler = threading.Thread(target=schedule_scan, daemon=True)
    scheduler.start()

@app.get("/")
def root():
    return {"status": "Airdrop Monitor 24/7 运行中"}

@app.get("/health")
def health_check():
    """Render 健康检查端点 - 必须立即响应"""
    return {"status": "healthy"}