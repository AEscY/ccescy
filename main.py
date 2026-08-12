import os
import feedparser
import requests
from fastapi import FastAPI
from datetime import datetime

app = FastAPI()

# 从环境变量读取密钥（Render Dashboard 里配置）
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
CF_ACCOUNT_ID = os.getenv('CF_ACCOUNT_ID')
CF_API_TOKEN = os.getenv('CF_API_TOKEN')


def send_telegram(message):
    """发送消息到 Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram 密钥未配置")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
        print("Telegram 消息推送成功")
    except Exception as e:
        print(f"推送失败: {e}")


def ai_summary(title, description):
    """调用 Cloudflare AI 生成空投摘要和风险评分"""
    if not CF_API_TOKEN or not CF_ACCOUNT_ID:
        return "⚠️ 未配置 Cloudflare AI，请检查环境变量"

    try:
        url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/@cf/meta/llama-3.1-8b-instruct"
        headers = {"Authorization": f"Bearer {CF_API_TOKEN}"}
        prompt = f"用中文一句话总结这个空投项目，并给出1-10的风险评分（分数越低越安全，只回复数字和一句话）：标题：{title}，描述：{description[:200]}"
        data = {"messages": [{"role": "user", "content": prompt}]}

        response = requests.post(url, json=data, headers=headers, timeout=30)
        result = response.json()

        if 'result' in result and 'response' in result['result']:
            return result['result']['response']
        else:
            return f"AI 分析异常: {result}"
    except Exception as e:
        return f"AI 分析失败: {str(e)[:50]}"


@app.get("/")
def root():
    """根路径，用于检查服务是否运行"""
    return {"message": "Airdrop Hunter is running!", "status": "ok"}


@app.get("/hunt")
def hunt_airdrops():
    """抓取空投信息并推送到 Telegram"""
    try:
        # 从 Airdrops.io 抓取 RSS 源
        feed = feedparser.parse('https://airdrops.io/feed/')
        entries = feed.entries[:3]  # 只取前 3 个

        if not entries:
            send_telegram("⚠️ 未抓取到任何空投数据，请检查 RSS 源")
            return {"status": "success", "count": 0}

        for entry in entries:
            analysis = ai_summary(entry.title, entry.description)
            message = f"""🚀 *新空投发现*

📌 项目：{entry.title}
🔗 详情：{entry.link}
📝 AI 分析：{analysis}
⏰ 时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}"""

            send_telegram(message)

        return {"status": "success", "count": len(entries)}

    except Exception as e:
        error_msg = f"❌ 抓取失败: {str(e)}"
        send_telegram(error_msg)
        return {"status": "error", "message": str(e)}


@app.get("/health")
def health_check():
    """健康检查端点，用于外部监控保活"""
    return {"status": "alive"}