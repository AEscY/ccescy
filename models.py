from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from enum import Enum


class AirdropStatus(Enum):
    UPCOMING = "upcoming"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    ENDED = "ended"
    CLAIMABLE = "claimable"


class Priority(Enum):
    CRITICAL = "🚨 紧急"
    HIGH = "🔴 高"
    MEDIUM = "🟡 中"
    LOW = "🟢 低"


@dataclass
class AirdropProject:
    name: str
    status: AirdropStatus
    chain: str = ""
    tvl: float = 0.0
    funding: float = 0.0
    investors: list = field(default_factory=list)
    deadline: Optional[datetime] = None
    difficulty: str = ""
    category: str = ""
    source: str = ""
    url: str = ""
    score: float = 0.0
    last_updated: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def calculate_score(self) -> float:
        """
        综合评分模型（满分100）
        - 融资背景: 40分
        - TVL规模: 30分
        - 时间紧迫度: 30分
        """
        score = 0.0

        # 融资评分 (0-40)
        if self.funding >= 50_000_000:
            score += 40
        elif self.funding >= 10_000_000:
            score += 30
        elif self.funding >= 1_000_000:
            score += 20
        else:
            score += 10

        # TVL评分 (0-30)
        if self.tvl >= 100_000_000:
            score += 30
        elif self.tvl >= 10_000_000:
            score += 20
        elif self.tvl >= 1_000_000:
            score += 10

        # 时间紧迫度 (0-30)
        if self.deadline:
            hours_left = (
                self.deadline - datetime.now(timezone.utc)
            ).total_seconds() / 3600
            if hours_left <= 48:
                score += 30
            elif hours_left <= 168:
                score += 20
            elif hours_left <= 720:
                score += 10

        self.score = score
        return score

    def get_priority(self) -> Priority:
        if not self.deadline:
            return Priority.LOW
        hours_left = (
            self.deadline - datetime.now(timezone.utc)
        ).total_seconds() / 3600
        if hours_left <= 48:
            return Priority.CRITICAL
        elif hours_left <= 168:
            return Priority.HIGH
        elif hours_left <= 720:
            return Priority.MEDIUM
        return Priority.LOW