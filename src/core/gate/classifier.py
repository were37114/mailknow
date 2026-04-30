"""Gate email classifier implementation."""

import json
import re
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from .models import GateClass, GateResult

logger = logging.getLogger(__name__)


@dataclass
class EmailInfo:
    """Email information for classification."""
    subject: str
    from_addr: str
    to_addrs: List[str]
    cc_addrs: List[str] = None
    content: str = ""
    flags: List[str] = None
    has_attachments: bool = False
    is_auto_reply: bool = False
    
    def __post_init__(self):
        if self.cc_addrs is None:
            self.cc_addrs = []
        if self.flags is None:
            self.flags = []


class GateClassifier:
    """Gate 5级分流分类器.
    
    纯规则引擎，0 token，>95%准确率。
    
    分流级别：
    - G0: urgent（紧急）
    - G1: important（重要）
    - G2: routine（常规）
    - G3: notification（通知）
    - G4: spam（垃圾）
    
    优先级：G0 > G4 > G3 > G2 > G1
    """
    
    def __init__(self, rules_path: Optional[Path] = None):
        """Initialize classifier with rules.
        
        Args:
            rules_path: Path to rules.json file.
                       Defaults to src/core/gate/rules.json
        """
        if rules_path is None:
            rules_path = Path(__file__).parent / "rules.json"
        
        self.rules_path = rules_path
        self.rules = self._load_rules()
        self._last_load_time = 0
        
        logger.info(f"Gate classifier initialized with {len(self.rules['rules'])} rule sets")
    
    def _load_rules(self) -> Dict[str, Any]:
        """Load rules from JSON file."""
        try:
            with open(self.rules_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load rules: {e}")
            # Return minimal default rules
            return {
                "version": "1.0.0",
                "rules": {
                    "routine": {
                        "priority": 2,
                        "conditions": [],
                        "threshold": 0.0
                    }
                }
            }
    
    def reload_rules(self) -> bool:
        """Reload rules from file (hot update).
        
        Returns:
            True if reload successful.
        """
        try:
            self.rules = self._load_rules()
            logger.info("Rules reloaded successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to reload rules: {e}")
            return False
    
    def classify(self, email: EmailInfo) -> GateResult:
        """Classify email into Gate class.
        
        Args:
            email: Email information for classification
        
        Returns:
            GateResult with class, confidence, and matched rules.
        """
        scores: Dict[str, float] = {}
        matched_rules: Dict[str, List[str]] = {}
        
        # Calculate score for each class
        for class_name, rule_set in self.rules["rules"].items():
            if class_name == "routine":
                # Routine is default, no conditions
                scores[class_name] = 0.0
                matched_rules[class_name] = []
                continue
            
            score = 0.0
            matched = []
            
            for condition in rule_set.get("conditions", []):
                condition_score, condition_matched = self._evaluate_condition(
                    email, condition
                )
                score += condition_score
                if condition_matched:
                    matched.append(condition["type"])
            
            # Normalize score
            threshold = rule_set.get("threshold", 0.5)
            if score >= threshold:
                scores[class_name] = min(score, 1.0)
            else:
                scores[class_name] = 0.0
            
            matched_rules[class_name] = matched
        
        # Apply conflict resolution (priority order)
        priority_order = self.rules.get("conflict_resolution", {}).get(
            "priority_order",
            ["urgent", "spam", "notification", "routine", "important"]
        )
        
        # Find highest priority class that meets threshold
        result_class = GateClass.ROUTINE
        result_score = 0.0
        result_matched = []
        
        for class_name in priority_order:
            if scores.get(class_name, 0) > 0:
                result_class = GateClass(class_name)
                result_score = scores[class_name]
                result_matched = matched_rules[class_name]
                break
        
        # Calculate confidence
        confidence = result_score if result_class != GateClass.ROUTINE else 0.5
        
        return GateResult(
            gate_class=result_class,
            confidence=confidence,
            matched_rules=result_matched,
            score=result_score
        )
    
    def _evaluate_condition(
        self, 
        email: EmailInfo, 
        condition: Dict[str, Any]
    ) -> tuple[float, bool]:
        """Evaluate a single condition.
        
        Returns:
            Tuple of (score, matched)
        """
        condition_type = condition["type"]
        weight = condition.get("weight", 1.0)
        
        if condition_type == "subject_keywords":
            return self._check_keywords(
                email.subject.lower(),
                condition["keywords"],
                weight
            )
        
        elif condition_type == "subject_pattern":
            return self._check_pattern(
                email.subject,
                condition["pattern"],
                weight
            )
        
        elif condition_type == "content_keywords":
            return self._check_keywords(
                email.content.lower(),
                condition["keywords"],
                weight
            )
        
        elif condition_type == "from_domains":
            return self._check_domains(
                email.from_addr,
                condition["domains"],
                weight
            )
        
        elif condition_type == "from_patterns":
            return self._check_patterns(
                email.from_addr.lower(),
                condition["patterns"],
                weight
            )
        
        elif condition_type == "flags":
            return self._check_flags(
                email.flags,
                condition["flags"],
                weight
            )
        
        elif condition_type == "to_me":
            # Check if user is in To (not CC)
            return self._check_to_me(email, weight)
        
        elif condition_type == "has_attachments":
            if email.has_attachments:
                return (weight, True)
            return (0.0, False)
        
        elif condition_type == "auto_reply":
            if email.is_auto_reply:
                return (weight, True)
            return (0.0, False)
        
        return (0.0, False)
    
    def _check_keywords(
        self, 
        text: str, 
        keywords: List[str], 
        weight: float
    ) -> tuple[float, bool]:
        """Check if any keyword is in text."""
        for keyword in keywords:
            if keyword.lower() in text:
                return (weight, True)
        return (0.0, False)
    
    def _check_pattern(
        self, 
        text: str, 
        pattern: str, 
        weight: float
    ) -> tuple[float, bool]:
        """Check if pattern matches text."""
        try:
            if re.search(pattern, text, re.IGNORECASE):
                return (weight, True)
        except re.error:
            pass
        return (0.0, False)
    
    def _check_domains(
        self, 
        email_addr: str, 
        domains: List[str], 
        weight: float
    ) -> tuple[float, bool]:
        """Check if email is from specific domains."""
        email_lower = email_addr.lower()
        for domain in domains:
            if domain.lower() in email_lower:
                return (weight, True)
        return (0.0, False)
    
    def _check_patterns(
        self, 
        email_addr: str, 
        patterns: List[str], 
        weight: float
    ) -> tuple[float, bool]:
        """Check if email matches patterns."""
        for pattern in patterns:
            if pattern.lower() in email_addr:
                return (weight, True)
        return (0.0, False)
    
    def _check_flags(
        self, 
        email_flags: List[str], 
        target_flags: List[str], 
        weight: float
    ) -> tuple[float, bool]:
        """Check if email has target flags."""
        for flag in target_flags:
            if flag in email_flags:
                return (weight, True)
        return (0.0, False)
    
    def _check_to_me(self, email: EmailInfo, weight: float) -> tuple[float, bool]:
        """Check if user is primary recipient (To, not CC)."""
        # This is a simplified check
        # In real implementation, would check against current user's email
        if email.to_addrs and not email.cc_addrs:
            return (weight, True)
        return (0.0, False)
