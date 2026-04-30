"""Tests for GateRulesManager: hot-reload, CRUD, versioning."""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from core.gate.classifier import GateClassifier, EmailInfo
from core.gate.rules_manager import GateRulesManager, RuleVersion, RuleChange
from core.gate.models import GateClass, GateResult


@pytest.fixture
def rules_path():
    """Create a temp rules file."""
    rules = {
        "version": "1.0.0",
        "rules": {
            "urgent": {
                "priority": 0,
                "conditions": [
                    {"type": "subject_keywords", "keywords": ["紧急", "URGENT"], "weight": 1.0},
                ],
                "threshold": 0.5,
            },
            "spam": {
                "priority": 4,
                "conditions": [
                    {"type": "subject_keywords", "keywords": ["免费", "中奖"], "weight": 0.8},
                ],
                "threshold": 0.5,
            },
            "notification": {
                "priority": 3,
                "conditions": [
                    {"type": "auto_reply", "weight": 0.9},
                ],
                "threshold": 0.5,
            },
            "important": {
                "priority": 1,
                "conditions": [
                    {"type": "to_me", "weight": 0.5},
                ],
                "threshold": 0.5,
            },
            "routine": {
                "priority": 2,
                "conditions": [],
                "threshold": 0.0,
            },
        },
        "conflict_resolution": {
            "priority_order": ["urgent", "spam", "notification", "routine", "important"]
        },
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)
        return Path(f.name)


@pytest.fixture
def classifier(rules_path):
    """Create classifier with temp rules."""
    return GateClassifier(rules_path=rules_path)


@pytest.fixture
def manager(classifier):
    """Create rules manager."""
    return GateRulesManager(classifier=classifier)


class TestRuleVersion:
    """Tests for RuleVersion dataclass."""

    def test_create_version(self):
        v = RuleVersion(
            version="1.0.0",
            rules={"test": True},
            checksum="abc123",
            created_at="2026-01-01",
            description="test",
        )
        assert v.version == "1.0.0"
        assert v.rules == {"test": True}


class TestRuleChange:
    """Tests for RuleChange dataclass."""

    def test_create_change(self):
        c = RuleChange(
            action="add",
            gate_class="spam",
            field="conditions[0]",
            new_value={"type": "from_domains", "domains": ["spam.com"]},
            timestamp="2026-01-01",
        )
        assert c.action == "add"


class TestGateRulesManager:
    """Tests for GateRulesManager."""

    def test_init_with_classifier(self, manager):
        """Test manager initializes with classifier."""
        assert manager.classifier is not None
        assert len(manager._versions) == 1
        assert manager._versions[0].version == "1.0.0"

    def test_get_rules(self, manager):
        """Test getting current rules."""
        rules = manager.get_rules()
        assert "rules" in rules
        assert "urgent" in rules["rules"]

    def test_get_gate_rules(self, manager):
        """Test getting rules for specific gate class."""
        spam_rules = manager.get_gate_rules("spam")
        assert spam_rules is not None
        assert "conditions" in spam_rules

    def test_get_nonexistent_gate_rules(self, manager):
        """Test getting rules for nonexistent gate class."""
        result = manager.get_gate_rules("nonexistent")
        assert result is None

    def test_add_condition(self, manager):
        """Test adding a condition."""
        result = manager.add_condition("spam", {
            "type": "from_domains",
            "domains": ["spam.com"],
            "weight": 0.9,
        })
        assert result is True
        
        spam_rules = manager.get_gate_rules("spam")
        assert len(spam_rules["conditions"]) == 2
        assert spam_rules["conditions"][1]["domains"] == ["spam.com"]

    def test_add_invalid_condition_no_type(self, manager):
        """Test adding condition without type fails."""
        result = manager.add_condition("spam", {"keywords": ["test"]})
        assert result is False

    def test_add_invalid_condition_bad_type(self, manager):
        """Test adding condition with unknown type fails."""
        result = manager.add_condition("spam", {"type": "unknown_type", "weight": 1.0})
        assert result is False

    def test_add_condition_to_unknown_class(self, manager):
        """Test adding condition to nonexistent class fails."""
        result = manager.add_condition("nonexistent", {"type": "subject_keywords", "keywords": ["test"]})
        assert result is False

    def test_update_condition(self, manager):
        """Test updating a condition."""
        new_condition = {"type": "subject_keywords", "keywords": ["紧急", "URGENT", "ASAP"], "weight": 1.2}
        result = manager.update_condition("urgent", 0, new_condition)
        assert result is True
        
        urgent_rules = manager.get_gate_rules("urgent")
        assert urgent_rules["conditions"][0]["keywords"] == ["紧急", "URGENT", "ASAP"]

    def test_update_condition_invalid_index(self, manager):
        """Test updating condition at invalid index fails."""
        result = manager.update_condition("urgent", 99, {"type": "to_me", "weight": 1.0})
        assert result is False

    def test_remove_condition(self, manager):
        """Test removing a condition."""
        # First add one
        manager.add_condition("spam", {
            "type": "from_domains",
            "domains": ["spam.com"],
            "weight": 0.9,
        })
        assert len(manager.get_gate_rules("spam")["conditions"]) == 2
        
        # Remove the added one
        result = manager.remove_condition("spam", 1)
        assert result is True
        assert len(manager.get_gate_rules("spam")["conditions"]) == 1

    def test_remove_condition_invalid_index(self, manager):
        """Test removing condition at invalid index fails."""
        result = manager.remove_condition("spam", 99)
        assert result is False

    def test_update_threshold(self, manager):
        """Test updating threshold."""
        result = manager.update_threshold("spam", 0.7)
        assert result is True
        assert manager.get_gate_rules("spam")["threshold"] == 0.7

    def test_update_threshold_invalid(self, manager):
        """Test updating threshold with invalid value fails."""
        result = manager.update_threshold("spam", 1.5)
        assert result is False
        
        result = manager.update_threshold("spam", -0.1)
        assert result is False

    def test_change_log(self, manager):
        """Test change log tracks modifications."""
        manager.add_condition("spam", {
            "type": "from_domains",
            "domains": ["spam.com"],
            "weight": 0.9,
        })
        manager.update_threshold("urgent", 0.8)
        
        log = manager.change_log
        assert len(log) >= 2
        assert log[0]["action"] == "add"
        assert log[0]["gate_class"] == "spam"
        assert log[1]["action"] == "update"
        assert log[1]["gate_class"] == "urgent"

    def test_save_version(self, manager):
        """Test saving a version."""
        version = manager.save_version("Test version")
        assert version == "1.0.1"
        
        versions = manager.list_versions()
        assert len(versions) == 2
        assert versions[1]["version"] == "1.0.1"

    def test_list_versions(self, manager):
        """Test listing versions."""
        versions = manager.list_versions()
        assert len(versions) == 1
        assert versions[0]["version"] == "1.0.0"

    def test_rollback(self, manager):
        """Test rollback to a previous version."""
        # Save initial state
        initial_version = manager.save_version("Before changes")
        
        # Make changes
        manager.add_condition("spam", {
            "type": "from_domains",
            "domains": ["spam.com"],
            "weight": 0.9,
        })
        manager.update_threshold("urgent", 0.9)
        
        # Verify changes applied
        assert len(manager.get_gate_rules("spam")["conditions"]) == 2
        assert manager.get_gate_rules("urgent")["threshold"] == 0.9
        
        # Rollback
        result = manager.rollback(initial_version)
        assert result is True
        
        # Verify rollback
        assert len(manager.get_gate_rules("spam")["conditions"]) == 1
        assert manager.get_gate_rules("urgent")["threshold"] == 0.5

    def test_rollback_nonexistent_version(self, manager):
        """Test rollback to nonexistent version fails."""
        result = manager.rollback("99.99.99")
        assert result is False

    def test_on_change_callback(self, manager):
        """Test change notification callback."""
        changes = []
        manager.on_change(lambda rules: changes.append(True))
        
        manager.add_condition("spam", {
            "type": "from_domains",
            "domains": ["spam.com"],
            "weight": 0.9,
        })
        
        assert len(changes) == 1

    def test_classification_after_rule_change(self, manager, classifier):
        """Test that classification changes after rule modification."""
        email = EmailInfo(
            subject="来自spam.com的邮件",
            from_addr="test@spam.com",
            to_addrs=["me@company.com"],
        )
        
        # Before: should be routine (no spam domain rule)
        result1 = classifier.classify(email)
        assert result1.gate_class != GateClass.SPAM
        
        # Add spam domain rule
        manager.add_condition("spam", {
            "type": "from_domains",
            "domains": ["spam.com"],
            "weight": 0.9,
        })
        
        # After: should be spam
        result2 = classifier.classify(email)
        assert result2.gate_class == GateClass.SPAM

    def test_check_and_reload_no_change(self, manager):
        """Test check_and_reload when file hasn't changed."""
        result = manager.check_and_reload()
        assert result is False

    def test_check_and_reload_with_file_change(self, manager, rules_path):
        """Test check_and_reload when file is modified externally."""
        # Modify the file
        with open(rules_path, 'r', encoding='utf-8') as f:
            rules = json.load(f)
        
        rules["rules"]["spam"]["conditions"].append({
            "type": "from_domains",
            "domains": ["newspam.com"],
            "weight": 0.8,
        })
        
        with open(rules_path, 'w', encoding='utf-8') as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)
        
        # Check and reload
        result = manager.check_and_reload()
        assert result is True
        
        # Verify new rule is loaded
        spam_rules = manager.get_gate_rules("spam")
        assert len(spam_rules["conditions"]) == 2
