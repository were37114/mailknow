"""Scene recommendation engine V1.

V5.2 spec:
- Scoring algorithm + feedback flywheel
- Cold start 4 stages: Day1 → Post-import → Week1 → Month1
- P0 scenes: approval reminder, weekly report, quote aggregation
- Recommendation boundary: ≤5 cards/day + 👎7-day cooldown + silent hours
- Feedback: 👍+0.1 history / 👎-0.2+7-day cooldown / 🔄demote+float
"""

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class SceneType(str, Enum):
    """Scene types for recommendation."""
    APPROVAL_REMINDER = "approval_reminder"
    WEEKLY_REPORT = "weekly_report"
    QUOTE_AGGREGATION = "quote_aggregation"
    ANOMALY_DETECTION = "anomaly_detection"  # V2
    ENTITY_SUMMARY = "entity_summary"        # V2


class FeedbackType(str, Enum):
    """User feedback types."""
    THUMBS_UP = "thumbs_up"     # 👍
    THUMBS_DOWN = "thumbs_down" # 👎
    REFRESH = "refresh"         # 🔄


class ColdStartStage(str, Enum):
    """Cold start stages."""
    DAY_1 = "day_1"                # First day: no data
    POST_IMPORT = "post_import"    # After first import
    WEEK_1 = "week_1"             # After 1 week of usage
    MONTH_1 = "month_1"           # After 1 month: full personalization


@dataclass
class SceneCard:
    """A recommendation card shown to user."""
    card_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    scene_type: SceneType = SceneType.APPROVAL_REMINDER
    title: str = ""
    description: str = ""
    confidence: float = 0.0
    priority: int = 5  # 0=highest, 5=lowest

    # Source data
    source_ids: List[str] = field(default_factory=list)
    action_label: str = ""     # "审批" / "生成周报" / etc.
    action_data: Dict[str, Any] = field(default_factory=dict)

    # Feedback
    feedback: Optional[FeedbackType] = None
    feedback_at: Optional[str] = None

    # Timing
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    shown_at: Optional[str] = None
    dismissed: bool = False

    @property
    def is_interacted(self) -> bool:
        """Whether user has interacted with this card."""
        return self.feedback is not None


@dataclass
class FeedbackRecord:
    """A feedback record for the flywheel."""
    card_id: str
    scene_type: SceneType
    feedback: FeedbackType
    timestamp: str
    # Adjusted score delta
    score_delta: float = 0.0


@dataclass
class RecommendationBoundary:
    """Boundary controls for recommendations.

    V5.2 spec:
    - ≤5 cards per day
    - 👎 7-day cooldown
    - Silent hours (22:00-08:00)
    - Approval only high confidence push
    """
    max_daily_cards: int = 5
    thumbs_down_cooldown_days: int = 7
    silent_hours_start: int = 22  # 22:00
    silent_hours_end: int = 8     # 08:00
    approval_push_min_confidence: float = 0.85  # Only push high-confidence approvals


class SceneRecommender:
    """Scene recommendation engine with feedback flywheel.

    Features:
    - Scoring algorithm with scene weights
    - Cold start strategy (4 stages)
    - Feedback flywheel (👍+0.1 / 👎-0.2+cooldown / 🔄demote)
    - Recommendation boundary controls
    """

    # Base scores for each scene type
    BASE_SCORES: Dict[SceneType, float] = {
        SceneType.APPROVAL_REMINDER: 0.9,
        SceneType.WEEKLY_REPORT: 0.7,
        SceneType.QUOTE_AGGREGATION: 0.6,
        SceneType.ANOMALY_DETECTION: 0.5,
        SceneType.ENTITY_SUMMARY: 0.4,
    }

    def __init__(
        self,
        boundary: Optional[RecommendationBoundary] = None,
    ):
        """Initialize recommender.

        Args:
            boundary: Recommendation boundary controls
        """
        self.boundary = boundary or RecommendationBoundary()

        # Scene weight adjustments (from feedback flywheel)
        self._scene_weights: Dict[SceneType, float] = {
            st: 1.0 for st in SceneType
        }

        # Feedback history
        self._feedback_history: List[FeedbackRecord] = []

        # Cooldown tracking: {scene_type: cooldown_until_iso}
        self._cooldowns: Dict[SceneType, str] = {}

        # Daily card count: {date_str: count}
        self._daily_cards: Dict[str, int] = defaultdict(int)

        # Cold start tracking
        self._first_use_date: Optional[str] = None
        self._first_import_date: Optional[str] = None

        # Pending cards
        self._cards: Dict[str, SceneCard] = {}

    def set_first_use(self, date: Optional[str] = None):
        """Record first use date."""
        self._first_use_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def set_first_import(self, date: Optional[str] = None):
        """Record first import date."""
        self._first_import_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def get_cold_start_stage(self) -> ColdStartStage:
        """Determine current cold start stage.

        Stage progression:
        1. Day1: No data yet, show onboarding tips
        2. Post-import: Data imported, show basic recommendations
        3. Week1: 1 week of data, personalized recommendations
        4. Month1: Full personalization with feedback
        """
        now = datetime.now(timezone.utc)

        if not self._first_use_date:
            return ColdStartStage.DAY_1

        try:
            first_use = datetime.fromisoformat(self._first_use_date.replace("Z", "+00:00"))
            if first_use.tzinfo is None:
                first_use = first_use.replace(tzinfo=timezone.utc)
            days_since = (now - first_use).days
        except ValueError:
            days_since = 0

        if not self._first_import_date:
            return ColdStartStage.DAY_1

        if days_since < 7:
            return ColdStartStage.POST_IMPORT
        elif days_since < 30:
            return ColdStartStage.WEEK_1
        else:
            return ColdStartStage.MONTH_1

    def recommend(
        self,
        context: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> List[SceneCard]:
        """Generate recommendations based on current context.

        Args:
            context: Current context dict with keys:
                - pending_approvals: List of pending approval cards
                - is_friday: Whether it's Friday
                - recent_quotes: Recent quote/price emails
                - anomalies: Detected anomalies
            now: Current time (for testing)

        Returns:
            List of recommended scene cards (respecting boundary)
        """
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # Check silent hours
        if self._is_silent_hours(now):
            logger.debug("Silent hours, no recommendations")
            return []

        # Check daily limit
        today = now.strftime("%Y-%m-%d")
        if self._daily_cards[today] >= self.boundary.max_daily_cards:
            logger.debug("Daily card limit reached")
            return []

        stage = self.get_cold_start_stage()
        candidates = []

        # Scene: Approval reminder
        pending_approvals = context.get("pending_approvals", [])
        if pending_approvals:
            high_conf = [a for a in pending_approvals if a.get("confidence", 0) >= self.boundary.approval_push_min_confidence]
            if high_conf or stage in (ColdStartStage.WEEK_1, ColdStartStage.MONTH_1):
                card = self._create_approval_card(
                    pending_approvals=high_conf if high_conf else pending_approvals[:3],
                    stage=stage,
                )
                if card:
                    candidates.append(card)

        # Scene: Weekly report
        is_friday = context.get("is_friday", False)
        if is_friday and now.hour >= 14:  # After 14:00 on Friday
            card = self._create_weekly_report_card(stage=stage)
            if card:
                candidates.append(card)

        # Scene: Quote aggregation
        recent_quotes = context.get("recent_quotes", [])
        if recent_quotes and stage in (ColdStartStage.POST_IMPORT, ColdStartStage.WEEK_1, ColdStartStage.MONTH_1):
            card = self._create_quote_card(recent_quotes, stage=stage)
            if card:
                candidates.append(card)

        # Score and rank candidates
        scored = [(card, self._score_card(card, stage)) for card in candidates]
        scored.sort(key=lambda x: -x[1])

        # Apply boundary (daily limit)
        remaining = self.boundary.max_daily_cards - self._daily_cards[today]
        selected = [card for card, score in scored[:remaining]]

        # Track daily count
        self._daily_cards[today] += len(selected)

        return selected

    def record_feedback(
        self,
        card_id: str,
        feedback: FeedbackType,
    ) -> Optional[SceneCard]:
        """Record user feedback on a recommendation card.

        V5.2 feedback flywheel:
        - 👍 +0.1 to scene type history weight
        - 👎 -0.2 to scene type weight + 7-day cooldown
        - 🔄 Demote and float (move to end of list)
        """
        card = self._cards.get(card_id)
        if not card:
            logger.warning(f"Card not found for feedback: {card_id}")
            return None

        card.feedback = feedback
        card.feedback_at = datetime.now(timezone.utc).isoformat()

        now = datetime.now(timezone.utc)

        if feedback == FeedbackType.THUMBS_UP:
            # 👍 +0.1 to scene type weight
            self._scene_weights[card.scene_type] = min(
                self._scene_weights.get(card.scene_type, 1.0) + 0.1,
                2.0  # Cap at 2.0
            )
            score_delta = 0.1

        elif feedback == FeedbackType.THUMBS_DOWN:
            # 👎 -0.2 + 7-day cooldown
            self._scene_weights[card.scene_type] = max(
                self._scene_weights.get(card.scene_type, 1.0) - 0.2,
                0.1  # Floor at 0.1
            )
            cooldown_until = (now + timedelta(days=self.boundary.thumbs_down_cooldown_days)).isoformat()
            self._cooldowns[card.scene_type] = cooldown_until
            score_delta = -0.2

        elif feedback == FeedbackType.REFRESH:
            # 🔄 Demote: lower priority, will float up next time
            card.priority = min(card.priority + 1, 10)
            score_delta = 0.0
        else:
            score_delta = 0.0

        # Record feedback
        self._feedback_history.append(FeedbackRecord(
            card_id=card_id,
            scene_type=card.scene_type,
            feedback=feedback,
            timestamp=now.isoformat(),
            score_delta=score_delta,
        ))

        logger.info(f"Feedback {feedback.value} on card {card_id} (scene={card.scene_type.value}, delta={score_delta})")
        return card

    def dismiss_card(self, card_id: str) -> bool:
        """Dismiss a recommendation card."""
        card = self._cards.get(card_id)
        if card:
            card.dismissed = True
            return True
        return False

    def get_active_cards(self) -> List[SceneCard]:
        """Get all non-dismissed cards."""
        return [c for c in self._cards.values() if not c.dismissed]

    def _score_card(self, card: SceneCard, stage: ColdStartStage) -> float:
        """Score a candidate card.

        Score = base_score * scene_weight * stage_multiplier * confidence
        """
        base = self.BASE_SCORES.get(card.scene_type, 0.5)
        weight = self._scene_weights.get(card.scene_type, 1.0)

        # Stage multipliers
        stage_multipliers = {
            ColdStartStage.DAY_1: 0.5,       # Low confidence, conservative
            ColdStartStage.POST_IMPORT: 0.7,
            ColdStartStage.WEEK_1: 0.9,
            ColdStartStage.MONTH_1: 1.0,      # Full confidence
        }
        stage_mult = stage_multipliers.get(stage, 0.5)

        # Check cooldown
        if card.scene_type in self._cooldowns:
            cooldown_until = self._cooldowns[card.scene_type]
            try:
                cooldown_dt = datetime.fromisoformat(cooldown_until.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < cooldown_dt:
                    return 0.0  # In cooldown, don't recommend
                else:
                    del self._cooldowns[card.scene_type]  # Cooldown expired
            except ValueError:
                del self._cooldowns[card.scene_type]

        return base * weight * stage_mult * card.confidence

    def _create_approval_card(
        self,
        pending_approvals: List[Dict[str, Any]],
        stage: ColdStartStage,
    ) -> Optional[SceneCard]:
        """Create approval reminder card."""
        if not pending_approvals:
            return None

        count = len(pending_approvals)
        first = pending_approvals[0]

        if count == 1:
            title = f"📋 审批提醒：{first.get('subject', '待审批')}"
            description = f"来自 {first.get('requester', '未知')} 的审批请求"
        else:
            title = f"📋 {count}项审批待处理"
            subjects = [a.get('subject', '') for a in pending_approvals[:3]]
            description = "、".join(subjects)
            if count > 3:
                description += f" 等{count}项"

        # Determine confidence
        max_conf = max(a.get("confidence", 0.5) for a in pending_approvals)

        card = SceneCard(
            scene_type=SceneType.APPROVAL_REMINDER,
            title=title,
            description=description,
            confidence=min(max_conf, 0.95),
            priority=0,  # Highest priority
            source_ids=[a.get("card_id", a.get("email_id", "")) for a in pending_approvals],
            action_label="去审批",
            action_data={"approval_ids": [a.get("card_id", "") for a in pending_approvals]},
        )

        self._cards[card.card_id] = card
        return card

    def _create_weekly_report_card(self, stage: ColdStartStage) -> Optional[SceneCard]:
        """Create weekly report generation card."""
        card = SceneCard(
            scene_type=SceneType.WEEKLY_REPORT,
            title="📝 生成本周周报",
            description="基于本周邮件数据，一键生成工作周报",
            confidence=0.8,
            priority=2,
            action_label="生成周报",
            action_data={"trigger": "friday_reminder"},
        )

        self._cards[card.card_id] = card
        return card

    def _create_quote_card(
        self,
        recent_quotes: List[Dict[str, Any]],
        stage: ColdStartStage,
    ) -> Optional[SceneCard]:
        """Create quote aggregation card."""
        if not recent_quotes:
            return None

        count = len(recent_quotes)
        card = SceneCard(
            scene_type=SceneType.QUOTE_AGGREGATION,
            title=f"💰 {count}份报价待汇总",
            description=f"收到 {count} 份报价邮件，可一键汇总对比",
            confidence=0.7,
            priority=3,
            source_ids=[q.get("email_id", "") for q in recent_quotes[:5]],
            action_label="查看报价",
            action_data={"quote_ids": [q.get("email_id", "") for q in recent_quotes]},
        )

        self._cards[card.card_id] = card
        return card

    def _is_silent_hours(self, now: datetime) -> bool:
        """Check if current time is in silent hours."""
        hour = now.hour
        start = self.boundary.silent_hours_start
        end = self.boundary.silent_hours_end

        if start > end:
            # Crosses midnight (e.g., 22:00-08:00)
            return hour >= start or hour < end
        else:
            return start <= hour < end

    def get_stats(self) -> Dict[str, Any]:
        """Get recommender statistics."""
        return {
            "cold_start_stage": self.get_cold_start_stage().value,
            "scene_weights": {st.value: w for st, w in self._scene_weights.items()},
            "feedback_count": len(self._feedback_history),
            "active_cards": len(self.get_active_cards()),
            "cooldowns": {st.value: until for st, until in self._cooldowns.items()},
            "daily_cards": dict(self._daily_cards),
        }
