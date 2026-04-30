"""Enhanced Token Budget Controller V2.

Features over V1:
- Monthly budget tracking in addition to daily
- Auto-degradation when budget exceeded (fallback to pure GBrain mode)
- Persistent usage tracking in SQLite
- Usage visualization data for frontend
- Cost estimation per provider
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class DegradationLevel(str, Enum):
    """Degradation levels when budget is exceeded."""
    NORMAL = "normal"           # Full LLM access
    WARNING = "warning"         # Approaching limit, reduce usage
    DEGRADED = "degraded"       # LLM only for critical tasks
    PURE_GBRAIN = "pure_gbrain" # No LLM at all, pure local


@dataclass
class BudgetConfig:
    """Token budget configuration."""
    # Daily limits
    daily_token_limit: int = 500_000       # 500K tokens/day
    daily_cost_limit: float = 0.50         # $0.50/day
    
    # Monthly limits (for power users: 200 emails/day)
    monthly_token_limit: int = 10_000_000  # 10M tokens/month
    monthly_cost_limit: float = 9.00       # $9/month (V5.2 target)
    
    # Per-request limits
    per_request_token_limit: int = 10_000  # 10K tokens/request
    
    # Warning thresholds
    warning_threshold: float = 0.8         # Warn at 80%
    degradation_threshold: float = 0.95    # Degrade at 95%
    
    # Cost rates (USD per 1M tokens)
    input_cost_per_m: float = 0.15         # GPT-4o-mini input
    output_cost_per_m: float = 0.60        # GPT-4o-mini output


@dataclass
class UsageRecord:
    """A single token usage record."""
    timestamp: str
    tokens_in: int
    tokens_out: int
    cost: float
    provider: str
    task_type: str  # tier4_extract, approval, report, etc.
    degradation: str = "normal"


@dataclass
class UsageSummary:
    """Usage summary for visualization."""
    daily_tokens: int = 0
    daily_cost: float = 0.0
    daily_limit: int = 0
    monthly_tokens: int = 0
    monthly_cost: float = 0.0
    monthly_limit: int = 0
    degradation: DegradationLevel = DegradationLevel.NORMAL
    
    # Per-task breakdown
    by_task: Dict[str, int] = field(default_factory=dict)
    
    @property
    def daily_usage_ratio(self) -> float:
        return self.daily_tokens / self.daily_limit if self.daily_limit > 0 else 0.0
    
    @property
    def monthly_usage_ratio(self) -> float:
        return self.monthly_tokens / self.monthly_limit if self.monthly_limit > 0 else 0.0
    
    @property
    def daily_remaining(self) -> int:
        return max(0, self.daily_limit - self.daily_tokens)
    
    @property
    def monthly_remaining(self) -> int:
        return max(0, self.monthly_limit - self.monthly_tokens)


class TokenBudgetController:
    """Enhanced token budget controller with monthly tracking and degradation.
    
    Usage:
        controller = TokenBudgetController(db_path="/path/to/db")
        controller.start()
        
        # Check before LLM call
        if controller.check(estimated_tokens=5000, task_type="tier4_extract"):
            response = await llm.complete(...)
            controller.record(tokens_in=500, tokens_out=200, cost=0.002, 
                            provider="openai", task_type="tier4_extract")
        else:
            # Degrade to local
            result = local_fallback(...)
    """
    
    USAGE_TABLE = "token_usage"
    
    def __init__(
        self,
        config: Optional[BudgetConfig] = None,
        db_path: Optional[str] = None,
    ):
        """Initialize controller.
        
        Args:
            config: Budget configuration
            db_path: Path to SQLite database for persistence
        """
        self.config = config or BudgetConfig()
        self.db_path = db_path
        
        # In-memory counters for fast access
        self._daily_tokens: int = 0
        self._daily_cost: float = 0.0
        self._monthly_tokens: int = 0
        self._monthly_cost: float = 0.0
        self._current_degradation: DegradationLevel = DegradationLevel.NORMAL
        self._daily_date: str = ""
        self._monthly_date: str = ""
        self._by_task: Dict[str, int] = {}
        
        if db_path:
            self._ensure_table()
            self._load_persistent_state()
    
    def _ensure_table(self):
        """Create usage table if not exists."""
        if not self.db_path:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.USAGE_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    cost REAL DEFAULT 0.0,
                    provider TEXT DEFAULT '',
                    task_type TEXT DEFAULT '',
                    degradation TEXT DEFAULT 'normal'
                )
            """)
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_usage_ts ON {self.USAGE_TABLE}(timestamp)")
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to create usage table: {e}")
    
    def _load_persistent_state(self):
        """Load usage state from database."""
        if not self.db_path:
            return
        
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            month_prefix = today[:7]  # "2026-04"
            
            conn = sqlite3.connect(self.db_path)
            
            # Daily totals
            cursor = conn.execute(
                f"SELECT COALESCE(SUM(tokens_in + tokens_out), 0), COALESCE(SUM(cost), 0.0) "
                f"FROM {self.USAGE_TABLE} WHERE timestamp LIKE ?",
                (f"{today}%",)
            )
            row = cursor.fetchone()
            self._daily_tokens = row[0]
            self._daily_cost = row[1]
            self._daily_date = today
            
            # Monthly totals
            cursor = conn.execute(
                f"SELECT COALESCE(SUM(tokens_in + tokens_out), 0), COALESCE(SUM(cost), 0.0) "
                f"FROM {self.USAGE_TABLE} WHERE timestamp LIKE ?",
                (f"{month_prefix}%",)
            )
            row = cursor.fetchone()
            self._monthly_tokens = row[0]
            self._monthly_cost = row[1]
            self._monthly_date = month_prefix
            
            # By task breakdown
            cursor = conn.execute(
                f"SELECT task_type, COALESCE(SUM(tokens_in + tokens_out), 0) "
                f"FROM {self.USAGE_TABLE} WHERE timestamp LIKE ? GROUP BY task_type",
                (f"{today}%",)
            )
            self._by_task = {row[0]: row[1] for row in cursor.fetchall()}
            
            conn.close()
            
            # Update degradation level
            self._update_degradation()
            
        except Exception as e:
            logger.warning(f"Failed to load persistent state: {e}")
    
    def check(self, estimated_tokens: int, task_type: str = "general") -> bool:
        """Check if request is within budget.
        
        Args:
            estimated_tokens: Estimated tokens for this request
            task_type: Type of task (affects degradation behavior)
            
        Returns:
            True if request is allowed
        """
        self._maybe_reset()
        
        # Per-request limit
        if estimated_tokens > self.config.per_request_token_limit:
            logger.warning(f"Per-request limit exceeded: {estimated_tokens}")
            return False
        
        # Check degradation level
        if self._current_degradation == DegradationLevel.PURE_GBRAIN:
            logger.info("Pure GBrain mode - LLM blocked")
            return False
        
        if self._current_degradation == DegradationLevel.DEGRADED:
            # Only allow critical tasks
            critical_tasks = {"tier4_extract", "approval"}
            if task_type not in critical_tasks:
                logger.info(f"Degraded mode - blocked task: {task_type}")
                return False
        
        # Daily limit
        if self._daily_tokens + estimated_tokens > self.config.daily_token_limit:
            logger.warning(f"Daily token limit exceeded")
            return False
        
        # Monthly limit
        if self._monthly_tokens + estimated_tokens > self.config.monthly_token_limit:
            logger.warning(f"Monthly token limit exceeded")
            return False
        
        return True
    
    def record(
        self,
        tokens_in: int,
        tokens_out: int,
        cost: float = 0.0,
        provider: str = "",
        task_type: str = "general",
    ) -> None:
        """Record token usage.
        
        Args:
            tokens_in: Input tokens used
            tokens_out: Output tokens used
            cost: Actual cost in USD
            provider: LLM provider name
            task_type: Type of task
        """
        self._maybe_reset()
        
        total_tokens = tokens_in + tokens_out
        
        # Update in-memory counters
        self._daily_tokens += total_tokens
        self._daily_cost += cost
        self._monthly_tokens += total_tokens
        self._monthly_cost += cost
        self._by_task[task_type] = self._by_task.get(task_type, 0) + total_tokens
        
        # Persist to database
        if self.db_path:
            self._persist_record(tokens_in, tokens_out, cost, provider, task_type)
        
        # Update degradation
        self._update_degradation()
    
    def get_summary(self) -> UsageSummary:
        """Get current usage summary for visualization."""
        self._maybe_reset()
        
        return UsageSummary(
            daily_tokens=self._daily_tokens,
            daily_cost=self._daily_cost,
            daily_limit=self.config.daily_token_limit,
            monthly_tokens=self._monthly_tokens,
            monthly_cost=self._monthly_cost,
            monthly_limit=self.config.monthly_token_limit,
            degradation=self._current_degradation,
            by_task=dict(self._by_task),
        )
    
    @property
    def degradation_level(self) -> DegradationLevel:
        """Current degradation level."""
        self._maybe_reset()
        return self._current_degradation
    
    def estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Estimate cost for a request.
        
        Args:
            tokens_in: Input tokens
            tokens_out: Output tokens
            
        Returns:
            Estimated cost in USD
        """
        return (tokens_in * self.config.input_cost_per_m + 
                tokens_out * self.config.output_cost_per_m) / 1_000_000
    
    def _update_degradation(self):
        """Update degradation level based on current usage."""
        daily_ratio = self._daily_tokens / self.config.daily_token_limit if self.config.daily_token_limit > 0 else 0
        monthly_ratio = self._monthly_tokens / self.config.monthly_token_limit if self.config.monthly_token_limit > 0 else 0
        
        max_ratio = max(daily_ratio, monthly_ratio)
        
        if max_ratio >= 1.0:
            self._current_degradation = DegradationLevel.PURE_GBRAIN
        elif max_ratio >= self.config.degradation_threshold:
            self._current_degradation = DegradationLevel.DEGRADED
        elif max_ratio >= self.config.warning_threshold:
            self._current_degradation = DegradationLevel.WARNING
        else:
            self._current_degradation = DegradationLevel.NORMAL
    
    def _maybe_reset(self):
        """Reset daily/monthly counters if new period."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        if today != self._daily_date:
            self._daily_tokens = 0
            self._daily_cost = 0.0
            self._by_task = {}
            self._daily_date = today
            self._update_degradation()
        
        month_prefix = today[:7]
        if month_prefix != self._monthly_date:
            self._monthly_tokens = 0
            self._monthly_cost = 0.0
            self._monthly_date = month_prefix
            self._update_degradation()
    
    def _persist_record(self, tokens_in, tokens_out, cost, provider, task_type):
        """Persist usage record to database."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                f"""INSERT INTO {self.USAGE_TABLE} 
                   (timestamp, tokens_in, tokens_out, cost, provider, task_type, degradation)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    tokens_in, tokens_out, cost,
                    provider, task_type,
                    self._current_degradation.value,
                )
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to persist usage record: {e}")
