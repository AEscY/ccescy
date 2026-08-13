import os
import requests
from datetime import datetime, timedelta

# ----- 从 Render 环境变量读取配置 -----
WORKER_URL = os.getenv("WORKER_URL")
PUSH_SECRET = os.getenv("PUSH_SECRET")
# -------------------------------------

def fetch_new_projects():
    """从 DeFiLlama 获取所有协议，按最近上线排序"""
    try:
        resp = requests.get("https://api.llama.fi/protocols", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        # 按 listedAt 倒序排列（最新上线的在前）
        sorted_projects = sorted(data, key=lambda x: x.get('listedAt', 0), reverse=True)
        
        # 只取最近 7 天上线的项目
        week_ago = int((datetime.now() - timedelta(days=7)).timestamp())
        new_projects = [p for p in sorted_projects if p.get('listedAt', 0) > week_ago]
        
        return new_projects
    except Exception as e:
        print(f"❌ 获取项目失败: {e}")
        return []

def score_project(project):
    """简单评分：TVL 越高、链越多，分数越高"""
    score = 0
    tvl = project.get('tvl', 0)
    chains = project.get('chains', [])
    
    if tvl > 10_000_000:   # TVL > 1000万美金
        score += 40
    elif tvl > 1_000_000:  # TVL > 100万美金
        score += 20
    else:
        score += 5
    
    # 链数量加分
    if len(chains) >= 3:
        score += 20
    elif len(chains) >= 2:
        score += 10
    
    # 有明确审计信息加分
    if project.get('audits'):
        score += 15
    
    # 有开源代码加分
    if project.get('github'):
        score += 10
    
    return min(score, 100)

def push_to_telegram(message):
    """通过 Cloudflare Worker 推送到 Telegram"""
    if not WORKER_URL or not PUSH_SECRET:
        print("❌ 环境变量 WORKER_URL 或 PUSH_SECRET 未设置")
        return
    
    headers = {
        "Content-Type": "application/json",
        "X-Auth-Token": PUSH_SECRET
    }
    data = {"message": message}
    
    try:
        resp = requests.post(WORKER_URL, json=data, headers=headers, timeout=10)
        print(f"✅ 推送结果: {resp.json()}")
    except Exception as e:
        print(f"❌ 推送失败: {e}")

def main():
    print(f"🔄 开始扫描空投项目... {datetime.now()}")
    
    projects = fetch_new_projects()
    if not projects:
        print("ℹ️ 未发现新项目")
        return
    
    print(f"📊 发现 {len(projects)} 个新项目，开始评分...")
    
    high_score_projects = []
    for p in projects[:20]:  # 最多处理前20个
        score = score_project(p)
        if score >= 60:
            high_score_projects.append((p, score))
    
    if not high_score_projects:
        print("ℹ️ 没有高分项目需要推送")
        return
    
    # 构造推送消息
    msg_lines = ["🚀 **空投情报周报**"]
    msg_lines.append(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    
    for p, score in high_score_projects[:5]:  # 最多推送5个
        name = p.get('name', 'Unknown')
        tvl = p.get('tvl', 0)
        chains = ', '.join(p.get('chains', [])[:3])
        url = p.get('url', '')
        
        msg_lines.append(f"**{name}** | 评分: {score}/100")
        msg_lines.append(f"  TVL: ${tvl:,.0f} | 链: {chains}")
        if url:
            msg_lines.append(f"  🔗 {url}")
        msg_lines.append("")
    
    push_to_telegram("\n".join(msg_lines))
    print(f"✅ 完成，推送了 {len(high_score_projects)} 个项目")

if __name__ == "__main__":
    main()