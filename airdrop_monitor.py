import os
import requests
from datetime import datetime, timedelta

# ---- 从环境变量读取（Render 会自动注入） ----
PUSH_URL = os.getenv("PUSH_URL")      # 例如: https://airdrop-pusher.xxx.workers.dev/push
PUSH_SECRET = os.getenv("PUSH_SECRET") # 与 Worker 中的 PUSH_SECRET 一致
# ------------------------------------------------

def fetch_new_projects():
    """从 DeFiLlama 获取最近7天的新项目"""
    try:
        resp = requests.get("https://api.llama.fi/protocols", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        week_ago = int((datetime.now() - timedelta(days=7)).timestamp())
        return [p for p in data if p.get('listedAt', 0) > week_ago]
    except Exception as e:
        print(f"❌ 获取项目失败: {e}")
        return []

def score_project(p):
    """简单评分规则：TVL + 链数量 + 审计 + 开源"""
    score = 0
    tvl = p.get('tvl', 0)
    if tvl > 10_000_000: score += 40
    elif tvl > 1_000_000: score += 20
    else: score += 5

    chains = p.get('chains', [])
    if len(chains) >= 3: score += 20
    elif len(chains) >= 2: score += 10

    if p.get('audits'): score += 15
    if p.get('github'): score += 10
    return min(score, 100)

def push(message):
    if not PUSH_URL or not PUSH_SECRET:
        print("❌ 环境变量未设置")
        return
    headers = {"Content-Type": "application/json", "X-Auth-Token": PUSH_SECRET}
    try:
        resp = requests.post(PUSH_URL, json={"message": message}, headers=headers, timeout=10)
        print("✅ 推送结果:", resp.json())
    except Exception as e:
        print("❌ 推送失败:", e)

def main():
    print(f"🔄 开始扫描 {datetime.now()}")
    projects = fetch_new_projects()
    if not projects:
        print("ℹ️ 未发现新项目")
        return

    good = []
    for p in projects[:30]:
        s = score_project(p)
        if s >= 60:
            good.append((p, s))

    if not good:
        print("ℹ️ 没有高分项目")
        return

    # 组装消息
    lines = ["🚀 **空投情报**", f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
    for p, s in good[:5]:
        name = p.get('name', 'Unknown')
        tvl = p.get('tvl', 0)
        chains = ', '.join(p.get('chains', [])[:3])
        url = p.get('url', '')
        lines.append(f"**{name}** 评分: {s}/100")
        lines.append(f"  TVL: ${tvl:,.0f} | 链: {chains}")
        if url: lines.append(f"  🔗 {url}")
        lines.append("")
    push("\n".join(lines))
    print(f"✅ 完成，推送了 {len(good)} 个项目")

if __name__ == "__main__":
    main()