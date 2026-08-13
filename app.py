import asyncio
import logging
import threading
from flask import Flask, jsonify
from scheduler import AirdropScheduler

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("AirdropBot")

# Flask应用（提供HTTP端点，防止Render休眠）
app = Flask(__name__)

# 全局调度器实例
scheduler = AirdropScheduler()


@app.route("/")
def health_check():
    """健康检查端点 - UptimeRobot和GitHub Actions会ping这里"""
    return jsonify({
        "status": "alive",
        "projects_tracked": len(scheduler.projects),
        "cycles_completed": scheduler.cycle_count,
    })


@app.route("/status")
def status():
    """详细状态端点"""
    top_projects = sorted(
        [v["project"] for v in scheduler.projects.values()],
        key=lambda x: x.score, reverse=True
    )[:10]
    return jsonify({
        "status": "running",
        "total_projects": len(scheduler.projects),
        "cycles": scheduler.cycle_count,
        "top_projects": [
            {
                "name": p.name,
                "score": p.score,
                "tvl": p.tvl,
                "status": p.status.value,
            }
            for p in top_projects
        ],
    })


@app.route("/trigger")
def trigger_scan():
    """手动触发扫描（GitHub Actions调用此端点）"""
    asyncio.run_coroutine_threadsafe(
        scheduler._scan_cycle(), loop
    )
    return jsonify({"message": "Scan triggered"})


def run_scheduler():
    """在后台线程运行调度器"""
    asyncio.run(scheduler.start())


# 启动后台调度线程
scheduler_thread = threading.Thread(
    target=run_scheduler, daemon=True
)
scheduler_thread.start()

# 获取事件循环引用（用于手动触发）
loop = asyncio.new_event_loop()


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)