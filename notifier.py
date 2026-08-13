import aiohttp
import logging
from models import AirdropProject
from analyzer import AnalysisEngine
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("AirdropBot")


class Notifier:
    """Telegram推送通知器"""

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.tg_api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
        self.chat_id = TELEGRAM_CHAT_ID
        self.engine = AnalysisEngine()

    async def send_message(self, text: str):
        """发送Telegram消息（自动处理超长文本）"""
        if not self.chat_id or not TELEGRAM_BOT_TOKEN:
            logger.warning("[Telegram] 未配置Token或ChatID，跳过推送")
            return

        # Telegram单条消息限制4096字符
        if len(text) > 4000:
            text = text[:3997] + "..."

        url = f"{self.tg_api}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            async with self.session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    logger.info("[Telegram] 推送成功")
                elif resp.status == 429:
                    logger.warning("[Telegram] 触发限流，稍后重试")
                else:
                    body = await resp.text()
                    logger.error(
                        f"[Telegram] 推送失败 {resp.status}: {body}"
                    )
        except Exception as e:
            logger.error(f"[Telegram] 推送异常: {e}")

    async def alert_new_airdrop(self, project: AirdropProject):
        """推送新空投发现"""
        priority = self.engine.get_priority(project)

        msg = (
            f"{priority.value} <b>新空投信号</b>\n\n"
            f"📌 项目: <b>{project.name}</b>\n"
            f"⛓️ 链: {project.chain or '多链'}\n"
            f"📊 TVL: ${project.tvl:,.0f}\n"
            f"💰 融资: ${project.funding:,.0f}\n"
            f"⭐ 评分: {project.score:.0f}/100\n"
            f"📋 状态: {project.status.value}\n"
            f"🏷️ 分类: {project.category}\n"
            f"🔗 来源: {project.source}\n"
            f"🕐 更新: {project.last_updated.strftime('%Y-%m-%d %H:%M UTC')}\n"
        )
        if project.deadline:
            hours_left = (
                project.deadline - __import__('datetime').datetime.now(
                    __import__('datetime').timezone.utc
                )
            ).total_seconds() / 3600
            msg += (
                f"⏰ 截止: {project.deadline.strftime('%Y-%m-%d')} "
                f"(剩余{hours_left:.1f}小时)\n"
            )

        await self.send_message(msg)

    async def alert_tvl_anomaly(
        self, name: str, old_tvl: float, new_tvl: float
    ):
        """推送TVL异常信号"""
        change_pct = (
            (new_tvl - old_tvl) / max(old_tvl, 1) * 100
        )
        msg = (
            f"📈 <b>TVL异常信号</b>\n\n"
            f"项目: {name}\n"
            f"TVL: ${old_tvl:,.0f} → ${new_tvl:,.0f}\n"
            f"涨幅: {change_pct:.1f}%\n"
            f"💡 可能预示空投即将到来"
        )
        await self.send_message(msg)

    async def alert_deadline(self, project: AirdropProject, hours: float):
        """截止时间预警"""
        msg = (
            f"⚠️ <b>截止时间预警</b>\n\n"
            f"📌 {project.name}\n"
            f"⏰ 距离截止仅剩 <b>{hours:.1f} 小时</b>\n"
            f"💡 请立即完成交互/领取操作！"
        )
        await self.send_message(msg)

    async def send_daily_summary(self, projects: list, stats: dict):
        """每日汇总报告"""
        msg = (
            f"📋 <b>每日空投情报汇总</b>\n"
            f"🕐 {stats.get('time', '')}\n\n"
            f"📊 监控项目总数: {stats.get('total', 0)}\n"
            f"🆕 本轮新增: {stats.get('new', 0)}\n"
            f"⚠️ TVL异常: {stats.get('anomalies', 0)}\n"
            f"⏰ 即将截止: {stats.get('expiring', 0)}\n\n"
        )

        if projects:
            msg += "<b>🔥 高分项目TOP5:</b>\n"
            sorted_p = sorted(
                projects, key=lambda x: x.score, reverse=True
            )[:5]
            for i, p in enumerate(sorted_p, 1):
                msg += (
                    f"{i}. {p.name} | "
                    f"⭐{p.score:.0f} | "
                    f"TVL ${p.tvl:,.0f}\n"
                )

        await self.send_message(msg)