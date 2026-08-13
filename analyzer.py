import logging
from models import AirdropProject, Priority
from config import TOP_VCS

logger = logging.getLogger("AirdropBot")


class AnalysisEngine:
    """项目评分与异常检测引擎"""

    def score_project(self, project: AirdropProject) -> AirdropProject:
        """增强评分：加入VC背景加分"""
        base_score = project.calculate_score()

        vc_bonus = 0
        for investor in project.investors:
            if any(
                top_vc.lower() in investor.lower()
                for top_vc in TOP_VCS
            ):
                vc_bonus = min(20, vc_bonus + 10)

        project.score = min(100, base_score + vc_bonus)
        return project

    def detect_tvl_anomaly(
        self, current_tvl: float, historical_avg: float,
        threshold: float = 0.5
    ) -> bool:
        """TVL暴涨检测"""
        if historical_avg == 0:
            return False
        change_rate = (current_tvl - historical_avg) / historical_avg
        return change_rate > threshold

    def get_priority(self, project: AirdropProject) -> Priority:
        return project.get_priority()