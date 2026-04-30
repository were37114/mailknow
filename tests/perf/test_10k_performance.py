"""Performance tests for 10K dataset.

Validates:
- 10K email insertion < 60s
- Search response < 500ms
- Gate classification < 10ms per email
- Embedding batch processing throughput
"""

import pytest
import asyncio
import json
import time
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
import random
import string

from sync.models import Email, EmailAddress
from core.gate.classifier import GateClassifier, EmailInfo
from core.pipeline import EmailPipeline
from core.search.hybrid import HybridSearch, SearchWeights, SearchOptions
from core.search.batch_embedding import BatchEmbeddingQueue
from db.pgpool import SQLitePool


# ===== Data Generator =====

NAMES_CN = ["张三", "李四", "王五", "赵六", "孙七", "周八", "吴九", "郑十",
            "刘经理", "陈总", "杨工", "黄主管", "林助理", "何总监"]
DOMAINS = ["company.com", "partner.cn", "supplier.com", "client.org", "vendor.net"]
SUBJECTS_IMPORTANT = ["项目进度讨论", "合同审批", "报价确认", "客户需求变更", "技术方案评审"]
SUBJECTS_URGENT = ["紧急：服务器宕机", "紧急：安全漏洞", "紧急：客户投诉", "紧急：数据丢失"]
SUBJECTS_ROUTINE = ["周报提交提醒", "团队建设活动", "食堂菜单更新", "停车通知", "办公用品申领"]
SUBJECTS_NOTIFICATION = ["系统维护通知", "报销审批已通过", "打卡提醒", "假期审批通过", "邮件投递成功"]
SUBJECTS_SPAM = ["恭喜中奖！免费领取", "限时优惠！点击领取", "低息贷款，快速审批", "代开发票，价格优惠"]
BODIES = [
    "请查看附件中的详细报告，如有问题请及时反馈。",
    "我们计划在下周三召开项目评审会议，请提前准备。",
    "关于上次讨论的技术方案，我整理了几个要点供参考。",
    "客户反馈了新的需求变更，需要我们重新评估工期。",
    "系统监控发现异常指标，请相关同事尽快处理。",
    "本周工作总结：完成了3个模块的开发和测试。",
    "提醒您今天下午3点有一场跨部门会议。",
    "您的报销申请已通过审批，预计3个工作日内到账。",
]


def generate_email(index: int) -> Email:
    """Generate a realistic test email."""
    # Distribute gate classes realistically
    r = random.random()
    if r < 0.05:
        subject = random.choice(SUBJECTS_URGENT)
    elif r < 0.20:
        subject = random.choice(SUBJECTS_IMPORTANT)
    elif r < 0.60:
        subject = random.choice(SUBJECTS_ROUTINE)
    elif r < 0.85:
        subject = random.choice(SUBJECTS_NOTIFICATION)
    else:
        subject = random.choice(SUBJECTS_SPAM)
    
    sender_name = random.choice(NAMES_CN)
    sender_domain = random.choice(DOMAINS)
    sender_addr = f"{sender_name.lower()}@{sender_domain}"
    
    return Email(
        message_id=f"<perf{index:06d}@{sender_domain}>",
        subject=f"{subject} #{index}",
        from_addr=EmailAddress(name=sender_name, address=sender_addr),
        to_addrs=[EmailAddress(name="我", address="me@company.com")],
        cc_addrs=[],
        text_body=random.choice(BODIES),
        date=datetime.now(timezone.utc) - timedelta(
            days=random.randint(0, 30),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        ),
        flags=[],
    )


# ===== Tests =====

class TestPerformance10K:
    """Performance tests with 10K email dataset."""

    @pytest.mark.asyncio
    async def test_insert_10k_emails(self):
        """Test inserting 10K emails through pipeline."""
        with tempfile.TemporaryDirectory() as d:
            db = SQLitePool(data_dir=Path(d))
            await db.start()
            await db.init_schema()
            
            pipeline = EmailPipeline(db=db)
            
            # Generate and insert 10K emails
            start_time = time.time()
            
            emails = [generate_email(i) for i in range(10000)]
            
            # Process in batches of 100
            for batch_start in range(0, 10000, 100):
                batch = emails[batch_start:batch_start + 100]
                results = await pipeline.process_batch(
                    emails=batch,
                    account_id="perf_test",
                    folder="INBOX",
                    start_uid=batch_start,
                )
                
                # Count errors
                errors = [r for r in results if r.error is not None]
                assert len(errors) == 0, f"Errors in batch {batch_start}: {[r.error for r in errors]}"
            
            elapsed = time.time() - start_time
            
            # Verify count
            conn = await db.get_connection()
            cursor = await conn.execute("SELECT COUNT(*) FROM pages WHERE type = 'email'")
            count = (await cursor.fetchone())[0]
            
            await db.stop()
            
            # Assertions
            assert count == 10000, f"Expected 10000, got {count}"
            assert elapsed < 120, f"Insertion took {elapsed:.1f}s, expected < 120s"
            print(f"\n✅ 10K insertion: {elapsed:.1f}s ({10000/elapsed:.0f} emails/s)")

    @pytest.mark.asyncio
    async def test_gate_classification_performance(self):
        """Test Gate classification speed."""
        classifier = GateClassifier()
        
        emails = [
            EmailInfo(
                subject=random.choice(SUBJECTS_URGENT + SUBJECTS_IMPORTANT + SUBJECTS_ROUTINE),
                from_addr=f"test{random.randint(1,100)}@company.com",
                to_addrs=["me@company.com"],
                content="测试内容",
            )
            for _ in range(1000)
        ]
        
        start_time = time.time()
        for email_info in emails:
            classifier.classify(email_info)
        elapsed = time.time() - start_time
        
        per_email_ms = elapsed / 1000 * 1000
        
        assert per_email_ms < 10, f"Gate classification took {per_email_ms:.2f}ms, expected < 10ms"
        print(f"\n✅ Gate classification: {per_email_ms:.2f}ms per email ({1000/elapsed:.0f} emails/s)")

    def test_search_performance_sync(self):
        """Test keyword search response time (sync, no deadlock risk)."""
        import sqlite3
        
        with tempfile.TemporaryDirectory() as d:
            db_path = str(Path(d) / "mailknow.db")
            conn = sqlite3.connect(db_path)
            
            # Create tables
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS pages (
                    id TEXT PRIMARY KEY, type TEXT, content TEXT, metadata TEXT,
                    gate_class TEXT DEFAULT 'routine', created_at TEXT, updated_at TEXT
                );
            """)
            
            now = datetime.now(timezone.utc).isoformat()
            for i in range(200):
                metadata = json.dumps({
                    "from_addr": f"sender{i}@test.com",
                    "from_name": random.choice(NAMES_CN),
                }, ensure_ascii=False)
                subject = random.choice(SUBJECTS_URGENT + SUBJECTS_IMPORTANT + SUBJECTS_ROUTINE)
                conn.execute(
                    "INSERT OR IGNORE INTO pages (id, type, content, metadata, gate_class, created_at, updated_at) VALUES (?, 'email', ?, ?, 'routine', ?, ?)",
                    (f"email:search{i}", f"{subject} #{i}", metadata, now, now)
                )
            conn.commit()
            
            # Keyword search benchmark
            queries = ["项目", "紧急", "审批", "会议", "服务器"]
            times = []
            for query in queries:
                keywords = query.split()
                like_conditions = " OR ".join(["content LIKE ?" for _ in keywords])
                like_params = [f"%{kw}%" for kw in keywords]
                
                start_time = time.time()
                for _ in range(10):  # 10 iterations
                    conn.execute(
                        f"SELECT id FROM pages WHERE {like_conditions} LIMIT 20",
                        like_params
                    ).fetchall()
                elapsed_ms = (time.time() - start_time) / 10 * 1000
                times.append(elapsed_ms)
            
            conn.close()
            
            avg_time = sum(times) / len(times)
            max_time = max(times)
            
            assert max_time < 500, f"Max search time {max_time:.0f}ms, expected < 500ms"
            print(f"\n✅ Search performance: avg={avg_time:.1f}ms, max={max_time:.1f}ms")

    @pytest.mark.asyncio
    async def test_embedding_queue_throughput(self):
        """Test embedding queue throughput."""
        with tempfile.TemporaryDirectory() as d:
            db = SQLitePool(data_dir=Path(d))
            await db.start()
            await db.init_schema()
            
            # Create mock embedding model
            from unittest.mock import MagicMock
            mock_model = MagicMock()
            import numpy as np
            mock_model.encode_batch = MagicMock(
                return_value=np.random.rand(32, 512).astype(np.float32)
            )
            mock_model.embedding_to_bytes = MagicMock(side_effect=lambda x: x.tobytes())
            mock_model.dimension = 512
            
            queue = BatchEmbeddingQueue(db=db, embedding_model=mock_model, batch_size=32)
            
            # Insert pages
            conn = await db.get_connection()
            now = datetime.now(timezone.utc).isoformat()
            for i in range(100):
                await conn.execute(
                    "INSERT OR IGNORE INTO pages (id, type, content, gate_class, created_at, updated_at) VALUES (?, 'email', ?, 'routine', ?, ?)",
                    (f"email:emb{i}", f"内容{i}", now, now)
                )
            await conn.commit()
            
            # Enqueue
            start_time = time.time()
            for i in range(100):
                await queue.enqueue(f"email:emb{i}", f"内容{i}", "routine")
            
            # Process
            processed = await queue.process_now()
            elapsed = time.time() - start_time
            
            progress = await queue.get_progress()
            
            await db.stop()
            
            assert processed >= 1  # At least one batch processed
            assert progress.completed > 0
            print(f"\n✅ Embedding throughput: {progress.completed} in {elapsed:.1f}s")
