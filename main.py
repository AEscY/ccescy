import os
import feedparser
import requests
from fastapi import FastAPI
from datetime import datetime
import logging

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
        res = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
        if res.status_code == 200:
            print("Telegram 消息推送成功")
        else:
            print(f"Telegram 推送可能被限制，状态码: {res.status_code}, 错误: {res.text}")
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

        response = requests.post(url, json=data, headers=headers, timeout=15)
        result = response.json()

        # 更加安全的 AI 结果解析
        if result and result.get('result') and 'response' in result['result']:
            return result['result']['response']
        else:
            return f"AI 分析异常: {result}"
    except Exception as e:
        # 如果 AI 调用超时或失败，直接返回默认信息，不影响消息推送
        return "⚠️ AI 分析超时或失败，请自行判断风险。"

@app.get("/")
def root():
    return {"message": "Airdrop Hunter is running!", "status": "ok"}

@app.get("/hunt")
def hunt_airdrops():
    """抓取空投信息并推送到 Telegram"""
    try:
        # 【修复1】伪装浏览器请求头，防止被 RSS 源屏蔽
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        # 【修复2】先通过 requests 拿到源数据，再交给 feedparser 解析
        print("开始抓取 airdrops.io 的 RSS 数据...")
        resp = requests.get('https://airdrops.io/feed/', headers=headers, timeout=15)
        
        if resp.status_code != 200:
            print(f"❌ RSS 请求失败，状态码: {resp.status_code}")
            send_telegram(f"⚠️ 抓取 RSS 失败，状态码 {resp.status_code}，请检查源是否失效。")
            return {"status": "error", "message": f"status {resp.status_code}"}

        # 解析 RSS 内容
        feed = feedparser.parse(resp.content)
        entries = feed.entries[:3]  # 只取前 3 个

        print(f"✅ 成功抓取到 {len(entries)} 条空投数据")

        if not entries:
            send_telegram("⚠️ 未抓取到任何空投数据 (RSS解析为空)，请检查源地址")
            return {"status": "success", "count": 0}

        for entry in entries:
            analysis = ai_summary(entry.title, entry.description)
            message = f"""🚀 *新空投发现*

📌 项目：{entry.title}
🔗 详情：{entry.link}
📝 AI 分析：{analysis}
⏰ 时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}"""

            send_telegram(message)
            # 【建议】增加 1 秒延迟，防止发送太快被 Telegram 限频
            import time
            time.sleep(1)

        return {"status": "success", "count": len(entries)}

    except Exception as e:
        error_msg = f"❌ 抓取过程发生致命错误: {str(e)}"
        print(error_msg)
        send_telegram(error_msg)
        return {"status": "error", "message": str(e)}

@app.get("/health")
def health_check():
    return {"status": "alive"}