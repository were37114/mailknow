"""Tier 4 link extractor - LLM semantic extraction.

Uses LLM (GPT-4o-mini) for semantic relationship extraction:
- Approval detection (is this email an approval request?)
- Implicit relationship extraction
- Intent classification
"""

import json
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from sync.models import Email
from .models import Link, LinkRelation, LinkTier
from llm.client import LLMClient, LLMProvider, get_llm_client
from llm.token_budget import TokenBudget

logger = logging.getLogger(__name__)


# Approval classification prompt
APPROVAL_PROMPT = """你是一个邮件分类专家。判断这封邮件是否是审批/签核请求。

审批邮件特征：
- 请求对方批准、同意、确认、签字、审核
- 包含审批关键词：请审批、请批准、请确认、请签字、请审核、同意否、是否可以
- 需要对方做出决策或授权

不是审批邮件的情况：
- 仅是通知/告知（"已审批"、"审批通过"）
- 抄送中的审批邮件（只是知会，不是主送）
- 系统自动通知
- 常规工作沟通

邮件信息：
- 主题：{subject}
- 发件人：{from_addr}
- 收件人：{to_addrs}
- 正文：{content}

请返回JSON格式：
{{
    "is_approval": true/false,
    "confidence": 0.0-1.0,
    "approval_type": "direct" | "cc" | "notification" | "none",
    "reason": "分类理由"
}}

只返回JSON，不要其他内容。"""


@dataclass
class ApprovalResult:
    """Approval classification result."""
    is_approval: bool
    confidence: float
    approval_type: str  # direct, cc, notification, none
    reason: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApprovalResult":
        """Create from dictionary."""
        return cls(
            is_approval=data.get("is_approval", False),
            confidence=data.get("confidence", 0.0),
            approval_type=data.get("approval_type", "none"),
            reason=data.get("reason", ""),
        )


class Tier4Extractor:
    """Extract Tier 4 links using LLM.
    
    Tier 4 = LLM-powered semantic extraction.
    ~400 tokens per email (for approval classification).
    """
    
    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        token_budget: Optional[TokenBudget] = None,
    ):
        """Initialize Tier 4 extractor.
        
        Args:
            llm_client: LLM client instance
            token_budget: Token budget controller
        """
        self.llm = llm_client or get_llm_client()
        self.budget = token_budget or TokenBudget()
    
    async def classify_approval(self, email: Email) -> ApprovalResult:
        """Classify if email is an approval request.
        
        Args:
            email: Email to classify
        
        Returns:
            Approval classification result
        """
        # If LLM is local (no API), use rule-based classification directly
        if self.llm.provider == LLMProvider.LOCAL:
            logger.debug("Using local rule-based classification (no LLM API)")
            return self._local_approval_classify(email)
        
        # Check budget
        estimated_tokens = 500  # ~400 input + ~100 output
        if not self.budget.check(estimated_tokens):
            logger.warning("Token budget exceeded, using local fallback")
            return self._local_approval_classify(email)
        
        # Prepare prompt
        content = self._truncate_content(email.text_body or "", max_chars=1000)
        
        prompt = APPROVAL_PROMPT.format(
            subject=email.subject,
            from_addr=str(email.from_addr),
            to_addrs=", ".join(str(a) for a in email.to_addrs),
            content=content,
        )
        
        try:
            response = await self.llm.complete(
                prompt=prompt,
                system="你是邮件分类专家，只返回JSON格式结果。",
                temperature=0.0,
                max_tokens=200,
                json_mode=True,
            )
            
            # Record token usage
            self.budget.record(response.tokens_total)
            
            # Parse response
            result = self._parse_approval_response(response.content)
            
            logger.info(
                f"Approval classification: is_approval={result.is_approval}, "
                f"confidence={result.confidence}, type={result.approval_type}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"LLM approval classification failed: {e}")
            return self._local_approval_classify(email)
    
    def extract(self, email: Email) -> List[Link]:
        """Extract Tier 4 links (synchronous wrapper for basic extraction).
        
        For full LLM-based extraction, use classify_approval() instead.
        This method provides local fallback extraction.
        """
        links = []
        email_id = self._get_email_id(email)
        
        # Local rule-based approval detection
        result = self._local_approval_classify(email)
        
        if result.is_approval:
            links.append(Link(
                source_id=email_id,
                target_id=f"approval:{result.approval_type}",
                relation=LinkRelation.RELATED_TO,
                tier=LinkTier.TIER_4,
                weight=result.confidence,
                metadata={
                    "type": "approval",
                    "approval_type": result.approval_type,
                    "reason": result.reason,
                    "provider": "local_fallback"
                }
            ))
        
        return links
    
    def _local_approval_classify(self, email: Email) -> ApprovalResult:
        """Local rule-based approval classification (fallback).
        
        Used when LLM is unavailable or budget exceeded.
        """
        subject = email.subject or ""
        content = email.text_body or ""
        
        # Approval keywords (order matters: longer phrases first)
        approval_keywords = [
            "请审批", "请批准", "请签字", "请审核",
            "请紧急审批", "紧急审批", "审核确认",
            "同意否", "是否可以", "审批请求", "审批申请",
            "approve", "approval", "sign off", "review and approve",
            "please approve",
            # Shorter keywords last (lower priority)
            "请确认",
        ]
        
        # Notification keywords (not approval - these indicate completed/rejected)
        # Checked FIRST, so they take priority over approval keywords
        notification_keywords = [
            "审批已通过", "审批已拒绝", "审批未通过", "审批不通过",
            "审批通过", "审批完成", "审批被拒", "审批已拒绝",
            "已审批通过", "已审批完成",
            "已审批", "已批准", "已同意",
            "未通过", "不通过", "被拒",
            "approved",
        ]
        
        # Check subject first
        subject_lower = subject.lower()
        content_lower = content.lower()
        
        # Check if it's a notification about completed approval
        for kw in notification_keywords:
            if kw in subject_lower or kw in content_lower:
                return ApprovalResult(
                    is_approval=False,
                    confidence=0.8,
                    approval_type="notification",
                    reason=f"已完成审批通知: {kw}"
                )
        
        # Check if it's an approval request
        # First, check for compound approval patterns (请...审批/批准/审核)
        approval_action_words = ["审批", "批准", "签字", "审核"]
        request_words = ["请", "需要", "要求", "烦请", "恳请", "望"]
        
        for action in approval_action_words:
            for request in request_words:
                # Check patterns like "请...审批" (with up to 4 chars between)
                import re
                pattern = rf"{request}.{{0,4}}{action}"
                if re.search(pattern, subject_lower) or re.search(pattern, content_lower):
                    is_cc = len(email.cc_addrs) > 0 and len(email.to_addrs) == 0
                    return ApprovalResult(
                        is_approval=True,
                        confidence=0.85 if not is_cc else 0.5,
                        approval_type="cc" if is_cc else "direct",
                        reason=f"包含审批请求模式: {request}...{action}"
                    )
        
        # Then check exact keyword matches
        for kw in approval_keywords:
            if kw in subject_lower or kw in content_lower:
                # Check if CC (not primary recipient)
                is_cc = len(email.cc_addrs) > 0 and len(email.to_addrs) == 0
                
                return ApprovalResult(
                    is_approval=True,
                    confidence=0.85 if not is_cc else 0.5,
                    approval_type="cc" if is_cc else "direct",
                    reason=f"包含审批关键词: {kw}"
                )
        
        return ApprovalResult(
            is_approval=False,
            confidence=0.3,
            approval_type="none",
            reason="未检测到审批特征"
        )
    
    def _parse_approval_response(self, content: str) -> ApprovalResult:
        """Parse LLM response into ApprovalResult."""
        try:
            # Try to extract JSON from response
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            
            data = json.loads(content)
            return ApprovalResult.from_dict(data)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM response: {content[:200]}")
            return ApprovalResult(
                is_approval=False,
                confidence=0.0,
                approval_type="none",
                reason="parse_error"
            )
    
    def _get_email_id(self, email: Email) -> str:
        """Get email ID."""
        if email.message_id:
            return f"email:{email.message_id.strip('<>')}"
        return f"email:unknown:{id(email)}"
    
    def _truncate_content(self, content: str, max_chars: int = 1000) -> str:
        """Truncate content to fit within token budget."""
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + "..."
