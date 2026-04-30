"""Data integrity checks - daily scan.

V5.2 spec:
- Daily scan for data consistency
- EXCLUDE gate_class IN ('spam', 'notification') - they naturally have no links
- Check orphan pages, broken links, stale entities
- Report issues and auto-fix where possible
"""

import json
import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class IntegrityIssueType(str, Enum):
    """Types of integrity issues."""
    ORPHAN_PAGE = "orphan_page"               # Page with no links
    BROKEN_LINK_SOURCE = "broken_link_source"  # Link source doesn't exist
    BROKEN_LINK_TARGET = "broken_link_target"  # Link target doesn't exist
    STALE_ENTITY = "stale_entity"              # Entity with no links for 30+ days
    MISSING_ENTITY_PAGE = "missing_entity_page" # Entity referenced but page missing
    DUPLICATE_ENTITY = "duplicate_entity"       # Potential duplicate entities
    EMPTY_METADATA = "empty_metadata"           # Email page with empty metadata


@dataclass
class IntegrityIssue:
    """An integrity issue found during scan."""
    issue_type: IntegrityIssueType
    severity: str = "medium"  # low/medium/high
    description: str = ""
    affected_id: str = ""
    suggested_fix: str = ""
    auto_fixable: bool = False
    fixed: bool = False


@dataclass
class IntegrityReport:
    """Result of an integrity scan."""
    scan_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    total_pages: int = 0
    total_links: int = 0
    total_entities: int = 0
    issues: List[IntegrityIssue] = field(default_factory=list)
    issues_by_type: Dict[str, int] = field(default_factory=dict)
    issues_by_severity: Dict[str, int] = field(default_factory=dict)
    auto_fixed: int = 0
    scan_duration_ms: float = 0.0
    
    @property
    def has_critical(self) -> bool:
        return any(i.severity == "critical" for i in self.issues)


class IntegrityChecker:
    """Data integrity checker.
    
    V5.2 important rule:
    - spam/notification emails naturally have no links
    - Don't report them as orphan pages
    - Only check important/urgent/routine emails
    """
    
    # Gate classes that naturally have no links - exclude from orphan check
    EXCLUDED_GATE_CLASSES = {"spam", "notification"}
    
    def __init__(self, db=None):
        self.db = db
    
    async def check(self, auto_fix: bool = False) -> IntegrityReport:
        """Run integrity check.
        
        Args:
            auto_fix: Auto-fix issues where possible
            
        Returns:
            Integrity report
        """
        start = datetime.now(timezone.utc)
        report = IntegrityReport()
        
        if not self.db:
            logger.warning("No database available for integrity check")
            return report
        
        try:
            conn = await self.db.get_connection()
            
            # Count totals
            cursor = await conn.execute("SELECT COUNT(*) FROM pages")
            row = await cursor.fetchone()
            report.total_pages = row[0] if row else 0
            
            cursor = await conn.execute("SELECT COUNT(*) FROM links")
            row = await cursor.fetchone()
            report.total_links = row[0] if row else 0
            
            cursor = await conn.execute("SELECT COUNT(*) FROM entities")
            row = await cursor.fetchone()
            report.total_entities = row[0] if row else 0
            
            # Check 1: Orphan pages (EXCLUDE spam/notification)
            await self._check_orphan_pages(conn, report, auto_fix)
            
            # Check 2: Broken links
            await self._check_broken_links(conn, report, auto_fix)
            
            # Check 3: Stale entities
            await self._check_stale_entities(conn, report)
            
            # Check 4: Missing entity pages
            await self._check_missing_entity_pages(conn, report, auto_fix)
            
            # Check 5: Empty metadata
            await self._check_empty_metadata(conn, report)
            
            await conn.commit()
            
        except Exception as e:
            logger.error(f"Integrity check failed: {e}")
        
        # Summarize
        for issue in report.issues:
            report.issues_by_type[issue.issue_type.value] = \
                report.issues_by_type.get(issue.issue_type.value, 0) + 1
            report.issues_by_severity[issue.severity] = \
                report.issues_by_severity.get(issue.severity, 0) + 1
        
        report.auto_fixed = len([i for i in report.issues if i.fixed])
        report.scan_duration_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        
        logger.info(
            f"Integrity check: {len(report.issues)} issues "
            f"({report.auto_fixed} auto-fixed) in {report.scan_duration_ms:.0f}ms"
        )
        
        return report
    
    async def _check_orphan_pages(self, conn, report: IntegrityReport, auto_fix: bool):
        """Check for pages with no links (excluding spam/notification)."""
        # Find email pages that should have links but don't
        cursor = await conn.execute("""
            SELECT p.id, p.gate_class
            FROM pages p
            WHERE p.type = 'email'
              AND p.gate_class NOT IN ('spam', 'notification')
              AND NOT EXISTS (
                  SELECT 1 FROM links l
                  WHERE l.source_id = p.id OR l.target_id = p.id
              )
        """)
        
        rows = await cursor.fetchall()
        for row in rows:
            page_id, gate_class = row[0], row[1]
            report.issues.append(IntegrityIssue(
                issue_type=IntegrityIssueType.ORPHAN_PAGE,
                severity="low",
                description=f"邮件 {page_id} (gate={gate_class}) 没有任何链接",
                affected_id=page_id,
                suggested_fix="重新运行 Tier1-2 提取",
                auto_fixable=False,
            ))
    
    async def _check_broken_links(self, conn, report: IntegrityReport, auto_fix: bool):
        """Check for links with non-existent source or target."""
        # Broken source
        cursor = await conn.execute("""
            SELECT l.id, l.source_id
            FROM links l
            WHERE NOT EXISTS (SELECT 1 FROM pages p WHERE p.id = l.source_id)
        """)
        
        rows = await cursor.fetchall()
        for row in rows:
            link_id, source_id = row[0], row[1]
            issue = IntegrityIssue(
                issue_type=IntegrityIssueType.BROKEN_LINK_SOURCE,
                severity="high",
                description=f"链接 {link_id} 的源 {source_id} 不存在",
                affected_id=link_id,
                suggested_fix="删除孤立链接",
                auto_fixable=True,
            )
            
            if auto_fix:
                await conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
                issue.fixed = True
            
            report.issues.append(issue)
        
        # Broken target (NULL target is OK - stub)
        cursor = await conn.execute("""
            SELECT l.id, l.target_id
            FROM links l
            WHERE l.target_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM pages p WHERE p.id = l.target_id)
        """)
        
        rows = await cursor.fetchall()
        for row in rows:
            link_id, target_id = row[0], row[1]
            issue = IntegrityIssue(
                issue_type=IntegrityIssueType.BROKEN_LINK_TARGET,
                severity="medium",
                description=f"链接 {link_id} 的目标 {target_id} 不存在",
                affected_id=link_id,
                suggested_fix="创建stub页面或删除链接",
                auto_fixable=True,
            )
            
            if auto_fix:
                # Create stub page for the target
                page_type = target_id.split(":")[0] if ":" in target_id else "unknown"
                name = target_id.split(":", 1)[1] if ":" in target_id else target_id
                await conn.execute(
                    "INSERT OR IGNORE INTO pages (id, type, content, metadata, created_at, updated_at) VALUES (?, ?, ?, '{}', ?, ?)",
                    (target_id, page_type, name, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat())
                )
                issue.fixed = True
            
            report.issues.append(issue)
    
    async def _check_stale_entities(self, conn, report: IntegrityReport):
        """Check for entities with no recent links."""
        cursor = await conn.execute("""
            SELECT e.id, e.name, MAX(p.updated_at) as last_activity
            FROM entities e
            LEFT JOIN links l ON l.target_id = e.id
            LEFT JOIN pages p ON p.id = l.source_id
            GROUP BY e.id
            HAVING last_activity IS NULL OR last_activity < datetime('now', '-30 days')
        """)
        
        rows = await cursor.fetchall()
        for row in rows:
            entity_id, name, last_activity = row[0], row[1], row[2]
            report.issues.append(IntegrityIssue(
                issue_type=IntegrityIssueType.STALE_ENTITY,
                severity="low",
                description=f"实体 {name} ({entity_id}) 30天无活动",
                affected_id=entity_id,
                suggested_fix="可考虑归档",
                auto_fixable=False,
            ))
    
    async def _check_missing_entity_pages(self, conn, report: IntegrityReport, auto_fix: bool):
        """Check for entities referenced in links but missing from entities table."""
        cursor = await conn.execute("""
            SELECT DISTINCT l.target_id
            FROM links l
            WHERE l.target_id LIKE 'person:%'
              AND NOT EXISTS (SELECT 1 FROM entities e WHERE e.id = l.target_id)
        """)
        
        rows = await cursor.fetchall()
        for row in rows:
            entity_id = row[0]
            name = entity_id.split(":", 1)[1] if ":" in entity_id else entity_id
            issue = IntegrityIssue(
                issue_type=IntegrityIssueType.MISSING_ENTITY_PAGE,
                severity="medium",
                description=f"实体 {entity_id} 在链接中被引用但不存在于entities表",
                affected_id=entity_id,
                suggested_fix="创建实体记录",
                auto_fixable=True,
            )
            
            if auto_fix:
                await conn.execute(
                    "INSERT OR IGNORE INTO entities (id, type, name, attributes, created_at, updated_at) VALUES (?, 'person', ?, '{}', ?, ?)",
                    (entity_id, name, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat())
                )
                issue.fixed = True
            
            report.issues.append(issue)
    
    async def _check_empty_metadata(self, conn, report: IntegrityReport):
        """Check for email pages with empty metadata."""
        cursor = await conn.execute("""
            SELECT id FROM pages
            WHERE type = 'email' AND (metadata IS NULL OR metadata = '' OR metadata = '{}')
        """)
        
        rows = await cursor.fetchall()
        for row in rows:
            report.issues.append(IntegrityIssue(
                issue_type=IntegrityIssueType.EMPTY_METADATA,
                severity="low",
                description=f"邮件 {row[0]} 没有元数据",
                affected_id=row[0],
                suggested_fix="重新同步该邮件",
                auto_fixable=False,
            ))
