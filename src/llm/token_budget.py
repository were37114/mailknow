"""Token budget controller for MailKnow.

Ensures LLM costs stay within budget.
"""

import logging
from typing import Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class TokenBudget:
    """Token budget configuration."""
    daily_limit: int = 500_000  # 500K tokens/day
    per_request_limit: int = 10_000  # 10K tokens/request
    warning_threshold: float = 0.8  # Warn at 80%
    
    # Cost limits (USD)
    daily_cost_limit: float = 0.50  # $0.50/day for power users
    
    # Tracking
    _used_today: int = 0
    _cost_today: float = 0.0
    _reset_date: str = ""
    
    def check(self, estimated_tokens: int) -> bool:
        """Check if request is within budget.
        
        Args:
            estimated_tokens: Estimated tokens for this request
        
        Returns:
            True if request is allowed
        """
        self._maybe_reset()
        
        if estimated_tokens > self.per_request_limit:
            logger.warning(f"Request exceeds per-request limit: {estimated_tokens} > {self.per_request_limit}")
            return False
        
        if self._used_today + estimated_tokens > self.daily_limit:
            logger.warning(f"Daily budget exceeded: {self._used_today + estimated_tokens} > {self.daily_limit}")
            return False
        
        if self._used_today + estimated_tokens > self.daily_limit * self.warning_threshold:
            logger.warning(
                f"Approaching daily budget: {self._used_today + estimated_tokens}/{self.daily_limit}"
            )
        
        return True
    
    def record(self, tokens_used: int, cost: float = 0.0) -> None:
        """Record token usage.
        
        Args:
            tokens_used: Actual tokens used
            cost: Cost in USD
        """
        self._maybe_reset()
        self._used_today += tokens_used
        self._cost_today += cost
    
    @property
    def remaining(self) -> int:
        """Remaining tokens for today."""
        self._maybe_reset()
        return max(0, self.daily_limit - self._used_today)
    
    @property
    def usage_ratio(self) -> float:
        """Current usage ratio (0-1)."""
        self._maybe_reset()
        return self._used_today / self.daily_limit if self.daily_limit > 0 else 0.0
    
    def _maybe_reset(self):
        """Reset daily counters if new day."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._reset_date:
            if self._reset_date:
                logger.info(f"Token budget reset: used {self._used_today} tokens, ${self._cost_today:.4f}")
            self._used_today = 0
            self._cost_today = 0.0
            self._reset_date = today
