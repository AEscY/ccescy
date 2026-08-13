import asyncio
import aiohttp
import logging
from datetime import datetime, timezone
from collector import DataCollector
from analyzer import AnalysisEngine
from notifier import Notifier
from config import (
    SCAN_INTERVAL_MIN, MIN_SCORE_ALERT,
    TVL_ANOMALY_THRESHOLD, FOCUS_CHAINS
)

logger = logging.getLogger("AirdropBot")


class AirdropScheduler:
    """24小时主调度器"""

    def __init__(self):
        self.projects: dict[str, dict] = {}  # name -> 项目快照
        self.session: aiohttp.ClientSession = None
        self.collector: DataCollector = None
        self.notifier: Notifier = None
        self.engine = AnalysisEngine()
        self.cycle_count = 0
        self.total_tvl_history: dict[str, list] = {}

    async def start(self):
        """启动机器人"""
        logger.info("=" * 50)
        logger.info("🚀 Airdrop Bot 启动中...")
        logger.info(f"   扫描间隔: {SCAN_INTERVAL_MIN} 分钟")
        logger.info(f"   推送阈值: 评分 >= {MIN_SCORE_ALERT}")
        logger.info(f"   关注链: {', '.join(FOCUS_CHAINS)}")
        logger.info("=" * 50)

        self.session = aiohttp.ClientSession(
            headers={"User-Agent": "AirdropBot/1.0"}
        )
        self.collector = DataCollector(self.session)
        self.notifier = Notifier(self.session)

        await self.notifier.send_message(
            "🤖 <b>Airdrop Bot 已上线</b>\n"
            f"⏱️ 每{SCAN_INTERVAL_MIN}分钟扫描一次\n"
            f"🎯 评分≥{MIN_SCORE_ALERT}自动推送"
        )

        try:
            while True:
                await self._scan_cycle()
                self.cycle_count += 1
                logger.info(
                    f"[调度] 第{self.cycle_count}轮完成，"
                    f"下次扫描: {SCAN_INTERVAL_MIN}分钟后"
                )
                await asyncio.sleep(SCAN_INTERVAL_MIN * 60)
        except asyncio.CancelledError:
            logger.info("[调度] 收到停止信号")
        finally:
            await self.session.close()

    async def _scan_cycle(self):
        """单次扫描周期"""
        cycle_start = datetime.now(timezone.utc)
        logger.info("[扫描] 开始新一轮数据采集...")

        new_count = 0
        anomaly_count = 0
        expiring_count = 0

        # ---- 任务1: 拉取无代币协议列表 ----
        tokenless = await self.collector.fetch_tokenless_protocols()
        for p in tokenless:
            if p.name not in self.projects:
                self.projects[p.name] = {
                    "project": p,
                    "first_seen": cycle_start,
                    "tvl_history": [],
                }
                new_count += 1
                if p.score >= MIN_SCORE_ALERT:
                    await self.notifier.alert_new_airdrop(p)

        # ---- 任务2: TVL异常检测（抽样检查TOP项目） ----
        top_projects = sorted(
            [v["project"] for v in self.projects.values()],
            key=lambda x: x.tvl, reverse=True
        )[:20]

        for proj in top_projects:
            slug = proj.name.lower().replace(" ", "-")
            tvl_data = await self.collector.fetch_protocol_tvl(slug)
            if tvl_data and "currentChainTvls" in tvl_data:
                current_tvl = sum(
                    v for v in tvl_data["currentChainTvls"].values()
                    if isinstance(v, (int, float))
                )
                history = self.projects.get(proj.name, {}).get(
                    "tvl_history", []
                )
                if len(history) >= 2:
                    avg_tvl = sum(history) / len(history)
                    if self.engine.detect_tvl_anomaly(
                        current_tvl, avg_tvl, TVL_ANOMALY_THRESHOLD
                    ):
                        await self.notifier.alert_tvl_anomaly(
                            proj.name, avg_tvl, current_tvl
                        )
                        anomaly_count += 1

                # 记录TVL历史
                if proj.name in self.projects:
                    self.projects[proj.name]["tvl_history"].append(
                        current_tvl
                    )
                    # 只保留最近48条（24小时@30min间隔）
                    self.projects[proj.name]["tvl_history"] = (
                        self.projects[proj.name]["tvl_history"][-48:]
                    )

            # 小延迟避免请求过快
            await asyncio.sleep(0.5)

        # ---- 任务3: 截止时间检查 ----
        now = datetime.now(timezone.utc)
        for name, data in self.projects.items():
            proj = data["project"]
            if proj.deadline:
                hours_left = (
                    proj.deadline - now
                ).total_seconds() / 3600
                if 0 < hours_left <= 24:
                    await self.notifier.alert_deadline(
                        proj, hours_left
                    )
                    expiring_count += 1

        # ---- 任务4: 每8轮发一次日报（约4小时一次） ----
        if self.cycle_count > 0 and self.cycle_count % 8 == 0:
            all_projects = [
                v["project"] for v in self.projects.values()
            ]
            stats = {
                "time": cycle_start.strftime("%Y-%m-%d %H:%M UTC"),
                "total": len(self.projects),
                "new": new_count,
                "anomalies": anomaly_count,
                "expiring": expiring_count,
            }
            await self.notifier.send_daily_summary(
                all_projects, stats
            )

        duration = (
            datetime.now(timezone.utc) - cycle_start
        ).total_seconds()
        logger.info(
            f"[扫描] 完成 | 新增: {new_count} | "
            f"异常: {anomaly_count} | "
            f"即将截止: {expiring_count} | "
            f"总计: {len(self.projects)} | "
            f"耗时: {duration:.1f}s"
        )