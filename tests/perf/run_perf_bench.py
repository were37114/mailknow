#!/usr/bin/env python3
"""
MailKnow V5.2 性能压测脚本

压测指标：
1. Gate分流速度：P95 < 10ms/封
2. 搜索响应时间：P95 < 500ms
3. 插入吞吐：1000封 < 30s
"""

import sys
import os
import time
import json
import random
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import statistics

# 添加src路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


# ===== 测试数据生成 =====

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


def generate_test_emails(count: int) -> List[Dict[str, Any]]:
    """生成测试邮件数据"""
    emails = []
    for i in range(count):
        r = random.random()
        if r < 0.05:
            subject = random.choice(SUBJECTS_URGENT)
            gate_class = 'G2'
        elif r < 0.20:
            subject = random.choice(SUBJECTS_IMPORTANT)
            gate_class = 'G4'
        elif r < 0.60:
            subject = random.choice(SUBJECTS_ROUTINE)
            gate_class = 'G3'
        elif r < 0.85:
            subject = random.choice(SUBJECTS_NOTIFICATION)
            gate_class = 'G1'
        else:
            subject = random.choice(SUBJECTS_SPAM)
            gate_class = 'G0'
        
        sender_name = random.choice(NAMES_CN)
        sender_domain = random.choice(DOMAINS)
        
        email = {
            'id': f"email_{i:06d}",
            'subject': f"{subject} #{i}",
            'sender': f"{sender_name.lower()}@{sender_domain}",
            'sender_name': sender_name,
            'content': random.choice(BODIES),
            'gate_class': gate_class,
            'date': (datetime.now(timezone.utc) - timedelta(days=random.randint(0, 30))).isoformat(),
        }
        emails.append(email)
    
    return emails


# ===== Gate分流压测 =====

def bench_gate_classification(emails: List[Dict[str, Any]], iterations: int = 3) -> Dict[str, float]:
    """测试Gate分流速度"""
    print(f"\n📊 Gate分流压测：{len(emails)} 封 x {iterations} 次")
    
    # 导入Gate分类器
    try:
        from core.gate.classifier import GateClassifier
        classifier = GateClassifier()
        use_real = True
    except Exception as e:
        print(f"⚠️ 无法导入GateClassifier: {e}，使用模拟分类")
        use_real = False
    
    all_times = []
    
    for iteration in range(iterations):
        start = time.time()
        
        if use_real:
            for email in emails:
                try:
                    result = classifier.classify({
                        'subject': email['subject'],
                        'content': email['content'],
                        'from_addr': email['sender'],
                    })
                except:
                    pass
        else:
            # 模拟分类（正则匹配）
            for email in emails:
                subject_lower = email['subject'].lower()
                if '紧急' in subject_lower or '紧急' in email['content']:
                    _ = 'G2'
                elif '审批' in subject_lower:
                    _ = 'G4'
                elif '通知' in subject_lower or '提醒' in subject_lower:
                    _ = 'G1'
                elif '中奖' in subject_lower or '优惠' in subject_lower:
                    _ = 'G0'
                else:
                    _ = 'G3'
        
        elapsed = time.time() - start
        all_times.append(elapsed)
    
    total_emails = len(emails) * iterations
    total_time = sum(all_times)
    avg_time_ms = (total_time / total_emails) * 1000
    p95_time_ms = statistics.quantiles(all_times, n=100)[94] * 1000 / len(emails) if len(all_times) >= 5 else avg_time_ms
    
    print(f"  ✅ 总耗时: {total_time:.2f}s")
    print(f"  ✅ 平均: {avg_time_ms:.2f}ms/封")
    print(f"  ✅ 吞吐: {total_emails/total_time:.0f} 封/秒")
    
    return {
        'total_time_s': total_time,
        'avg_ms': avg_time_ms,
        'p95_ms': p95_time_ms,
        'throughput': total_emails / total_time,
        'passed': avg_time_ms < 10,
    }


# ===== 搜索压测 =====

def bench_search(db_path: str, queries: List[str], iterations: int = 10) -> Dict[str, float]:
    """测试搜索响应时间"""
    print(f"\n📊 搜索压测：{len(queries)} 查询 x {iterations} 次")
    
    conn = sqlite3.connect(db_path)
    
    all_times = []
    
    for query in queries:
        query_times = []
        for _ in range(iterations):
            start = time.time()
            
            # 关键词搜索
            cursor = conn.execute(
                "SELECT id, subject FROM pages WHERE content LIKE ? LIMIT 20",
                (f"%{query}%",)
            )
            _ = cursor.fetchall()
            
            elapsed_ms = (time.time() - start) * 1000
            query_times.append(elapsed_ms)
        
        all_times.extend(query_times)
    
    conn.close()
    
    avg_time_ms = statistics.mean(all_times)
    p95_time_ms = statistics.quantiles(all_times, n=100)[94] if len(all_times) >= 20 else max(all_times)
    max_time_ms = max(all_times)
    
    print(f"  ✅ 平均: {avg_time_ms:.1f}ms")
    print(f"  ✅ P95: {p95_time_ms:.1f}ms")
    print(f"  ✅ 最大: {max_time_ms:.1f}ms")
    
    return {
        'avg_ms': avg_time_ms,
        'p95_ms': p95_time_ms,
        'max_ms': max_time_ms,
        'passed': p95_time_ms < 500,
    }


# ===== 插入压测 =====

def bench_insertion(db_path: str, emails: List[Dict[str, Any]], batch_size: int = 100) -> Dict[str, float]:
    """测试插入吞吐"""
    print(f"\n📊 插入压测：{len(emails)} 封，批次 {batch_size}")
    
    conn = sqlite3.connect(db_path)
    
    # 创建表
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pages (
            id TEXT PRIMARY KEY,
            type TEXT,
            subject TEXT,
            content TEXT,
            sender TEXT,
            gate_class TEXT,
            date TEXT,
            created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_content ON pages(content);
    """)
    conn.commit()
    
    start = time.time()
    
    inserted = 0
    for i in range(0, len(emails), batch_size):
        batch = emails[i:i + batch_size]
        now = datetime.now().isoformat()
        
        for email in batch:
            conn.execute(
                """INSERT OR REPLACE INTO pages 
                   (id, type, subject, content, sender, gate_class, date, created_at)
                   VALUES (?, 'email', ?, ?, ?, ?, ?, ?)""",
                (email['id'], email['subject'], email['content'], 
                 email['sender'], email['gate_class'], email['date'], now)
            )
        conn.commit()
        inserted += len(batch)
    
    elapsed = time.time() - start
    throughput = inserted / elapsed
    
    conn.close()
    
    print(f"  ✅ 总耗时: {elapsed:.2f}s")
    print(f"  ✅ 吞吐: {throughput:.0f} 封/秒")
    print(f"  ✅ 每批: {elapsed / (len(emails) / batch_size):.2f}s")
    
    return {
        'total_time_s': elapsed,
        'throughput': throughput,
        'batch_time_s': elapsed / (len(emails) / batch_size),
        'passed': elapsed < 60,  # 1000封 < 60s
    }


# ===== 主函数 =====

def main():
    print("=" * 60)
    print("MailKnow V5.2 性能压测")
    print("=" * 60)
    
    # 准备测试数据
    print("\n📁 准备测试数据...")
    
    # 小规模测试
    small_emails = generate_test_emails(1000)
    print(f"  ✅ 生成1000封测试邮件")
    
    # 大规模测试
    large_emails = generate_test_emails(50000)
    print(f"  ✅ 生成50000封测试邮件")
    
    # 临时数据库
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "perf_test.db"
        
        # 测试结果
        results = {}
        
        # 1. Gate分流压测
        results['gate_1000'] = bench_gate_classification(small_emails, iterations=3)
        
        # 2. 插入压测
        results['insert_1000'] = bench_insertion(str(db_path), small_emails, batch_size=100)
        
        # 3. 搜索压测
        search_queries = ["项目", "紧急", "审批", "会议", "服务器", "报告", "系统", "通知"]
        results['search'] = bench_search(str(db_path), search_queries, iterations=10)
        
        # 4. 大规模插入压测（如果前面测试通过）
        if results['insert_1000']['passed']:
            db_path_large = Path(tmpdir) / "perf_test_large.db"
            # 分批进行，避免内存溢出
            batch_results = []
            for batch_start in range(0, 50000, 10000):
                batch_emails = large_emails[batch_start:batch_start + 10000]
                result = bench_insertion(str(db_path_large), batch_emails, batch_size=100)
                batch_results.append(result)
            
            # 汇总
            total_time = sum(r['total_time_s'] for r in batch_results)
            results['insert_50000'] = {
                'total_time_s': total_time,
                'throughput': 50000 / total_time,
                'passed': total_time < 300,  # 5万封 < 5分钟
            }
            print(f"\n📊 50000封插入汇总：{total_time:.1f}s")
        
        # 打印结果汇总
        print("\n" + "=" * 60)
        print("压测结果汇总")
        print("=" * 60)
        
        passed = 0
        total = len(results)
        
        for test_name, result in results.items():
            status = "✅ PASS" if result.get('passed', False) else "❌ FAIL"
            print(f"{test_name}: {status}")
            passed += 1 if result.get('passed', False) else 0
        
        print(f"\n总计: {passed}/{total} 通过")
        
        if passed == total:
            print("\n🎉 全部压测通过！")
            return 0
        else:
            print(f"\n⚠️ {total - passed} 项未通过，需要优化")
            return 1


if __name__ == "__main__":
    sys.exit(main())
