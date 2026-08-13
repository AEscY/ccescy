import aiohttp
import logging
from models import AirdropProject, AirdropStatus

logger = logging.getLogger("AirdropBot")

# DefiLlama 免费API（无需API Key，无速率限制）
DEFILLAMA_BASE = "https://api.llama.fi"
DEFILLAMA_AIRDROPS = "https://api.llama.fi/tokenProtocols/airdrop"
DEFILLAMA_YIELDS = "https://yields.llama.fi/pools"


class DataCollector:
    """多数据源采集器"""

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def fetch_tokenless_protocols(self) -> list[AirdropProject]:
        """
        从DefiLlama拉取所有无代币协议（潜在空投目标）
        截至2026年8月，DefiLlama追踪了3500+个无代币协议
        """
        projects = []
        try:
            async with self.session.get(
                DEFILLAMA_AIRDROPS,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data:
                        p = AirdropProject(
                            name=item.get("name", "Unknown"),
                            status=AirdropStatus.UPCOMING,
                            tvl=float(item.get("tvl", 0) or 0),
                            chain=item.get("chain", ""),
                            category=item.get("category", ""),
                            source="DefiLlama-Tokenless",
                        )
                        p.calculate_score()
                        projects.append(p)
                    logger.info(
                        f"[DefiLlama] 拉取到 {len(projects)} 个无代币协议"
                    )
        except Exception as e:
            logger.error(f"[DefiLlama] 拉取失败: {e}")
        return projects

    async def fetch_protocol_tvl(self, slug: str) -> dict:
        """获取指定协议的实时TVL数据"""
        url = f"{DEFILLAMA_BASE}/protocol/{slug}"
        try:
            async with self.session.get(
                url, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.error(f"[DefiLlama] TVL查询失败 {slug}: {e}")
        return {}

    async def fetch_chains_overview(self) -> dict:
        """获取所有链的TVL概览，识别新兴生态"""
        url = f"{DEFILLAMA_BASE}/chains"
        try:
            async with self.session.get(
                url, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        c["name"]: c.get("tvl", 0) for c in data
                    }
        except Exception as e:
            logger.error(f"[DefiLlama] 链数据拉取失败: {e}")
        return {}

    async def fetch_hot_yields(self, chain: str = None) -> list:
        """获取高收益池，识别farming机会"""
        try:
            async with self.session.get(
                DEFILLAMA_YIELDS,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pools = data.get("data", [])
                    if chain:
                        pools = [
                            p for p in pools
                            if p.get("chain", "").lower() == chain.lower()
                        ]
                    hot = [
                        p for p in pools
                        if p.get("tvlUsd", 0) > 1_000_000
                        and p.get("apy", 0) > 5
                    ]
                    return sorted(
                        hot, key=lambda x: x.get("apy", 0), reverse=True
                    )[:50]
        except Exception as e:
            logger.error(f"[DefiLlama] 收益率数据拉取失败: {e}")
        return []