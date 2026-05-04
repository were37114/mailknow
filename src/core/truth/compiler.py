"""compiled_truth - LLM-generated entity summaries with template fallback.

V5.2 spec:
- LLM generates entity summaries from related emails
- Template-based fallback when LLM unavailable
- 30-minute cache for compiled truths
- Incremental updates on new email arrivals
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from llm.client import LLMClient, LLMProvider, get_llm_client
from llm.fallback import WithFallback, get_fallback
from llm.token_budget_v2 import TokenBudgetController

logger = logging.getLogger(__name__)


@dataclass
class CompiledTruth:
    """A compiled truth for an entity."""
    entity_id: str
    entity_name: str
    entity_type: str  # person, org, project

    # The compiled content
    summary: str
    key_facts: List[str] = field(default_factory=list)

    # Source info
    source_count: int = 0
    source_ids: List[str] = field(default_factory=list)

    # Generation info
    llm_used: bool = False
    generated_at: str = ""
    cache_expires_at: str = ""

    # Stats
    email_count: int = 0
    last_email_date: str = ""

    def is_expired(self) -> bool:
        """Check if cached truth has expired."""
        if not self.cache_expires_at:
            return True
        try:
            expires = datetime.fromisoformat(self.cache_expires_at)
            return datetime.now(timezone.utc) > expires
        except ValueError:
            return True


# LLM prompt for truth compilation
TRUTH_PROMPT = """你是一个信息摘要助手。根据以下邮件数据，为实体"{entity_name}"生成一份结构化摘要。

⚠️ 重要规则：
1. 只基于提供的邮件数据，不要编造
2. 使用确定性推导，不猜测意图
3. 提取关键事实，不要预测性内容
4. 每条事实必须可追溯到源邮件

邮件数据：
{email_data}

请返回JSON格式：
{{
    "summary": "一句话摘要",
    "key_facts": ["事实1", "事实2", "事实3"],
    "source_count": 邮件数量
}}

只返回JSON，不要其他内容。"""


class TruthCompiler:
    """Compile entity truths from email data.

    Strategy:
    1. Check cache for existing truth
    2. If expired or missing, compile from emails
    3. Try LLM generation first
    4. Fall back to template-based generation
    5. Cache result with 30-minute TTL
    """

    CACHE_TTL_SECONDS = 30 * 60  # 30 minutes

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        token_budget: Optional[TokenBudgetController] = None,
        fallback: Optional[WithFallback] = None,
        cache_ttl: Optional[int] = None,
    ):
        self.llm = llm_client or get_llm_client()
        self.budget = token_budget or TokenBudgetController()
        self.fallback = fallback or get_fallback()
        self.cache_ttl = cache_ttl or self.CACHE_TTL_SECONDS

        # In-memory cache: entity_id → CompiledTruth
        self._cache: Dict[str, CompiledTruth] = {}

    async def compile(
        self,
        entity_id: str,
        entity_name: str,
        entity_type: str,
        related_emails: List[Dict[str, Any]],
        force: bool = False,
    ) -> CompiledTruth:
        """Compile truth for an entity.

        Args:
            entity_id: Entity identifier
            entity_name: Entity display name
            entity_type: Entity type (person, org, project)
            related_emails: Related email dicts
            force: Force recompilation even if cached

        Returns:
            Compiled truth
        """
        # Check cache
        if not force and entity_id in self._cache:
            cached = self._cache[entity_id]
            if not cached.is_expired():
                logger.debug(f"Using cached truth for {entity_id}")
                return cached

        if not related_emails:
            truth = self._empty_truth(entity_id, entity_name, entity_type)
            self._cache[entity_id] = truth
            return truth

        # Try LLM compilation
        truth = await self._compile_with_llm(entity_id, entity_name, entity_type, related_emails)

        if truth is None:
            # Fallback to template
            truth = self._compile_with_template(entity_id, entity_name, entity_type, related_emails)

        # Cache
        self._cache[entity_id] = truth
        return truth

    async def _compile_with_llm(
        self,
        entity_id: str,
        entity_name: str,
        entity_type: str,
        related_emails: List[Dict[str, Any]],
    ) -> Optional[CompiledTruth]:
        """Compile truth using LLM."""
        estimated_tokens = min(len(related_emails) * 80, 2000) + 300

        try:
            # Prepare email summaries
            email_summaries = []
            for email in related_emails[:20]:
                email_summaries.append({
                    "subject": email.get("subject", ""),
                    "from": email.get("from", ""),
                    "date": email.get("date", ""),
                    "gate_class": email.get("gate_class", ""),
                    "is_approval": email.get("is_approval", False),
                })

            email_data = json.dumps(email_summaries, ensure_ascii=False, indent=2)
            prompt = TRUTH_PROMPT.format(entity_name=entity_name, email_data=email_data)

            result = await self.fallback.call(
                prompt=prompt,
                system="你是信息摘要助手，只基于提供的数据生成摘要。不要包含预测性内容。",
                temperature=0.0,
                max_tokens=500,
                json_mode=True,
                task_type="compile_truth",
                estimated_tokens=estimated_tokens,
            )

            if result.used_fallback:
                return None

            # Parse response
            data = json.loads(result.content)

            now = datetime.now(timezone.utc)
            expires = datetime.fromtimestamp(now.timestamp() + self.cache_ttl, tz=timezone.utc)

            return CompiledTruth(
                entity_id=entity_id,
                entity_name=entity_name,
                entity_type=entity_type,
                summary=data.get("summary", ""),
                key_facts=data.get("key_facts", []),
                source_count=data.get("source_count", len(related_emails)),
                source_ids=[e.get("email_id", "") for e in related_emails[:20]],
                llm_used=True,
                generated_at=now.isoformat(),
                cache_expires_at=expires.isoformat(),
                email_count=len(related_emails),
                last_email_date=related_emails[0].get("date", "") if related_emails else "",
            )

        except Exception as e:
            logger.error(f"LLM truth compilation failed for {entity_id}: {e}")
            return None

    def _compile_with_template(
        self,
        entity_id: str,
        entity_name: str,
        entity_type: str,
        related_emails: List[Dict[str, Any]],
    ) -> CompiledTruth:
        """Compile truth using templates (no LLM)."""
        now = datetime.now(timezone.utc)
        expires = datetime.fromtimestamp(now.timestamp() + self.cache_ttl, tz=timezone.utc)

        # Template-based summary
        email_count = len(related_emails)

        # Count by gate class
        gate_counts: Dict[str, int] = {}
        approval_count = 0
        for email in related_emails:
            gate = email.get("gate_class", "routine")
            gate_counts[gate] = gate_counts.get(gate, 0) + 1
            if email.get("is_approval"):
                approval_count += 1

        # Build summary
        if entity_type == "person":
            summary = f"{entity_name}：共{email_count}封邮件往来"
            if approval_count > 0:
                summary += f"，含{approval_count}封审批"
        elif entity_type == "org":
            summary = f"{entity_name}：共{email_count}封组织相关邮件"
        else:
            summary = f"{entity_name}：共{email_count}封相关邮件"

        # Build key facts
        key_facts = []
        if gate_counts.get("important", 0) > 0:
            key_facts.append(f"重要邮件{gate_counts['important']}封")
        if gate_counts.get("urgent", 0) > 0:
            key_facts.append(f"紧急邮件{gate_counts['urgent']}封")
        if approval_count > 0:
            key_facts.append(f"审批邮件{approval_count}封")

        # Recent subjects
        recent = [e.get("subject", "") for e in related_emails[:3] if e.get("subject")]
        if recent:
            key_facts.append(f"最近：{', '.join(recent[:2])}")

        return CompiledTruth(
            entity_id=entity_id,
            entity_name=entity_name,
            entity_type=entity_type,
            summary=summary,
            key_facts=key_facts,
            source_count=email_count,
            source_ids=[e.get("email_id", "") for e in related_emails[:20]],
            llm_used=False,
            generated_at=now.isoformat(),
            cache_expires_at=expires.isoformat(),
            email_count=email_count,
            last_email_date=related_emails[0].get("date", "") if related_emails else "",
        )

    def _empty_truth(
        self,
        entity_id: str,
        entity_name: str,
        entity_type: str,
    ) -> CompiledTruth:
        """Return empty truth for entity with no emails."""
        now = datetime.now(timezone.utc)
        return CompiledTruth(
            entity_id=entity_id,
            entity_name=entity_name,
            entity_type=entity_type,
            summary=f"{entity_name}：暂无邮件往来",
            key_facts=[],
            source_count=0,
            llm_used=False,
            generated_at=now.isoformat(),
            cache_expires_at=now.isoformat(),
        )

    def invalidate(self, entity_id: str) -> None:
        """Invalidate cached truth for an entity."""
        self._cache.pop(entity_id, None)

    def invalidate_all(self) -> None:
        """Invalidate all cached truths."""
        self._cache.clear()

    def get_cached(self, entity_id: str) -> Optional[CompiledTruth]:
        """Get cached truth without recompiling."""
        return self._cache.get(entity_id)

    def get_stats(self) -> Dict[str, Any]:
        """Get compiler statistics."""
        return {
            "cached_entities": len(self._cache),
            "cache_ttl_seconds": self.cache_ttl,
        }


# Global instance
_compiler: Optional[TruthCompiler] = None


def get_truth_compiler() -> TruthCompiler:
    """Get global truth compiler instance."""
    global _compiler
    if _compiler is None:
        _compiler = TruthCompiler()
    return _compiler
