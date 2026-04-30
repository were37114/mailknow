"""Data desensitization engine for MailKnow.

Protects sensitive information before sending to LLM:
1. Person names (人名) - 张三 → 张* / 张某
2. Phone numbers (手机号) - 13812345678 → 138****5678
3. Email addresses (邮箱) - test@company.com → t***@company.com
4. ID card numbers (身份证) - 110101199001011234 → 110101****1234
5. Amounts (金额) - ¥50,000 → ¥[金额]
6. Passwords/keys (密码/密钥) - password: abc123 → password: [已脱敏]

Design principles:
- Reversible mapping stored locally (never sent to LLM)
- Minimal context loss for classification tasks
- Configurable per-rule enable/disable
"""

import re
import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class SensitiveType(str, Enum):
    """Types of sensitive information."""
    PERSON_NAME = "person_name"
    PHONE = "phone"
    EMAIL = "email"
    ID_CARD = "id_card"
    AMOUNT = "amount"
    PASSWORD = "password"


@dataclass
class DesensitizeRule:
    """A single desensitization rule."""
    type: SensitiveType
    pattern: re.Pattern
    replacement: str
    enabled: bool = True
    description: str = ""


@dataclass
class DesensitizeResult:
    """Result of desensitization."""
    original: str
    sanitized: str
    replacements: List[Dict[str, str]]  # [{original: "张三", sanitized: "张*", type: "person_name"}]

    @property
    def was_modified(self) -> bool:
        return self.original != self.sanitized


class DesensitizeEngine:
    """Data desensitization engine.
    
    Usage:
        engine = DesensitizeEngine()
        result = engine.desensitize("张三的手机号是13812345678")
        # result.sanitized = "张*的手机号是138****5678"
        # result.replacements = [{original: "张三", sanitized: "张*", type: "person_name"}, ...]
        
        # Restore (using mapping)
        restored = engine.restore(result.sanitized, result.replacements)
        # restored == "张三的手机号是13812345678"
    """
    
    # Chinese name patterns (2-4 characters, common surnames)
    COMMON_SURNAMES = (
        "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
        "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐"
        "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄"
    )
    
    def __init__(self, rules: Optional[List[DesensitizeRule]] = None):
        """Initialize desensitization engine.
        
        Args:
            rules: Custom rules (default: all 6 types enabled)
        """
        self.rules = rules or self._default_rules()
    
    def _default_rules(self) -> List[DesensitizeRule]:
        """Create default desensitization rules."""
        return [
            # 1. Phone numbers
            DesensitizeRule(
                type=SensitiveType.PHONE,
                pattern=re.compile(
                    r'(?<!\d)(1[3-9]\d{9})(?!\d)'  # Chinese mobile
                ),
                replacement=r'\1',  # Will be custom-replaced
                description="手机号脱敏",
            ),
            # 2. Email addresses
            DesensitizeRule(
                type=SensitiveType.EMAIL,
                pattern=re.compile(
                    r'([A-Za-z0-9._%+\-])([A-Za-z0-9._%+\-]*)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})'
                ),
                replacement=r'\1***@\3',
                description="邮箱脱敏",
            ),
            # 3. ID card numbers (18 digits)
            DesensitizeRule(
                type=SensitiveType.ID_CARD,
                pattern=re.compile(
                    r'(?<!\d)([1-9]\d{5})(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)'
                ),
                replacement=r'\1****\4\5****',
                description="身份证脱敏",
            ),
            # 4. Amounts (¥/$ followed by numbers)
            DesensitizeRule(
                type=SensitiveType.AMOUNT,
                pattern=re.compile(
                    r'[¥￥$]\s*[\d,]+\.?\d*|\d{1,3}(,\d{3})+\.?\d*\s*(元|万|块|美元|美金)'
                ),
                replacement='[金额]',
                description="金额脱敏",
            ),
            # 5. Passwords/keys
            DesensitizeRule(
                type=SensitiveType.PASSWORD,
                pattern=re.compile(
                    r'(密码|password|passwd|pwd|secret|token|key|密钥|API\s*key)[:\s=：]+\S+',
                    re.IGNORECASE
                ),
                replacement=r'\1: [已脱敏]',
                description="密码/密钥脱敏",
            ),
            # 6. Person names (Chinese, 2-4 chars after common surnames)
            # Match surname + 1-3 chars, with word boundary context
            DesensitizeRule(
                type=SensitiveType.PERSON_NAME,
                pattern=re.compile(
                    r'([' + DesensitizeEngine.COMMON_SURNAMES + r'])([\u4e00-\u9fa5]{1,3})(?=[，。、：；！？\s\n\r）)的了的与和]|$)'
                ),
                replacement=r'\1*',
                description="人名脱敏",
            ),
        ]
    
    def desensitize(self, text: str) -> DesensitizeResult:
        """Desensitize text by replacing sensitive information.
        
        Args:
            text: Input text
            
        Returns:
            DesensitizeResult with sanitized text and replacement mapping
        """
        if not text:
            return DesensitizeResult(original=text, sanitized=text, replacements=[])
        
        sanitized = text
        replacements = []
        
        for rule in self.rules:
            if not rule.enabled:
                continue
            
            try:
                sanitized, rule_replacements = self._apply_rule(sanitized, rule)
                replacements.extend(rule_replacements)
            except Exception as e:
                logger.warning(f"Rule {rule.type.value} failed: {e}")
        
        return DesensitizeResult(
            original=text,
            sanitized=sanitized,
            replacements=replacements,
        )
    
    def _apply_rule(
        self, 
        text: str, 
        rule: DesensitizeRule
    ) -> Tuple[str, List[Dict[str, str]]]:
        """Apply a single desensitization rule.
        
        Returns:
            Tuple of (sanitized_text, replacements)
        """
        replacements = []
        
        def replace_match(match):
            original = match.group(0)
            
            if rule.type == SensitiveType.PHONE:
                # 13812345678 → 138****5678
                sanitized = original[:3] + "****" + original[-4:]
            elif rule.type == SensitiveType.EMAIL:
                # test@company.com → t***@company.com
                if len(match.group(2)) > 0:
                    sanitized = f"{match.group(1)}***@{match.group(3)}"
                else:
                    sanitized = f"{match.group(1)}***@{match.group(3)}"
            elif rule.type == SensitiveType.ID_CARD:
                # 110101199001011234 → 110101****0112****
                full = original
                sanitized = full[:6] + "****" + full[10:14] + "****"
            elif rule.type == SensitiveType.PERSON_NAME:
                # 张三 → 张*
                sanitized = match.group(1) + "*"
            else:
                sanitized = rule.replacement
            
            replacements.append({
                "original": original,
                "sanitized": sanitized,
                "type": rule.type.value,
            })
            
            return sanitized
        
        result = rule.pattern.sub(replace_match, text)
        return result, replacements
    
    def restore(self, text: str, replacements: List[Dict[str, str]]) -> str:
        """Restore desensitized text using replacement mapping.
        
        Args:
            text: Sanitized text
            replacements: Replacement mapping from desensitize()
            
        Returns:
            Restored text
        """
        restored = text
        for r in reversed(replacements):
            restored = restored.replace(r["sanitized"], r["original"], 1)
        return restored
    
    def enable_rule(self, type_: SensitiveType) -> None:
        """Enable a desensitization rule."""
        for rule in self.rules:
            if rule.type == type_:
                rule.enabled = True
    
    def disable_rule(self, type_: SensitiveType) -> None:
        """Disable a desensitization rule."""
        for rule in self.rules:
            if rule.type == type_:
                rule.enabled = False
    
    def list_rules(self) -> List[Dict[str, Any]]:
        """List all rules with their status."""
        return [
            {
                "type": rule.type.value,
                "description": rule.description,
                "enabled": rule.enabled,
            }
            for rule in self.rules
        ]
