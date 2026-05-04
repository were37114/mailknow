"""Gate rules hot-reload manager.

Features:
1. Watch rules.json for file changes (auto-reload)
2. CRUD API for runtime rule modifications
3. Version tracking and rollback support
4. Rule validation before applying
5. Persist custom rules to database
"""

import copy
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from db.pgpool import SQLitePool

from .classifier import GateClassifier
from .models import GateClass

logger = logging.getLogger(__name__)


@dataclass
class RuleVersion:
    """A versioned snapshot of gate rules."""
    version: str
    rules: Dict[str, Any]
    checksum: str
    created_at: str
    description: str = ""


@dataclass
class RuleChange:
    """A single rule change."""
    action: str  # add, update, delete
    gate_class: str
    field: str  # conditions, threshold, priority
    old_value: Any = None
    new_value: Any = None
    timestamp: str = ""


class GateRulesManager:
    """Manage Gate rules with hot-reload capability.

    Usage:
        manager = GateRulesManager(classifier, db)
        await manager.start()  # Start file watcher

        # CRUD operations
        manager.add_condition("spam", {"type": "from_domains", "domains": ["spam.com"], "weight": 0.9})
        manager.update_threshold("important", 0.6)
        manager.remove_condition("spam", 2)  # Remove condition at index 2

        # Version control
        manager.save_version("Added spam domain")
        versions = manager.list_versions()
        manager.rollback("1.0.3")
    """

    RULES_TABLE = "gate_rules_versions"

    def __init__(
        self,
        classifier: GateClassifier,
        db: Optional[SQLitePool] = None,
        watch_interval: float = 5.0,
    ):
        """Initialize rules manager.

        Args:
            classifier: Gate classifier instance
            db: Optional database pool for persistence
            watch_interval: Seconds between file change checks
        """
        self.classifier = classifier
        self.db = db
        self.watch_interval = watch_interval
        self._last_checksum = ""
        self._versions: List[RuleVersion] = []
        self._change_log: List[RuleChange] = []
        self._watching = False
        self._callbacks: List[Callable] = []

        # Calculate initial checksum
        self._last_checksum = self._compute_checksum(classifier.rules)

        # Record initial version
        self._versions.append(RuleVersion(
            version="1.0.0",
            rules=classifier.rules,
            checksum=self._last_checksum,
            created_at=datetime.now(timezone.utc).isoformat(),
            description="Initial rules",
        ))

    def _compute_checksum(self, rules: Dict[str, Any]) -> str:
        """Compute checksum of rules for change detection."""
        rules_json = json.dumps(rules, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(rules_json.encode()).hexdigest()

    # ---- CRUD Operations ----

    def add_condition(self, gate_class: str, condition: Dict[str, Any]) -> bool:
        """Add a condition to a gate class rule set.

        Args:
            gate_class: Target gate class (e.g. "spam", "urgent")
            condition: Condition dict with type, keywords/patterns/domains, weight

        Returns:
            True if added successfully
        """
        try:
            if gate_class not in self.classifier.rules.get("rules", {}):
                logger.warning(f"Unknown gate class: {gate_class}")
                return False

            conditions = self.classifier.rules["rules"][gate_class].get("conditions", [])

            # Validate condition
            if not self._validate_condition(condition):
                logger.warning(f"Invalid condition: {condition}")
                return False

            conditions.append(condition)
            self.classifier.rules["rules"][gate_class]["conditions"] = conditions

            self._log_change("add", gate_class, f"conditions[{len(conditions)-1}]", None, condition)
            self._notify_change()
            return True

        except Exception as e:
            logger.error(f"Failed to add condition: {e}")
            return False

    def update_condition(self, gate_class: str, index: int, condition: Dict[str, Any]) -> bool:
        """Update a condition at specific index.

        Args:
            gate_class: Target gate class
            index: Condition index
            condition: New condition dict

        Returns:
            True if updated successfully
        """
        try:
            conditions = self.classifier.rules["rules"][gate_class].get("conditions", [])
            if index < 0 or index >= len(conditions):
                logger.warning(f"Invalid condition index: {index}")
                return False

            old_condition = conditions[index]
            conditions[index] = condition

            self._log_change("update", gate_class, f"conditions[{index}]", old_condition, condition)
            self._notify_change()
            return True

        except Exception as e:
            logger.error(f"Failed to update condition: {e}")
            return False

    def remove_condition(self, gate_class: str, index: int) -> bool:
        """Remove a condition at specific index.

        Args:
            gate_class: Target gate class
            index: Condition index to remove

        Returns:
            True if removed successfully
        """
        try:
            conditions = self.classifier.rules["rules"][gate_class].get("conditions", [])
            if index < 0 or index >= len(conditions):
                logger.warning(f"Invalid condition index: {index}")
                return False

            old_condition = conditions.pop(index)

            self._log_change("delete", gate_class, f"conditions[{index}]", old_condition, None)
            self._notify_change()
            return True

        except Exception as e:
            logger.error(f"Failed to remove condition: {e}")
            return False

    def update_threshold(self, gate_class: str, threshold: float) -> bool:
        """Update threshold for a gate class.

        Args:
            gate_class: Target gate class
            threshold: New threshold value (0.0 - 1.0)

        Returns:
            True if updated successfully
        """
        try:
            if not 0.0 <= threshold <= 1.0:
                logger.warning(f"Invalid threshold: {threshold}")
                return False

            old_threshold = self.classifier.rules["rules"][gate_class].get("threshold", 0.5)
            self.classifier.rules["rules"][gate_class]["threshold"] = threshold

            self._log_change("update", gate_class, "threshold", old_threshold, threshold)
            self._notify_change()
            return True

        except Exception as e:
            logger.error(f"Failed to update threshold: {e}")
            return False

    def get_rules(self) -> Dict[str, Any]:
        """Get current rules."""
        return self.classifier.rules

    def get_gate_rules(self, gate_class: str) -> Optional[Dict[str, Any]]:
        """Get rules for a specific gate class."""
        return self.classifier.rules.get("rules", {}).get(gate_class)

    # ---- File Watcher ----

    def check_and_reload(self) -> bool:
        """Check if rules file changed and reload.

        Returns:
            True if reloaded (file changed)
        """
        current_checksum = self._compute_checksum(self.classifier.rules)

        # Read file to check for external changes
        try:
            with open(self.classifier.rules_path, 'r', encoding='utf-8') as f:
                file_rules = json.load(f)
            file_checksum = self._compute_checksum(file_rules)

            if file_checksum != current_checksum:
                logger.info("Rules file changed externally, reloading...")
                self.classifier.rules = file_rules
                self._last_checksum = file_checksum

                self._versions.append(RuleVersion(
                    version=self._next_version(),
                    rules=file_rules,
                    checksum=file_checksum,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    description="Auto-reload from file change",
                ))

                self._notify_change()
                return True

        except Exception as e:
            logger.error(f"Failed to check/reload rules: {e}")

        return False

    # ---- Version Control ----

    def save_version(self, description: str = "") -> str:
        """Save current rules as a new version.

        Args:
            description: Version description

        Returns:
            Version string
        """
        checksum = self._compute_checksum(self.classifier.rules)
        version = self._next_version()

        self._versions.append(RuleVersion(
            version=version,
            rules=copy.deepcopy(self.classifier.rules),
            checksum=checksum,
            created_at=datetime.now(timezone.utc).isoformat(),
            description=description,
        ))

        self._last_checksum = checksum

        # Persist to database if available
        if self.db:
            self._persist_version(version, self.classifier.rules, description)

        logger.info(f"Saved rules version {version}: {description}")
        return version

    def list_versions(self) -> List[Dict[str, Any]]:
        """List all saved versions."""
        return [
            {
                "version": v.version,
                "checksum": v.checksum,
                "created_at": v.created_at,
                "description": v.description,
            }
            for v in self._versions
        ]

    def rollback(self, version: str) -> bool:
        """Rollback to a specific version.

        Args:
            version: Version string to rollback to

        Returns:
            True if rollback successful
        """
        target = None
        for v in self._versions:
            if v.version == version:
                target = v
                break

        if not target:
            logger.warning(f"Version {version} not found")
            return False

        # Save current state before rollback
        current_checksum = self._compute_checksum(self.classifier.rules)

        # Apply target version (deep copy to avoid shared references)
        self.classifier.rules = copy.deepcopy(target.rules)
        self._last_checksum = target.checksum

        # Also write to file
        try:
            with open(self.classifier.rules_path, 'w', encoding='utf-8') as f:
                json.dump(target.rules, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to write rules file: {e}")

        self._versions.append(RuleVersion(
            version=self._next_version(),
            rules=target.rules,
            checksum=target.checksum,
            created_at=datetime.now(timezone.utc).isoformat(),
            description=f"Rollback to {version}",
        ))

        logger.info(f"Rolled back to version {version}")
        return True

    # ---- Change Notifications ----

    def on_change(self, callback: Callable):
        """Register callback for rule changes."""
        self._callbacks.append(callback)

    def _notify_change(self):
        """Notify all registered callbacks."""
        for callback in self._callbacks:
            try:
                callback(self.classifier.rules)
            except Exception as e:
                logger.warning(f"Change callback error: {e}")

    # ---- Validation ----

    def _validate_condition(self, condition: Dict[str, Any]) -> bool:
        """Validate a condition dict."""
        if "type" not in condition:
            return False

        valid_types = {
            "subject_keywords", "subject_pattern", "content_keywords",
            "from_domains", "from_patterns", "flags", "to_me",
            "has_attachments", "auto_reply",
        }

        if condition["type"] not in valid_types:
            return False

        # Type-specific validation
        cond_type = condition["type"]
        if cond_type in ("subject_keywords", "content_keywords"):
            if "keywords" not in condition or not condition["keywords"]:
                return False
        elif cond_type == "subject_pattern":
            if "pattern" not in condition:
                return False
        elif cond_type == "from_domains":
            if "domains" not in condition or not condition["domains"]:
                return False
        elif cond_type == "from_patterns":
            if "patterns" not in condition:
                return False
        elif cond_type == "flags":
            if "flags" not in condition or not condition["flags"]:
                return False

        return True

    # ---- Helpers ----

    def _next_version(self) -> str:
        """Generate next version number."""
        if not self._versions:
            return "1.0.0"

        last = self._versions[-1].version
        parts = last.split(".")
        patch = int(parts[-1]) + 1
        return f"{'.'.join(parts[:-1])}.{patch}"

    def _log_change(
        self,
        action: str,
        gate_class: str,
        field_name: str,
        old_value: Any,
        new_value: Any,
    ):
        """Log a rule change."""
        self._change_log.append(RuleChange(
            action=action,
            gate_class=gate_class,
            field=field_name,
            old_value=old_value,
            new_value=new_value,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))

    async def _persist_version(self, version: str, rules: Dict, description: str):
        """Persist version to database."""
        if not self.db:
            return

        try:
            import json as json_mod
            conn = await self.db.get_connection()
            await conn.execute(
                """CREATE TABLE IF NOT EXISTS gate_rules_versions (
                    version TEXT PRIMARY KEY,
                    rules TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                )"""
            )
            await conn.execute(
                """INSERT OR REPLACE INTO gate_rules_versions
                   (version, rules, checksum, description, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    version,
                    json_mod.dumps(rules, ensure_ascii=False),
                    self._compute_checksum(rules),
                    description,
                    datetime.now(timezone.utc).isoformat(),
                )
            )
            await conn.commit()
        except Exception as e:
            logger.warning(f"Failed to persist version: {e}")

    @property
    def change_log(self) -> List[Dict[str, Any]]:
        """Get change log."""
        return [
            {
                "action": c.action,
                "gate_class": c.gate_class,
                "field": c.field,
                "timestamp": c.timestamp,
            }
            for c in self._change_log
        ]
