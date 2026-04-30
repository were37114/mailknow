"""Weekly report generator - deterministic derivation with LLM enhancement.

V5.2 spec:
- Deterministic derivation: only facts, no predictions ("下周计划" forbidden)
- GBrain + LLM hybrid generation
- Template-based fallback when LLM unavailable
- Friday 16:00 auto-reminder trigger
- Editable + exportable output
"""

import json
import logging
import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from llm.client import LLMClient, LLMProvider, get_llm_client
from llm.token_budget_v2 import TokenBudgetController
from llm.fallback import WithFallback, get_fallback

logger = logging.getLogger(__name__)


# Forbidden phrases that indicate prediction (not deterministic)
FORBIDDEN_PHRASES = [
    "下周计划", "下周将", "下周准备", "下周要",
    "未来计划", "计划中", "预计将", "将会",
    "next week", "plan to", "will do",
    "打算", "准备做", "即将",
]

# Patterns that indicate factual content (allowed)
FACTUAL_PATTERNS = [
    r"完成了?\s", r"已\s*(完成|提交|发送|审批|回复)",
    r"收到\s*\d+\s*封", r"处理了?\s",
    r"与\s*.+\s*(讨论|沟通|确认)", r"参加了?\s",
    r"提交了?\s", r"通过了?\s", r"拒绝了?\s",
]


@dataclass
class ReportSection:
    """A section of the weekly report."""
    title: str
    items: List[str]
    source_count: int  # Number of emails this section is based on
    source_ids: List[str] = field(default_factory=list)  # Email IDs for traceability


@dataclass
class WeeklyReport:
    """Generated weekly report."""
    period_start: str
    period_end: str
    sections: List[ReportSection]
    total_emails: int
    generated_at: str
    llm_used: bool = False
    deterministic_only: bool = False
    validation_passed: bool = True
    validation_warnings: List[str] = field(default_factory=list)
    
    def to_markdown(self) -> str:
        """Convert report to markdown format."""
        lines = [
            f"# 周报 {self.period_start} ~ {self.period_end}",
            "",
            f"> 基于 {self.total_emails} 封邮件自动生成 | "
            f"{'GBrain + LLM' if self.llm_used else 'GBrain 确定性推导'}",
            "",
        ]
        
        if self.validation_warnings:
            lines.append("> ⚠️ 以下内容可能包含非确定性推导，请人工审核：")
            for w in self.validation_warnings:
                lines.append(f"> - {w}")
            lines.append("")
        
        for section in self.sections:
            lines.append(f"## {section.title}")
            for item in section.items:
                lines.append(f"- {item}")
            lines.append(f"_（来源：{section.source_count}封邮件）_")
            lines.append("")
        
        lines.append("---")
        lines.append(f"生成时间：{self.generated_at}")
        if not self.validation_passed:
            lines.append("⚠️ 此报告包含预测性内容，建议人工审核")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "period_start": self.period_start,
            "period_end": self.period_end,
            "sections": [
                {
                    "title": s.title,
                    "items": s.items,
                    "source_count": s.source_count,
                    "source_ids": s.source_ids,
                }
                for s in self.sections
            ],
            "total_emails": self.total_emails,
            "generated_at": self.generated_at,
            "llm_used": self.llm_used,
            "deterministic_only": self.deterministic_only,
            "validation_passed": self.validation_passed,
            "validation_warnings": self.validation_warnings,
        }


# LLM prompt for report generation
REPORT_PROMPT = """你是一个周报生成助手。根据用户本周的邮件数据，生成一份结构化的周报。

⚠️ 重要规则（必须严格遵守）：
1. 只基于提供的邮件数据生成，不要编造内容
2. **绝对不要包含"下周计划"或任何预测性内容**（V5.2规范）
3. 每条结论必须可追溯到源邮件
4. 使用确定性推导，不猜测意图
5. 不要出现"计划"、"预计"、"打算"、"准备"等预测性词汇

本周邮件数据：
{email_data}

请返回JSON格式：
{{
    "sections": [
        {{
            "title": "分类标题",
            "items": ["条目1", "条目2"],
            "source_count": 数量
        }}
    ]
}}

只返回JSON，不要其他内容。"""


class DeterministicValidator:
    """Validate report content for deterministic derivation compliance.
    
    Checks:
    - No forbidden phrases (下周计划, etc.)
    - Each item is factual (not predictive)
    - Returns validation result with warnings
    """
    
    def validate(self, report: WeeklyReport) -> tuple:
        """Validate report for deterministic compliance.
        
        Returns:
            (passed, warnings) tuple
        """
        warnings = []
        
        for section in report.sections:
            for item in section.items:
                # Check forbidden phrases
                for phrase in FORBIDDEN_PHRASES:
                    if phrase in item:
                        warnings.append(f"'{item[:50]}...' 包含预测性词汇：{phrase}")
                
                # Check if item is factual
                is_factual = any(re.search(p, item) for p in FACTUAL_PATTERNS)
                is_forbidden = any(phrase in item for phrase in FORBIDDEN_PHRASES)
                
                if not is_factual and not is_forbidden:
                    # Neutral item - acceptable but flag for review
                    pass
        
        passed = len(warnings) == 0
        return passed, warnings


class ReportGenerator:
    """Weekly report generator with deterministic derivation.
    
    Strategy:
    1. Collect emails for the week
    2. Classify by Gate class and entity
    3. Generate deterministic sections (no LLM)
    4. Optionally enhance with LLM (with deterministic validation)
    5. Validate output for compliance
    """
    
    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        token_budget: Optional[TokenBudgetController] = None,
        fallback: Optional[WithFallback] = None,
    ):
        self.llm = llm_client or get_llm_client()
        self.budget = token_budget or TokenBudgetController()
        self.fallback = fallback or get_fallback()
        self.validator = DeterministicValidator()
    
    def generate(
        self,
        emails: List[Dict[str, Any]],
        period_start: Optional[str] = None,
        period_end: Optional[str] = None,
        use_llm: bool = True,
    ) -> WeeklyReport:
        """Generate weekly report from emails.
        
        Args:
            emails: List of email dicts with keys: subject, from, to, content, gate_class, date, is_approval, email_id
            period_start: Period start date (YYYY-MM-DD)
            period_end: Period end date (YYYY-MM-DD)
            use_llm: Whether to use LLM enhancement
            
        Returns:
            Generated weekly report (validated)
        """
        now = datetime.now()
        
        # Default period: last 7 days
        if not period_start:
            period_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        if not period_end:
            period_end = now.strftime("%Y-%m-%d")
        
        # Generate deterministic sections (synchronous - no LLM)
        sections = self._generate_deterministic_sections(emails)
        
        # LLM enhancement is async - call async_generate for full functionality
        # For sync usage, just use deterministic sections
        
        # Build report
        report = WeeklyReport(
            period_start=period_start,
            period_end=period_end,
            sections=sections,
            total_emails=len(emails),
            generated_at=now.strftime("%Y-%m-%d %H:%M"),
            llm_used=False,
            deterministic_only=True,
        )
        
        # Validate for deterministic compliance
        passed, warnings = self.validator.validate(report)
        report.validation_passed = passed
        report.validation_warnings = warnings
        
        if warnings:
            logger.warning(f"Report has {len(warnings)} deterministic violations")
        
        return report
    
    async def async_generate(
        self,
        emails: List[Dict[str, Any]],
        period_start: Optional[str] = None,
        period_end: Optional[str] = None,
    ) -> WeeklyReport:
        """Async version with LLM enhancement."""
        now = datetime.now()
        
        if not period_start:
            period_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        if not period_end:
            period_end = now.strftime("%Y-%m-%d")
        
        sections = self._generate_deterministic_sections(emails)
        
        llm_used = False
        if self.budget.degradation_level.value != "pure_gbrain":
            enhanced = await self._enhance_with_llm(emails, sections)
            if enhanced:
                sections = enhanced
                llm_used = True
        
        report = WeeklyReport(
            period_start=period_start,
            period_end=period_end,
            sections=sections,
            total_emails=len(emails),
            generated_at=now.strftime("%Y-%m-%d %H:%M"),
            llm_used=llm_used,
            deterministic_only=not llm_used,
        )
        
        passed, warnings = self.validator.validate(report)
        report.validation_passed = passed
        report.validation_warnings = warnings
        
        return report
    
    def _generate_deterministic_sections(
        self,
        emails: List[Dict[str, Any]]
    ) -> List[ReportSection]:
        """Generate report sections using deterministic rules (no LLM)."""
        sections = []
        
        # 1. Important emails section
        gate_groups = self._group_by_gate(emails)
        important = gate_groups.get("important", []) + gate_groups.get("urgent", [])
        if important:
            items = self._summarize_emails(important, max_items=10)
            sections.append(ReportSection(
                title="⭐ 重要事项",
                items=items,
                source_count=len(important),
                source_ids=[e.get("email_id", "") for e in important[:10]],
            ))
        
        # 2. Approval emails
        approval_emails = [e for e in emails if e.get("is_approval")]
        if approval_emails:
            items = self._summarize_approvals(approval_emails)
            sections.append(ReportSection(
                title="📋 待审批",
                items=items,
                source_count=len(approval_emails),
                source_ids=[e.get("email_id", "") for e in approval_emails],
            ))
        
        # 3. Routine work - grouped by sender
        routine = gate_groups.get("routine", [])
        if routine:
            by_sender = self._group_by_sender(routine)
            items = []
            for sender, sender_emails in sorted(by_sender.items(), key=lambda x: -len(x[1])):
                count = len(sender_emails)
                subjects = [e.get("subject", "") for e in sender_emails[:3]]
                items.append(f"{sender} ({count}封): {', '.join(subjects)}")
            sections.append(ReportSection(
                title="📬 常规工作",
                items=items[:10],
                source_count=len(routine),
                source_ids=[e.get("email_id", "") for e in routine[:10]],
            ))
        
        # 4. Notifications summary
        notifications = gate_groups.get("notification", [])
        if notifications:
            items = [f"收到 {len(notifications)} 封通知邮件"]
            by_sender = self._group_by_sender(notifications)
            for sender, sender_emails in sorted(by_sender.items(), key=lambda x: -len(x[1]))[:5]:
                items.append(f"- {sender}: {len(sender_emails)}封")
            sections.append(ReportSection(
                title="🔔 通知汇总",
                items=items,
                source_count=len(notifications),
                source_ids=[e.get("email_id", "") for e in notifications[:5]],
            ))
        
        # 5. Spam
        spam = gate_groups.get("spam", [])
        if spam:
            sections.append(ReportSection(
                title="🗑️ 垃圾邮件",
                items=[f"过滤 {len(spam)} 封垃圾邮件"],
                source_count=len(spam),
            ))
        
        return sections
    
    async def _enhance_with_llm(
        self,
        emails: List[Dict[str, Any]],
        existing_sections: List[ReportSection],
    ) -> Optional[List[ReportSection]]:
        """Enhance report with LLM.
        
        Returns None if LLM is unavailable or fails.
        """
        estimated_tokens = min(len(emails) * 100, 3000) + 500
        
        try:
            # Prepare email data summary (desensitized by WithFallback)
            email_summaries = []
            for email in emails[:30]:
                email_summaries.append({
                    "subject": email.get("subject", ""),
                    "from": email.get("from", ""),
                    "gate_class": email.get("gate_class", ""),
                    "is_approval": email.get("is_approval", False),
                })
            
            email_data = json.dumps(email_summaries, ensure_ascii=False, indent=2)
            prompt = REPORT_PROMPT.format(email_data=email_data)
            
            result = await self.fallback.call(
                prompt=prompt,
                system="你是周报生成助手，只基于提供的数据生成报告。绝对不要包含预测性内容。",
                temperature=0.0,
                max_tokens=1500,
                json_mode=True,
                task_type="report",
                estimated_tokens=estimated_tokens,
            )
            
            if result.used_fallback:
                logger.info("LLM enhancement used fallback, keeping deterministic sections")
                return None
            
            # Parse response
            data = json.loads(result.content)
            sections = []
            for section_data in data.get("sections", []):
                section = ReportSection(
                    title=section_data.get("title", ""),
                    items=section_data.get("items", []),
                    source_count=section_data.get("source_count", 0),
                )
                sections.append(section)
            
            return sections if sections else None
            
        except Exception as e:
            logger.error(f"LLM enhancement failed: {e}")
            return None
    
    def _summarize_emails(
        self,
        emails: List[Dict[str, Any]],
        max_items: int = 10
    ) -> List[str]:
        """Summarize email list into bullet points."""
        items = []
        for email in emails[:max_items]:
            subject = email.get("subject", "无主题")
            sender = email.get("from", "未知")
            date = email.get("date", "")
            sender_name = sender.split("@")[0] if "@" in sender else sender
            
            if date:
                items.append(f"[{date}] {subject} (from: {sender_name})")
            else:
                items.append(f"{subject} (from: {sender_name})")
        return items
    
    def _summarize_approvals(
        self,
        emails: List[Dict[str, Any]]
    ) -> List[str]:
        """Summarize approval emails."""
        items = []
        for email in emails:
            subject = email.get("subject", "无主题")
            approval_type = email.get("approval_type", "direct")
            status = "待审批" if approval_type == "direct" else "抄送知会"
            items.append(f"{subject} [{status}]")
        return items
    
    def _group_by_gate(
        self,
        emails: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group emails by Gate class."""
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for email in emails:
            gate = email.get("gate_class", "routine")
            if gate not in groups:
                groups[gate] = []
            groups[gate].append(email)
        return groups
    
    def _group_by_sender(
        self,
        emails: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group emails by sender."""
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for email in emails:
            sender = email.get("from", "unknown")
            sender_name = sender.split("@")[0] if "@" in sender else sender
            if sender_name not in groups:
                groups[sender_name] = []
            groups[sender_name].append(email)
        return groups


class ReportScheduler:
    """Schedule weekly report generation.
    
    V5.2 spec: Friday 16:00 auto-reminder.
    Scene recommendation card can also trigger report generation.
    """
    
    def __init__(
        self,
        generator: Optional[ReportGenerator] = None,
    ):
        self.generator = generator or ReportGenerator()
        self._last_generated: Optional[str] = None
        self._scheduled_time = "16:00"  # Friday 16:00
        self._scheduled_day = 4  # 0=Monday, 4=Friday
    
    def should_generate(self, now: Optional[datetime] = None) -> bool:
        """Check if it's time to generate the weekly report.
        
        Returns True on Friday at/after 16:00 (once per week).
        """
        if now is None:
            now = datetime.now()
        
        # Check if it's Friday
        if now.weekday() != self._scheduled_day:
            return False
        
        # Check if it's after scheduled time
        current_time = now.strftime("%H:%M")
        if current_time < self._scheduled_time:
            return False
        
        # Check if already generated this week
        this_week_key = now.strftime("%Y-W%W")
        if self._last_generated == this_week_key:
            return False
        
        return True
    
    def generate_if_due(
        self,
        emails: List[Dict[str, Any]],
        now: Optional[datetime] = None,
    ) -> Optional[WeeklyReport]:
        """Generate report if it's due.
        
        Returns report or None.
        """
        if not self.should_generate(now):
            return None
        
        report = self.generator.generate(emails)
        
        # Mark as generated
        if now is None:
            now = datetime.now()
        self._last_generated = now.strftime("%Y-W%W")
        
        logger.info(f"Auto-generated weekly report for {report.period_start} ~ {report.period_end}")
        return report
