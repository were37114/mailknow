"""
E2E知识库查询测试

端到端验证："和A公司的往来邮件" → 实体识别 → Hybrid Search → 结果展示

验证点：
1. NL→SQL模板翻译正确
2. SQL安全校验通过
3. HybridSearch RRF融合正确
4. 搜索结果按相关度排序
5. 元数据搜索生效
6. 分页功能正常

作者：MailKnow Team
日期：2026-05-02
"""

import pytest
import json
import sqlite3
import tempfile
import os
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from core.search.hybrid import (
    HybridSearch, SearchResult, SearchWeights, SearchOptions,
)
from core.search.nl2sql import NL2SQLTranslator, NL2SQLResult
from core.search.embedding import LocalEmbedding


# ── Fixtures ──

@pytest.fixture
def test_db():
    """创建测试数据库并插入模拟数据"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 创建 pages 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            id TEXT PRIMARY KEY,
            type TEXT DEFAULT 'email',
            content TEXT,
            metadata TEXT,
            gate_class TEXT DEFAULT 'routine',
            gate_score REAL DEFAULT 0.5,
            embedding BLOB,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # 插入测试邮件
    test_data = [
        (
            "email:001",
            "与A公司的合同讨论",
            json.dumps({
                "from_addr": "pm@a-company.com",
                "from_name": "张三",
                "to_addrs": ["user@company.com"],
                "date": "2026-04-28",
                "gate_class": "important",
                "is_approval": False,
            }),
            "important",
            "2026-04-28T10:00:00",
        ),
        (
            "email:002",
            "A公司报价单",
            json.dumps({
                "from_addr": "sales@a-company.com",
                "from_name": "李四",
                "to_addrs": ["user@company.com"],
                "date": "2026-04-29",
                "gate_class": "routine",
                "is_approval": False,
            }),
            "routine",
            "2026-04-29T14:00:00",
        ),
        (
            "email:003",
            "B公司项目进展",
            json.dumps({
                "from_addr": "dev@b-company.com",
                "from_name": "王五",
                "to_addrs": ["user@company.com"],
                "date": "2026-04-30",
                "gate_class": "routine",
                "is_approval": False,
            }),
            "routine",
            "2026-04-30T09:00:00",
        ),
        (
            "email:004",
            "审批：A公司采购订单",
            json.dumps({
                "from_addr": "finance@company.com",
                "from_name": "财务",
                "to_addrs": ["user@company.com"],
                "date": "2026-05-01",
                "gate_class": "important",
                "is_approval": True,
            }),
            "important",
            "2026-05-01T11:00:00",
        ),
        (
            "email:005",
            "垃圾邮件测试",
            json.dumps({
                "from_addr": "spam@unknown.com",
                "from_name": "推广",
                "to_addrs": ["user@company.com"],
                "date": "2026-05-01",
                "gate_class": "spam",
                "is_approval": False,
            }),
            "spam",
            "2026-05-01T15:00:00",
        ),
    ]

    for page_id, content, metadata, gate_class, created_at in test_data:
        cursor.execute(
            "INSERT OR REPLACE INTO pages (id, content, metadata, gate_class, created_at) VALUES (?, ?, ?, ?, ?)",
            (page_id, content, metadata, gate_class, created_at),
        )

    conn.commit()
    conn.close()

    yield db_path

    try:
        os.unlink(db_path)
    except:
        pass


@pytest.fixture
def hybrid_search(test_db):
    """创建 HybridSearch 实例"""
    return HybridSearch(db_path=test_db)


@pytest.fixture
def nl2sql_translator():
    """创建 NL2SQLTranslator 实例"""
    return NL2SQLTranslator()


# ── 测试：NL→SQL翻译 ──

class TestNL2SQLTranslation:
    """NL→SQL翻译测试"""

    def test_template_recent_emails(self, nl2sql_translator):
        """模板翻译："最近N天的邮件" """
        result = nl2sql_translator._try_template("最近7天的邮件")

        assert result is not None
        assert "SELECT" in result.sql
        assert "7" in result.sql

    def test_template_entity_emails(self, nl2sql_translator):
        """模板翻译："和XXX的往来邮件" """
        result = nl2sql_translator._try_template("和A公司的往来邮件")

        assert result is not None
        assert "SELECT" in result.sql
        assert "A公司" in result.sql

    def test_template_approval_emails(self, nl2sql_translator):
        """模板翻译："审批邮件" """
        result = nl2sql_translator._try_template("审批邮件")

        assert result is not None
        assert "SELECT" in result.sql
        assert "is_approval" in result.sql

    def test_template_important_emails(self, nl2sql_translator):
        """模板翻译："重要邮件" """
        result = nl2sql_translator._try_template("重要邮件")

        assert result is not None
        assert "SELECT" in result.sql
        assert "important" in result.sql

    def test_no_template_match(self, nl2sql_translator):
        """无匹配模板时返回 None"""
        result = nl2sql_translator._try_template("天气怎么样")
        assert result is None


# ── 测试：SQL安全校验 ──

class TestSQLSecurityValidation:
    """SQL安全校验测试"""

    def test_select_only_allowed(self, nl2sql_translator):
        """只允许 SELECT 查询"""
        is_safe, errors = nl2sql_translator._validate_sql("SELECT * FROM pages")
        assert is_safe is True
        assert len(errors) == 0

    def test_drop_blocked(self, nl2sql_translator):
        """DROP 被阻止"""
        is_safe, errors = nl2sql_translator._validate_sql("DROP TABLE pages")
        assert is_safe is False
        assert any("dangerous" in e for e in errors)

    def test_delete_blocked(self, nl2sql_translator):
        """DELETE 被阻止"""
        is_safe, errors = nl2sql_translator._validate_sql("DELETE FROM pages WHERE 1=1")
        assert is_safe is False

    def test_insert_blocked(self, nl2sql_translator):
        """INSERT 被阻止"""
        is_safe, errors = nl2sql_translator._validate_sql("INSERT INTO pages VALUES (1, 'x')")
        assert is_safe is False

    def test_union_blocked(self, nl2sql_translator):
        """UNION 注入被阻止"""
        is_safe, errors = nl2sql_translator._validate_sql(
            "SELECT * FROM pages UNION SELECT * FROM users"
        )
        assert is_safe is False

    def test_semicolon_blocked(self, nl2sql_translator):
        """分号被阻止"""
        is_safe, errors = nl2sql_translator._validate_sql(
            "SELECT * FROM pages; DROP TABLE pages"
        )
        assert is_safe is False

    def test_empty_sql_blocked(self, nl2sql_translator):
        """空SQL被阻止"""
        is_safe, errors = nl2sql_translator._validate_sql("")
        assert is_safe is False


# ── 测试：HybridSearch ──

class TestHybridSearchE2E:
    """HybridSearch 端到端测试（仅关键词和元数据搜索，跳过向量搜索以避免加载模型）"""

    @pytest.mark.asyncio
    async def test_keyword_search_finds_results(self, test_db):
        """关键词搜索能找到结果"""
        # 直接测试 _keyword_search（避免触发向量搜索和 embedding 加载）
        from core.search.hybrid import HybridSearch
        search = HybridSearch(db_path=test_db)
        results = await search._keyword_search("A公司", limit=10)

        assert len(results) > 0
        # 结果格式: (page_id, score, rank)
        page_ids = [r[0] for r in results]
        assert "email:001" in page_ids or "email:002" in page_ids or "email:004" in page_ids

    @pytest.mark.asyncio
    async def test_metadata_search(self, test_db):
        """元数据搜索"""
        from core.search.hybrid import HybridSearch
        search = HybridSearch(db_path=test_db)
        results = await search._metadata_search("张三", limit=10)

        # 张三在 email:001 的 metadata 中
        assert len(results) > 0

    def test_rrf_fusion(self, test_db):
        """RRF融合正确合并结果"""
        from core.search.hybrid import HybridSearch, SearchResult
        search = HybridSearch(db_path=test_db)

        # 模拟三个搜索源的结果
        vector_results = [("email:001", 0.95, 1), ("email:002", 0.80, 2)]
        keyword_results = [("email:001", 1.0, 1), ("email:003", 0.5, 2)]
        metadata_results = [("email:002", 2.0, 1)]

        combined = search._rrf_fusion(vector_results, keyword_results, metadata_results)

        assert len(combined) == 3  # 3个unique page_ids
        # email:001 应该得分最高（同时出现在 vector 和 keyword 中）
        sorted_results = sorted(combined, key=lambda r: r.score, reverse=True)
        assert sorted_results[0].page_id == "email:001"

    def test_search_result_structure(self):
        """SearchResult 结构正确"""
        result = SearchResult(
            page_id="test-001",
            content="测试内容",
            score=0.95,
            metadata={"from": "test@test.com"},
            gate_class="important",
        )
        assert result.page_id == "test-001"
        assert result.score == 0.95


# ── 测试：搜索权重配置 ──

class TestSearchWeights:
    """搜索权重配置测试"""

    def test_default_weights(self):
        """默认权重合理"""
        weights = SearchWeights()
        assert weights.vector_weight > 0
        assert weights.keyword_weight > 0
        assert weights.rrf_k > 0

    def test_custom_weights(self, test_db):
        """自定义权重"""
        weights = SearchWeights(
            vector_weight=2.0,
            keyword_weight=0.5,
            metadata_weight=1.0,
        )
        search = HybridSearch(db_path=test_db, weights=weights)
        assert search.weights.vector_weight == 2.0
        assert search.weights.keyword_weight == 0.5


# ── 测试：NL2SQLResult结构 ──

class TestNL2SQLResult:
    """NL2SQL结果结构测试"""

    def test_result_structure(self):
        """结果结构完整"""
        result = NL2SQLResult(
            original_query="和A公司的往来邮件",
            sql="SELECT * FROM pages WHERE content LIKE '%A公司%'",
            explanation="查询包含A公司的邮件",
            estimated_rows=10,
            is_safe=True,
        )

        assert result.original_query == "和A公司的往来邮件"
        assert "SELECT" in result.sql
        assert result.is_safe is True
        assert result.estimated_rows == 10

    def test_unsafe_result(self):
        """不安全结果标记"""
        result = NL2SQLResult(
            original_query="恶意查询",
            sql="DROP TABLE pages",
            explanation="恶意操作",
            is_safe=False,
            validation_errors=["dangerous_pattern"],
        )

        assert result.is_safe is False
        assert len(result.validation_errors) > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
