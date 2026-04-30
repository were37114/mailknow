"""Cold start strategy for scene recommendations.

V5.2 spec:
4 stages:
- Day1: No data, show onboarding + manual triggers
- Post-import: Data available, show basic scenes (approval, report)
- Week1: 1 week data, personalized recommendations
- Month1: Full personalization with feedback flywheel

This module provides stage-specific recommendation strategies.
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timezone

from .recommender import (
    SceneType, SceneCard, ColdStartStage, 
    RecommendationBoundary,
)

logger = logging.getLogger(__name__)


@dataclass
class StageStrategy:
    """Recommendation strategy for a cold start stage."""
    stage: ColdStartStage
    enabled_scenes: List[SceneType]
    max_daily_cards: int
    confidence_threshold: float
    description: str


# Stage strategies
STAGE_STRATEGIES: Dict[ColdStartStage, StageStrategy] = {
    ColdStartStage.DAY_1: StageStrategy(
        stage=ColdStartStage.DAY_1,
        enabled_scenes=[SceneType.WEEKLY_REPORT],  # Only show manual-trigger scenes
        max_daily_cards=2,
        confidence_threshold=0.9,  # Only very confident recommendations
        description="首次使用，展示入门引导和手动触发场景",
    ),
    ColdStartStage.POST_IMPORT: StageStrategy(
        stage=ColdStartStage.POST_IMPORT,
        enabled_scenes=[
            SceneType.APPROVAL_REMINDER,
            SceneType.WEEKLY_REPORT,
            SceneType.QUOTE_AGGREGATION,
        ],
        max_daily_cards=3,
        confidence_threshold=0.8,
        description="数据已导入，展示基础场景推荐",
    ),
    ColdStartStage.WEEK_1: StageStrategy(
        stage=ColdStartStage.WEEK_1,
        enabled_scenes=[
            SceneType.APPROVAL_REMINDER,
            SceneType.WEEKLY_REPORT,
            SceneType.QUOTE_AGGREGATION,
            SceneType.ANOMALY_DETECTION,
        ],
        max_daily_cards=5,
        confidence_threshold=0.7,
        description="1周数据积累，个性化推荐开始生效",
    ),
    ColdStartStage.MONTH_1: StageStrategy(
        stage=ColdStartStage.MONTH_1,
        enabled_scenes=list(SceneType),  # All scenes
        max_daily_cards=5,
        confidence_threshold=0.6,
        description="1月数据积累，完整个性化推荐+反馈飞轮",
    ),
}


class ColdStartManager:
    """Manage cold start stage transitions and strategies.
    
    Features:
    - Track stage progression based on usage history
    - Apply stage-specific recommendation strategies
    - Smooth transitions between stages
    """
    
    def __init__(self):
        self._first_use: Optional[str] = None
        self._first_import: Optional[str] = None
        self._email_count = 0
        self._feedback_count = 0
    
    def set_first_use(self, date: Optional[str] = None):
        """Record first use date."""
        self._first_use = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    def set_first_import(self, date: Optional[str] = None, email_count: int = 0):
        """Record first import."""
        self._first_import = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._email_count = email_count
    
    def record_email_count(self, count: int):
        """Update email count."""
        self._email_count = count
    
    def record_feedback(self):
        """Record a feedback event."""
        self._feedback_count += 1
    
    def get_stage(self) -> ColdStartStage:
        """Determine current cold start stage."""
        now = datetime.now(timezone.utc)
        
        if not self._first_use:
            return ColdStartStage.DAY_1
        
        try:
            first_use_dt = datetime.fromisoformat(self._first_use + "T00:00:00+00:00")
            days = (now - first_use_dt).days
        except ValueError:
            days = 0
        
        if not self._first_import:
            return ColdStartStage.DAY_1
        
        if days < 7:
            return ColdStartStage.POST_IMPORT
        elif days < 30:
            return ColdStartStage.WEEK_1
        else:
            return ColdStartStage.MONTH_1
    
    def get_strategy(self) -> StageStrategy:
        """Get current stage's strategy."""
        stage = self.get_stage()
        return STAGE_STRATEGIES[stage]
    
    def is_scene_enabled(self, scene_type: SceneType) -> bool:
        """Check if a scene type is enabled for current stage."""
        strategy = self.get_strategy()
        return scene_type in strategy.enabled_scenes
    
    def get_max_daily_cards(self) -> int:
        """Get max daily cards for current stage."""
        return self.get_strategy().max_daily_cards
    
    def get_confidence_threshold(self) -> float:
        """Get confidence threshold for current stage."""
        return self.get_strategy().confidence_threshold
    
    def get_stage_info(self) -> Dict[str, Any]:
        """Get full stage info for UI display."""
        stage = self.get_stage()
        strategy = self.get_strategy()
        
        return {
            "stage": stage.value,
            "description": strategy.description,
            "enabled_scenes": [s.value for s in strategy.enabled_scenes],
            "max_daily_cards": strategy.max_daily_cards,
            "confidence_threshold": strategy.confidence_threshold,
            "email_count": self._email_count,
            "feedback_count": self._feedback_count,
            "first_use": self._first_use,
            "first_import": self._first_import,
        }
