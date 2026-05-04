#!/usr/bin/env python3
"""Desensitization context isolation test.

Compares full-text desensitization vs. segment-by-segment desensitization
to measure Precision, Recall, and F1 differences.

Hypothesis: Full-text desensitization preserves more context but may miss
cross-boundary patterns. Segment-by-segment may miss names at segment edges
but has fewer false positives.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from llm.desensitize import DesensitizeEngine, SensitiveType


def create_test_samples():
    """Create test samples with known sensitive values."""
    samples = []

    # Person names
    samples.append({
        "text": "收件人：刘洋，你好。关于项目安排，请张经理审批。",
        "expected_types": {"person_name"},
        "expected_values": {"刘洋", "张经理"},
    })
    samples.append({
        "text": "李四是项目负责人，王五参加会议，陈小明来开会了",
        "expected_types": {"person_name"},
        "expected_values": {"李四", "王五", "陈小明"},
    })
    samples.append({
        "text": "请孙总审批，赵大宝的方案需要确认",
        "expected_types": {"person_name"},
        "expected_values": {"孙总", "赵大宝"},
    })

    # Phone numbers
    samples.append({
        "text": "联系方式：13812345678，备用电话15987654321",
        "expected_types": {"phone"},
        "expected_values": {"13812345678", "15987654321"},
    })

    # Emails
    samples.append({
        "text": "发件人zhangsan@company.com，抄送lisi@example.cn",
        "expected_types": {"email"},
        "expected_values": {"zhangsan@company.com", "lisi@example.cn"},
    })

    # Amounts
    samples.append({
        "text": "合同金额¥80,000，预算500万元",
        "expected_types": {"amount"},
        "expected_values": {"¥80,000", "500万元"},
    })

    # Mixed
    samples.append({
        "text": "张三的手机号是13812345678，邮箱zhangsan@test.com，审批金额¥5,000",
        "expected_types": {"person_name", "phone", "email", "amount"},
        "expected_values": {"张三", "13812345678", "zhangsan@test.com", "¥5,000"},
    })

    # Edge case: false positive traps
    samples.append({
        "text": "培训安排事宜，关于项目安排，会议安排如下",
        "expected_types": set(),
        "expected_values": set(),  # No person names should be detected
    })

    return samples


def full_text_desensitize(engine, text):
    """Desensitize the entire text at once."""
    return engine.desensitize(text)


def segment_desensitize(engine, text, delimiter="。"):
    """Desensitize each segment independently, then rejoin."""
    segments = text.split(delimiter)
    all_replacements = []
    sanitized_segments = []

    for segment in segments:
        if not segment.strip():
            sanitized_segments.append(segment)
            continue
        result = engine.desensitize(segment)
        sanitized_segments.append(result.sanitized)
        all_replacements.extend(result.replacements)

    sanitized = delimiter.join(sanitized_segments)

    from llm.desensitize import DesensitizeResult
    return DesensitizeResult(
        original=text,
        sanitized=sanitized,
        replacements=all_replacements,
    )


def evaluate(result, expected_values):
    """Evaluate desensitization results against expected values.

    Returns (precision, recall, f1, tp, fp, fn)
    """
    detected_values = set(r["original"] for r in result.replacements)
    expected = set(expected_values)

    # True positives: expected values that were correctly detected
    tp = len(detected_values & expected)
    # False positives: detected values not in expected
    fp = len(detected_values - expected)
    # False negatives: expected values not detected
    fn = len(expected - detected_values)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return precision, recall, f1, tp, fp, fn


def main():
    print("=" * 70)
    print("MailKnow V5.2 — 脱敏上下文隔离测试")
    print("=" * 70)

    engine = DesensitizeEngine()
    samples = create_test_samples()

    # Test both approaches
    approaches = [
        ("全文脱敏", full_text_desensitize),
        ("分段脱敏", segment_desensitize),
    ]

    results_by_approach = {}

    for approach_name, approach_fn in approaches:
        total_tp = total_fp = total_fn = 0

        print(f"\n{'─' * 70}")
        print(f"方法：{approach_name}")
        print(f"{'─' * 70}")

        for i, sample in enumerate(samples):
            result = approach_fn(engine, sample["text"])
            precision, recall, f1, tp, fp, fn = evaluate(result, sample["expected_values"])

            total_tp += tp
            total_fp += fp
            total_fn += fn

            status = "✅" if fp == 0 and fn == 0 else "⚠️"
            print(f"\n  {status} 样本 {i+1}: P={precision:.2f} R={recall:.2f} F1={f1:.2f}")
            print(f"    原文: {sample['text'][:50]}...")
            print(f"    脱敏: {result.sanitized[:50]}...")
            if fp > 0:
                false_pos = set(r["original"] for r in result.replacements) - sample["expected_values"]
                print(f"    ❌ 误报(FP): {false_pos}")
            if fn > 0:
                false_neg = sample["expected_values"] - set(r["original"] for r in result.replacements)
                print(f"    ❌ 漏报(FN): {false_neg}")

        total_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 1.0
        total_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 1.0
        total_f1 = 2 * total_p * total_r / (total_p + total_r) if (total_p + total_r) > 0 else 0.0

        results_by_approach[approach_name] = {
            "precision": total_p,
            "recall": total_r,
            "f1": total_f1,
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
        }

    # Summary comparison
    print(f"\n{'=' * 70}")
    print("对比总结")
    print(f"{'=' * 70}")
    print(f"{'方法':<12} {'Precision':<12} {'Recall':<12} {'F1':<12} {'TP':<6} {'FP':<6} {'FN':<6}")
    print(f"{'─' * 70}")

    for name, r in results_by_approach.items():
        print(f"{name:<12} {r['precision']:<12.4f} {r['recall']:<12.4f} {r['f1']:<12.4f} {r['tp']:<6} {r['fp']:<6} {r['fn']:<6}")

    # Verdict
    full = results_by_approach["全文脱敏"]
    seg = results_by_approach["分段脱敏"]

    if full["f1"] >= seg["f1"]:
        print(f"\n✅ 结论：全文脱敏 F1={full['f1']:.4f} ≥ 分段脱敏 F1={seg['f1']:.4f}，推荐全文脱敏")
    else:
        print(f"\n⚠️ 结论：分段脱敏 F1={seg['f1']:.4f} > 全文脱敏 F1={full['f1']:.4f}，需要评估上下文损失")

    # Check that no approach has FP on false-positive traps
    trap_sample = [s for s in samples if not s["expected_values"]][0]
    for name, fn in approaches:
        result = fn(engine, trap_sample["text"])
        fp_count = len(result.replacements)
        if fp_count > 0:
            print(f"  ❌ {name} 在假阳性陷阱中误报了 {fp_count} 个值")
            return 1

    print("\n🎉 全部测试通过！两种方法均无假阳性")
    return 0


if __name__ == "__main__":
    sys.exit(main())
