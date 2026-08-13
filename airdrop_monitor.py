import os
import requests
import json
from datetime import datetime, timedelta
from openai import OpenAI

# ---- 从环境变量读取 ----
PUSH_URL = os.getenv("PUSH_URL")
PUSH_SECRET = os.getenv("PUSH_SECRET")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")  # 新增：DeepSeek API Key
# -------------------------

# ---- 初始化 DeepSeek 客户端 ----
deepseek_client = None
if DEEPSEEK_API_KEY:
    deepseek_client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )
    print("✅ DeepSeek AI 已初始化")
else:
    print("⚠️ 未设置 DEEPSEEK_API_KEY，AI 筛选功能将禁用")

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

def ai_score_project(project):
    """
    使用 DeepSeek AI 对项目进行评分（0-100分）
    返回：评分整数，如果失败返回 None
    """
    if not deepseek_client:
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
        response = deepseek_client.chat.completions.create(
            model="deepseek-v4-flash",  # 使用 flash 版本，更快更便宜[reference:12]
            messages=[
                {"role": "system", "content": "你是一个专业的 Web3 空投分析师，只返回数字评分。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=10
        )
        score_text = response.choices[0].message.content.strip()
        # 提取数字
        import re
        numbers = re.findall(r'\d+', score_text)
        if numbers:
            score = int(numbers[0])
            return min(100, max(0, score))  # 限制在 0-100 之间
        return None
    except Exception as e:
        print(f"⚠️ AI 评分失败 ({name}): {e}")
        return None

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

def format_project_message(projects):
    """格式化项目推送消息"""
    lines = ["🚀 **空投情报**", f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
    for p, s in projects[:5]:
        name = p.get('name', 'Unknown')
        tvl = p.get('tvl', 0)
        chains = ', '.join(p.get('chains', [])[:3])
        url = p.get('url', '')
        ai_score = p.get('ai_score', 'N/A')
        lines.append(f"**{name}** 评分: {s}/100 | AI: {ai_score}/100")
        lines.append(f"  TVL: ${tvl:,.0f} | 链: {chains}")
        if url:
            lines.append(f"  🔗 {url}")
        lines.append("")
    return "\n".join(lines)

def main():
    print(f"🔄 开始扫描 {datetime.now()}")

    projects = fetch_new_projects()
    if not projects:
        print("ℹ️ 未发现新项目")
        print("###GOOD_PROJECTS_START###")
        print(json.dumps([]))
        print("###GOOD_PROJECTS_END###")
        return

    print(f"📊 发现 {len(projects)} 个新项目，开始评分...")

    good = []
    for p in projects[:30]:
        # 1. 规则评分
        rule_score = score_project(p)

        # 2. AI 评分（如果启用）
        ai_score = None
        if deepseek_client and rule_score >= 40:  # 只有规则评分及格才调用 AI，节省 token
            ai_score = ai_score_project(p)
            if ai_score is not None:
                print(f"  🤖 {p.get('name')}: 规则={rule_score}, AI={ai_score}")
            else:
                print(f"  ⚠️ {p.get('name')}: AI 评分失败，使用规则评分")
                ai_score = rule_score  # AI 失败时回退到规则评分
        else:
            ai_score = rule_score  # AI 未启用时使用规则评分

        # 3. 综合评分：规则评分和 AI 评分的平均值
        final_score = int((rule_score + ai_score) / 2) if ai_score is not None else rule_score

        # 4. 判断是否推送（综合评分 >= 60）
        if final_score >= 60:
            p['ai_score'] = ai_score
            p['rule_score'] = rule_score
            good.append((p, final_score))

    if not good:
        print("ℹ️ 没有高分项目")
        push("📊 本次扫描完成，未发现高分项目")
        print("###GOOD_PROJECTS_START###")
        print(json.dumps([]))
        print("###GOOD_PROJECTS_END###")
        return

    # 推送即时消息
    push(format_project_message(good))
    print(f"✅ 完成，推送了 {len(good)} 个项目")

    # 输出 JSON 供 main.py 收集（用于每日汇总）
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