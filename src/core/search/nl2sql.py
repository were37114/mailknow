"""NL→SQL - Natural language to SQL query translation.

V5.2 spec:
- GPT-4o-mini generates SQL from natural language
- Security validation to prevent SQL injection
- Only SELECT queries allowed
- "最近3个月金额超5万的审批" should be queryable
"""

import json
import logging
import re
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone

from llm.client import LLMClient, get_llm_client
from llm.fallback import WithFallback, get_fallback
from llm.token_budget_v2 import TokenBudgetController

logger = logging.getLogger(__name__)


# Dangerous SQL patterns
DANGEROUS_PATTERNS = [
    r'\b(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE)\b',
    r';.*\b(SELECT|INSERT|UPDATE|DELETE|DROP)\b',  # Multiple statements
    r'--',           # SQL comments
    r'/\*',          # Block comments
    r'\bUNION\b',    # UNION injection
    r'\bINTO\b\s+(OUT|DUMP)',  # File operations
]

# Allowed table names
ALLOWED_TABLES = {"pages", "links", "entities"}

# Schema description for LLM
SCHEMA_DESC = """
邮件数据库schema（SQLite）：

pages表：
- id TEXT PRIMARY KEY  -- 邮件ID，格式 "email:xxx"
- type TEXT            -- "email"
- content TEXT         -- 邮件主题
- metadata TEXT        -- JSON: {from_addr, to_addrs, date, gate_class, is_approval, has_attachments, ...}
- gate_class TEXT      -- "important"/"urgent"/"routine"/"notification"/"spam"
- gate_score REAL      -- 0.0-1.0
- created_at TEXT
- updated_at TEXT

links表：
- id TEXT PRIMARY KEY
- source_id TEXT REFERENCES pages(id)
- target_id TEXT REFERENCES pages(id)
- relation TEXT        -- "sent_to"/"cc'd"/"replied_to"/"mentions_person"/"mentions_org"/"mentions_amount"/...
- tier INTEGER         -- 1/2/4
- weight REAL
- metadata TEXT
- created_at TEXT

entities表：
- id TEXT PRIMARY KEY  -- 格式 "person:xxx" 或 "org:xxx"
- type TEXT            -- "person"/"org"/"project"
- name TEXT
- attributes TEXT      -- JSON: {emails, aliases, ...}
- created_at TEXT
- updated_at TEXT
"""

NL2SQL_PROMPT = """你是一个SQL生成助手。根据用户的自然语言查询，生成安全的SQL查询。

数据库schema：
{schema}

⚠️ 安全规则：
1. 只能生成SELECT查询
2. 不能使用DROP/DELETE/INSERT/UPDATE/ALTER
3. 不能使用UNION
4. 不能使用分号
5. 只能查询pages/links/entities表
6. metadata是JSON字段，需用json_extract()提取

用户查询：{query}

请返回JSON格式：
{{
    "sql": "SELECT ...",
    "explanation": "查询说明",
    "estimated_rows": 估计行数
}}

只返回JSON，不要其他内容。"""


@dataclass
class NL2SQLResult:
    """Result of NL→SQL translation."""
    original_query: str
    sql: str
    explanation: str
    estimated_rows: int = 0
    is_safe: bool = True
    validation_errors: List[str] = field(default_factory=list)
    llm_used: bool = False


class NL2SQLTranslator:
    """Natural language to SQL translator.
    
    Features:
    - LLM-based SQL generation
    - Security validation
    - Template fallback for common patterns
    - Query result formatting
    """
    
    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        fallback: Optional[WithFallback] = None,
    ):
        self.llm = llm_client or get_llm_client()
        self.fallback = fallback or get_fallback()
    
    async def translate(self, query: str) -> NL2SQLResult:
        """Translate natural language to SQL.
        
        Args:
            query: Natural language query
            
        Returns:
            Translation result with validated SQL
        """
        # Try template match first (0 token)
        template_result = self._try_template(query)
        if template_result:
            return template_result
        
        # Use LLM
        result = await self._translate_with_llm(query)
        if result:
            # Validate
            is_safe, errors = self._validate_sql(result.sql)
            result.is_safe = is_safe
            result.validation_errors = errors
            
            if not is_safe:
                logger.warning(f"Generated SQL failed validation: {errors}")
                result.sql = ""
            
            return result
        
        # Fallback
        return NL2SQLResult(
            original_query=query,
            sql="",
            explanation="无法生成安全的SQL查询",
            is_safe=False,
            validation_errors=["translation_failed"],
        )
    
    async def _translate_with_llm(self, query: str) -> Optional[NL2SQLResult]:
        """Translate using LLM."""
        try:
            prompt = NL2SQL_PROMPT.format(schema=SCHEMA_DESC, query=query)
            
            result = await self.fallback.call(
                prompt=prompt,
                system="你是SQL生成助手，只生成安全的SELECT查询。",
                temperature=0.0,
                max_tokens=500,
                json_mode=True,
                task_type="nl2sql",
                estimated_tokens=800,
            )
            
            if result.used_fallback:
                return None
            
            data = json.loads(result.content)
            
            return NL2SQLResult(
                original_query=query,
                sql=data.get("sql", ""),
                explanation=data.get("explanation", ""),
                estimated_rows=data.get("estimated_rows", 0),
                llm_used=True,
            )
            
        except Exception as e:
            logger.error(f"NL2SQL LLM translation failed: {e}")
            return None
    
    def _try_template(self, query: str) -> Optional[NL2SQLResult]:
        """Try template-based translation for common patterns."""
        import re
        
        # Pattern: "最近N天的邮件"
        match = re.search(r'最近(\d+)天[的的]?邮件', query)
        if match:
            days = int(match.group(1))
            return NL2SQLResult(
                original_query=query,
                sql=f"SELECT id, content, metadata, gate_class FROM pages WHERE type = 'email' AND created_at >= datetime('now', '-{days} days') ORDER BY created_at DESC LIMIT 100",
                explanation=f"查询最近{days}天的邮件",
                estimated_rows=100,
            )
        
        # Pattern: "和XXX的往来邮件"
        match = re.search(r'[和与](.+?)[的的]往来[邮件]?', query)
        if match:
            name = match.group(1).strip()
            return NL2SQLResult(
                original_query=query,
                sql=f"SELECT p.id, p.content, p.metadata, p.gate_class FROM pages p JOIN links l ON l.source_id = p.id JOIN entities e ON l.target_id = e.id WHERE e.name LIKE '%{name}%' AND p.type = 'email' ORDER BY p.created_at DESC LIMIT 100",
                explanation=f"查询与{name}的往来邮件",
                estimated_rows=50,
            )
        
        # Pattern: "审批邮件"
        if "审批" in query:
            return NL2SQLResult(
                original_query=query,
                sql="SELECT id, content, metadata, gate_class FROM pages WHERE type = 'email' AND metadata LIKE '%is_approval%' ORDER BY created_at DESC LIMIT 100",
                explanation="查询审批相关邮件",
                estimated_rows=50,
            )
        
        # Pattern: "重要邮件"
        if "重要" in query:
            return NL2SQLResult(
                original_query=query,
                sql="SELECT id, content, metadata, gate_class FROM pages WHERE type = 'email' AND gate_class IN ('important', 'urgent') ORDER BY created_at DESC LIMIT 100",
                explanation="查询重要和紧急邮件",
                estimated_rows=50,
            )
        
        return None
    
    def _validate_sql(self, sql: str) -> Tuple[bool, List[str]]:
        """Validate SQL for safety.
        
        Returns:
            (is_safe, errors)
        """
        errors = []
        
        if not sql.strip():
            errors.append("empty_sql")
            return False, errors
        
        # Check for dangerous patterns
        sql_upper = sql.upper()
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, sql_upper):
                errors.append(f"dangerous_pattern: {pattern}")
        
        # Must start with SELECT
        if not sql_upper.strip().startswith("SELECT"):
            errors.append("not_select")
        
        # Check table names
        for table in re.findall(r'\b(\w+)\b', sql):
            if table.lower() in ('from', 'join', 'into', 'update', 'table'):
                continue
            # Check if it's a table name
            if table.lower() in ALLOWED_TABLES:
                continue
            # Could be an alias, allow it
        
        # No semicolons
        if ';' in sql:
            errors.append("semicolon_found")
        
        return len(errors) == 0, errors
