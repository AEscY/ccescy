import os
import sys
import json
import re
import requests
from datetime import datetime, timedelta

# ---------- 导入智谱 AI SDK ----------
try:
    from zhipuai import ZhipuAI
    ZHIPU_AVAILABLE = True
except ImportError:
    ZHIPU_AVAILABLE = False
    print("⚠️ 未安装 zhipuai，请运行: pip install zhipuai")

# ---------- 从环境变量读取配置 ----------
PUSH_URL = os.getenv("PUSH_URL")
PUSH_SECRET = os.getenv("PUSH_SECRET")
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "glm-4-flash")

# ---------- 多链配置 ----------
# 默认监控链：从环境变量读取，逗号分隔，默认 EVM 主流链
MONITORED_CHAINS = os.getenv("MONITORED_CHAINS", "ethereum,arbitrum,base,solana,sui,optimism,polygon").split(",")
# 清洗空格
MONITORED_CHAINS = [c.strip() for c in MONITORED_CHAINS if c.strip()]
print(f"📌 监控链列表: {MONITORED_CHAINS}")

# ---------- 初始化智谱客户端 ----------
zhipu_client = None
if ZHIPU_AVAILABLE and ZHIPU_API_KEY:
    try:
        zhipu_client = ZhipuAI(api_key=ZHIPU_API_KEY)
        print("✅ 智谱 AI (GLM-4-Flash) 已初始化")
    except Exception as e:
        print(f"❌ 智谱 AI 初始化失败: {e}")
else:
    if not ZHIPU_AVAILABLE:
        print("⚠️ 缺少 zhipuai 库，AI 评分禁用")
    elif not ZHIPU_API_KEY:
        print("⚠️ 未设置 ZHIPU_API_KEY，AI 评分禁用")

# ---------- 数据获取（多链） ----------
def fetch_projects_by_chain(chain):
    """从 DeFiLlama 获取指定链的新项目（最近7天）"""
    try:
        url = f"https://api.llama.fi/protocols?chain={chain}"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        week_ago = int((datetime.now() - timedelta(days=7)).timestamp())
        # 过滤最近7天新增的项目
        new_projects = [p for p in data if p.get('listedAt', 0) > week_ago]
        print(f"  🔗 {chain}: 发现 {len(new_projects)} 个新项目")
        return new_projects
    except Exception as e:
        print(f"❌ 获取链 {chain} 项目失败: {e}")
        return []

def fetch_all_projects():
    """汇总所有监控链的项目，并去重（按项目名称去重）"""
    all_projects = []
    seen_names = set()
    for chain in MONITORED_CHAINS:
        projects = fetch_projects_by_chain(chain)
        for p in projects:
            name = p.get('name', '')
            if name and name not in seen_names:
                seen_names.add(name)
                # 合并链信息（如果已存在相同名称的项目，可能来自不同链，但 DeFiLlama 通常全局唯一）
                all_projects.append(p)
    print(f"📊 总去重后新项目数: {len(all_projects)}")
    return all_projects

# ---------- 规则评分 ----------
def score_project(p):
    """规则评分：TVL + 链数量 + 审计 + 开源"""
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

# ---------- AI 评分 ----------
def ai_score_project(project):
    """使用智谱 GLM-4-Flash 对项目评分 (0-100)"""
    if not zhipu_client:
        return None

    name = project.get('name', '未知')
    description = project.get('description', '无描述')
    chains = ', '.join(project.get('chains', [])[:5])
    tvl = project.get('tvl', 0)
    url = project.get('url', '无官网')

    prompt = f"""你是一个专业的 Web3 空投分析师。请评估以下项目是否值得关注，给出 0-100 分的评分。

项目名称：{name}
项目描述：{description}
所在链：{chains}
TVL：${tvl:,.0f}
官网：{url}

评分规则：
- 有清晰的产品定位和路线图：+20分
- 有知名投资机构或审计报告：+20分
- 社交媒体活跃、社区有讨论：+15分
- 代码已开源且持续更新：+15分
- 项目名称含有"AI""元宇宙""Web3"等蹭热点词汇：-20分
- 描述模糊、无实际产品：-30分

请只返回一个数字评分（0-100），不要有任何其他文字。"""

    try:
        response = zhipu_client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": "你是一个专业的 Web3 空投分析师，只返回数字评分。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=10
        )
        score_text = response.choices[0].message.content.strip()
        numbers = re.findall(r'\d+', score_text)
        if numbers:
            score = int(numbers[0])
            return min(100, max(0, score))
        return None
    except Exception as e:
        print(f"⚠️ AI 评分失败 ({name}): {e}")
        return None

# ---------- 推送函数 ----------
def push(message):
    """推送消息到 Telegram"""
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

# ---------- 格式化消息 ----------
def format_project_message(projects):
    """格式化项目推送消息（含 AI 评分）"""
    lines = ["🚀 **空投情报（多链）**", f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
    for p, final_score in projects[:5]:
        name = p.get('name', 'Unknown')
        tvl = p.get('tvl', 0)
        chains = ', '.join(p.get('chains', [])[:3])
        url = p.get('url', '')
        ai_score = p.get('ai_score', 'N/A')
        rule_score = p.get('rule_score', 'N/A')
        lines.append(f"**{name}** 综合: {final_score}/100 | AI: {ai_score}/100 | 规则: {rule_score}/100")
        lines.append(f"  TVL: ${tvl:,.0f} | 链: {chains}")
        if url:
            lines.append(f"  🔗 {url}")
        lines.append("")
    return "\n".join(lines)

# ---------- 主流程 ----------
def main():
    print(f"🔄 开始多链扫描 {datetime.now()}")

    # 获取所有链的项目
    projects = fetch_all_projects()
    if not projects:
        print("ℹ️ 未发现新项目")
        print("###GOOD_PROJECTS_START###")
        print(json.dumps([]))
        print("###GOOD_PROJECTS_END###")
        return

    print(f"📊 共发现 {len(projects)} 个新项目，开始评分...")

    good = []
    for p in projects[:30]:  # 限制数量避免 API 过载
        rule_score = score_project(p)

        ai_score = None
        if zhipu_client and rule_score >= 40:
            ai_score = ai_score_project(p)
            if ai_score is not None:
                print(f"  🤖 {p.get('name')}: 规则={rule_score}, AI={ai_score}")
            else:
                print(f"  ⚠️ {p.get('name')}: AI 评分失败，使用规则评分")
                ai_score = rule_score
        else:
            ai_score = rule_score

        final_score = int((rule_score + ai_score) / 2) if ai_score is not None else rule_score

        if final_score >= 60:
            p['rule_score'] = rule_score
            p['ai_score'] = ai_score
            good.append((p, final_score))

    if not good:
        print("ℹ️ 没有高分项目")
        push("📊 本次多链扫描完成，未发现高分项目")
        print("###GOOD_PROJECTS_START###")
        print(json.dumps([]))
        print("###GOOD_PROJECTS_END###")
        return

    push(format_project_message(good))
    print(f"✅ 完成，推送了 {len(good)} 个项目")

    # 输出 JSON 供 main.py 收集每日汇总
    print("###GOOD_PROJECTS_START###")
    out_data = [{
        "name": p[0].get('name', 'Unknown'),
        "score": p[1],
        "rule_score": p[0].get('rule_score', 0),
        "ai_score": p[0].get('ai_score', 'N/A'),
        "tvl": p[0].get('tvl', 0),
        "chains": p[0].get('chains', []),
        "url": p[0].get('url', '')
    } for p in good]
    print(json.dumps(out_data))
    print("###GOOD_PROJECTS_END###")

if __name__ == "__main__":
    main()