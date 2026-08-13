import os
import requests
import json
from datetime import datetime, timedelta

# ---- 从环境变量读取 ----
PUSH_URL = os.getenv("PUSH_URL")
PUSH_SECRET = os.getenv("PUSH_SECRET")
# -------------------------

def fetch_new_projects():
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
    score = 0
    tvl = p.get('tvl', 0)
    if tvl > 10_000_000:
        score += 40
    elif tvl > 1_000_000:
        score += 20
    else:
        score += 5

    chains = p.get('chains', [])
    if len(chains) >= 3:
        score += 20
    elif len(chains) >= 2:
        score += 10

    if p.get('audits'):
        score += 15
    if p.get('github'):
        score += 10
    return min(score, 100)

def push(message):
    print(f"📤 准备推送消息: {message[:50]}...")
    if not PUSH_URL or not PUSH_SECRET:
        print("❌ 环境变量 PUSH_URL 或 PUSH_SECRET 未设置")
        return
    headers = {"Content-Type": "application/json", "X-Auth-Token": PUSH_SECRET}
    try:
        resp = requests.post(PUSH_URL, json={"message": message}, headers=headers, timeout=10)
        if resp.status_code == 200:
            print(f"✅ 推送成功: {resp.json()}")
        else:
            print(f"⚠️ 推送失败，状态码 {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"❌ 推送异常: {e}")

def format_project_message(projects):
    lines = ["🚀 **空投情报**", f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
    for p, s in projects[:5]:
        name = p.get('name', 'Unknown')
        tvl = p.get('tvl', 0)
        chains = ', '.join(p.get('chains', [])[:3])
        url = p.get('url', '')
        lines.append(f"**{name}** 评分: {s}/100")
        lines.append(f"  TVL: ${tvl:,.0f} | 链: {chains}")
        if url:
            lines.append(f"  🔗 {url}")
        lines.append("")
    return "\n".join(lines)

def main():
    print(f"🔄 开始扫描 {datetime.now()}")

    # 强制测试推送（可注释掉）
    # push("🚀 空投监控系统已启动（测试消息，请忽略）")

    projects = fetch_new_projects()
    if not projects:
        print("ℹ️ 未发现新项目")
        # 输出空列表供 main.py 收集
        print("###GOOD_PROJECTS_START###")
        print(json.dumps([]))
        print("###GOOD_PROJECTS_END###")
        return

    good = []
    for p in projects[:30]:
        s = score_project(p)
        if s >= 60:
            good.append((p, s))

    if not good:
        print("ℹ️ 没有高分项目")
        push("📊 本次扫描完成，未发现高分项目")
        # 输出空列表
        print("###GOOD_PROJECTS_START###")
        print(json.dumps([]))
        print("###GOOD_PROJECTS_END###")
        return

    # 推送即时消息
    push(format_project_message(good))
    print(f"✅ 完成，推送了 {len(good)} 个项目")

    # 输出 JSON 供 main.py 解析（用于每日汇总）
    print("###GOOD_PROJECTS_START###")
    # 只输出项目名称和评分等关键信息，完整数据在 main.py 中存储
    out_data = [{"name": p[0]['name'], "score": p[1], "tvl": p[0].get('tvl',0), "chains": p[0].get('chains',[]), "url": p[0].get('url','')} for p in good]
    print(json.dumps(out_data))
    print("###GOOD_PROJECTS_END###")

if __name__ == "__main__":
    main()