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
    # Covers top 200+ Chinese surnames (covering 96%+ of population)
    COMMON_SURNAMES = (
        "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
        "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐"
        "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄"
        "和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁"
        "杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐丘骆高夏蔡田樊胡凌霍"
        "虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚程"
        "嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗"
        "山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司"
        "韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭"
        "贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿"
        "阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东"
        "欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢"
        "关蒯相查后荆红游竺权逯盖益桓公"
    )
    
    # Characters very unlikely to appear in Chinese given names
    # Used to filter false positives like "安排" (安+排), "关于" (关+于)
    NON_NAME_CHARS = frozenset(
        # Structural / grammatical particles
        '了是在有会将要能可以给向从对被让把到去来又或也'
        # Common verbs (business context)
        '参加审批批准办理执行完成通过进行开始准备'
        # Measure words
        '个只条项件种次位本分元角'
        # Common content words (not names)
        '关于项目安排工作内容要求情况问题方式方法'
        # Adverbs / conjunctions
        '很已正虽但如果因为所以虽然而且'
        # Pronouns / determiners
        '些这里那哪每各某另该此其之'
        # Aspect markers / negatives
        '得地着过不没'
    )
    
    # Characters that commonly precede person names in email context
    NAME_PREFIX_CHARS = frozenset('：致请给和与向对被让把叫称由收发告转约代托帮送交')
    
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
            # 4. Amounts (¥/$ followed by numbers, or Chinese amounts)
            DesensitizeRule(
                type=SensitiveType.AMOUNT,
                pattern=re.compile(
                    r'[¥￥$]\s*[\d,]+\.?\d*|'  # ¥50000, $100
                    r'\d{1,3}(,\d{3})+\.?\d*\s*(元|块|美元|美金)|'  # 50,000元
                    r'\d+(\.\d+)?\s*(万|万元|亿|亿元)|(金额|合同金额|预算|报价)[:：]?\s*\d+(\.\d+)?\s*(万|万元|亿|亿元|元)'  # 150万, 合同金额800万元
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
            # Pattern: surname + 1-2 char given name (no trailing lookahead constraint)
            # All validation is done in _is_valid_person_name to avoid
            # the impossibility of enumerating all Chinese boundary chars
            DesensitizeRule(
                type=SensitiveType.PERSON_NAME,
                pattern=re.compile(
                    r'([' + DesensitizeEngine.COMMON_SURNAMES + r'])'
                    r'([\u4e00-\u9fa5]{1,2})'
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
    
    def _is_valid_person_name(self, given_name: str, start: int, text: str) -> bool:
        """Validate if a matched pattern is likely a real person name.
        
        Filters out false positives like:
        - "安排" (安+排) where 安 is a surname but 排 is not a name char
        - "关于" (关+于) where 关 is a surname but 于 is a particle
        - "经理" after 张 etc.
        
        Args:
            given_name: The name part after surname (1-2 chars)
            start: Start position of the match in text
            text: The full text being processed
            
        Returns:
            True if this looks like a real person name
        """
        # Check leading context: if preceded by a non-boundary CJK char, likely false positive
        # e.g., "培训安排" → 安排 is not a name
        # But "收件人：刘洋" → 刘洋 is a name (：is boundary)
        # Also skip if inside a desensitization marker like [金额]
        if start > 0:
            prev_char = text[start - 1]
            # Skip if inside desensitization bracket marker
            if prev_char == '[':
                return False
            if '\u4e00' <= prev_char <= '\u9fa5':
                if prev_char not in self.NAME_PREFIX_CHARS:
                    return False
        
        # For 2-char given names, both chars must not be in exclusion list
        # For 1-char given names, check if it's a common non-name word
        if len(given_name) == 2:
            if any(ch in self.NON_NAME_CHARS for ch in given_name):
                return False
        elif len(given_name) == 1:
            if given_name in self.NON_NAME_CHARS:
                return False
        
        return True
    
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
            
            # For person names, validate the match to avoid false positives
            # If a 2-char given name fails validation, try 1-char instead
            if rule.type == SensitiveType.PERSON_NAME:
                given_name = match.group(2)
                if not self._is_valid_person_name(given_name, match.start(), text):
                    # If 2-char name is invalid, try 1-char name instead
                    if len(given_name) == 2:
                        # Check if just the first char is a valid 1-char name
                        short_name = given_name[0]
                        if self._is_valid_person_name(short_name, match.start(), text):
                            # Accept the 1-char name match instead
                            sanitized = match.group(1) + "*"
                            original_short = match.group(1) + short_name
                            replacements.append({
                                "original": original_short,
                                "sanitized": sanitized,
                                "type": rule.type.value,
                            })
                            # Return the remaining char + replacement
                            return sanitized + given_name[1]
                    return original
            
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
                # 张三 → 张* (group(1)=surname, group(2)=given_name)
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
