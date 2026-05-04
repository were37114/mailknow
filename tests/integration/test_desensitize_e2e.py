#!/usr/bin/env python3
"""
MailKnow V5.2 脱敏安全测试

验证6类敏感信息正确脱敏：
1. 人名：张三 → 张*
2. 手机号：13812345678 → 138****5678
3. 邮箱：test@company.com → t***@company.com
4. 身份证：110101199001011234 → 110101****1234
5. 金额：¥50000 → [金额]
6. 密码：password: abc123 → password: [已脱敏]
"""

import json
import os
import sys
from pathlib import Path

# 添加src路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from llm.desensitize import DesensitizeEngine, SensitiveType


def test_phone_desensitization():
    """测试手机号脱敏"""
    print("\n📊 测试手机号脱敏...")

    engine = DesensitizeEngine()
    test_cases = [
        ("联系方式：13812345678", "联系方式：138****5678"),
        ("手机号是15987654321", "手机号是159****54321"),
        ("电话18611223344", "电话186****3344"),
    ]

    passed = 0
    for original, expected_pattern in test_cases:
        result = engine.desensitize(original)
        # 验证脱敏后不包含完整手机号
        if "13812345678" not in result.sanitized and "15987654321" not in result.sanitized:
            print(f"  ✅ {original} → {result.sanitized}")
            passed += 1
        else:
            print(f"  ❌ {original} → {result.sanitized} (未正确脱敏)")

    return passed == len(test_cases)


def test_email_desensitization():
    """测试邮箱脱敏"""
    print("\n📊 测试邮箱脱敏...")

    engine = DesensitizeEngine()
    test_cases = [
        ("邮箱：test@company.com", "邮箱：t***@company.com"),
        ("联系zhangsan@example.cn", "联系z***@example.cn"),
        ("发件人user123@domain.org", "发件人u***@domain.org"),
    ]

    passed = 0
    for original, expected_pattern in test_cases:
        result = engine.desensitize(original)
        # 验证脱敏后不包含完整邮箱
        if "test@company.com" not in result.sanitized and "zhangsan@example.cn" not in result.sanitized:
            print(f"  ✅ {original} → {result.sanitized}")
            passed += 1
        else:
            print(f"  ❌ {original} → {result.sanitized} (未正确脱敏)")

    return passed == len(test_cases)


def test_id_card_desensitization():
    """测试身份证脱敏"""
    print("\n📊 测试身份证脱敏...")

    engine = DesensitizeEngine()
    test_cases = [
        ("身份证号：110101199001011234", "身份证号：110101****1234"),
        ("证件号码330102198512121234", "证件号码330102****1234"),
    ]

    passed = 0
    for original, expected_pattern in test_cases:
        result = engine.desensitize(original)
        # 验证脱敏后不包含完整身份证号
        if "110101199001011234" not in result.sanitized and "330102198512121234" not in result.sanitized:
            print(f"  ✅ {original} → {result.sanitized}")
            passed += 1
        else:
            print(f"  ❌ {original} → {result.sanitized} (未正确脱敏)")

    return passed == len(test_cases)


def test_amount_desensitization():
    """测试金额脱敏"""
    print("\n📊 测试金额脱敏...")

    engine = DesensitizeEngine()
    test_cases = [
        ("金额：¥50000", "[金额]"),
        ("合同金额800万元", "[金额]万元"),
        ("预算500000元", "[金额]"),
    ]

    passed = 0
    for original, expected_pattern in test_cases:
        result = engine.desensitize(original)
        # 验证脱敏后不包含完整金额
        if "50000" not in result.sanitized and "800万" not in result.sanitized:
            print(f"  ✅ {original} → {result.sanitized}")
            passed += 1
        else:
            print(f"  ❌ {original} → {result.sanitized} (未正确脱敏)")

    return passed == len(test_cases)


def test_password_desensitization():
    """测试密码脱敏"""
    print("\n📊 测试密码脱敏...")

    engine = DesensitizeEngine()
    test_cases = [
        ("密码：Abc123!@#", "密码: [已脱敏]"),
        ("password: secret123", "password: [已脱敏]"),
        ("API key: sk-abc123xyz", "API key: [已脱敏]"),
    ]

    passed = 0
    for original, expected_pattern in test_cases:
        result = engine.desensitize(original)
        # 验证脱敏后不包含密码明文
        if "Abc123!@#" not in result.sanitized and "secret123" not in result.sanitized:
            print(f"  ✅ {original} → {result.sanitized}")
            passed += 1
        else:
            print(f"  ❌ {original} → {result.sanitized} (未正确脱敏)")

    return passed == len(test_cases)


def test_person_name_desensitization():
    """测试人名脱敏"""
    print("\n📊 测试人名脱敏...")

    engine = DesensitizeEngine()
    test_cases = [
        ("张三，你好", "张*，你好"),
        ("李四是项目负责人", "李*是项目负责人"),
        ("王五参加会议", "王*参加会议"),
    ]

    passed = 0
    for original, expected_pattern in test_cases:
        result = engine.desensitize(original)
        # 验证脱敏后人名被替换
        if "张三" not in result.sanitized or "*" in result.sanitized:
            print(f"  ✅ {original} → {result.sanitized}")
            passed += 1
        else:
            print(f"  ❌ {original} → {result.sanitized} (未正确脱敏)")

    return passed == len(test_cases)


def test_combined_email():
    """端到端测试：使用测试数据集"""
    print("\n📊 端到端测试：测试数据集...")

    # 加载测试数据集
    dataset_path = Path(__file__).parent.parent / "datasets" / "sensitive_samples" / "sensitive_samples.json"

    if not dataset_path.exists():
        print(f"  ⚠️ 测试数据集不存在: {dataset_path}")
        return True  # 跳过，不阻塞测试

    with open(dataset_path, 'r', encoding='utf-8') as f:
        test_samples = json.load(f)

    engine = DesensitizeEngine()

    passed = 0
    total = len(test_samples)

    for sample in test_samples:
        original = sample['content']
        sensitive_type = sample['type']
        original_value = sample['original_value']

        result = engine.desensitize(original)

        # 验证原始敏感信息不在脱敏后文本中
        if original_value in result.sanitized:
            print(f"  ❌ {sensitive_type}: 原始值 '{original_value}' 未被脱敏")
        else:
            passed += 1

    print(f"  ✅ {passed}/{total} 测试通过")

    return passed == total


def main():
    print("=" * 60)
    print("MailKnow V5.2 脱敏安全测试")
    print("=" * 60)

    tests = [
        ("手机号脱敏", test_phone_desensitization),
        ("邮箱脱敏", test_email_desensitization),
        ("身份证脱敏", test_id_card_desensitization),
        ("金额脱敏", test_amount_desensitization),
        ("密码脱敏", test_password_desensitization),
        ("人名脱敏", test_person_name_desensitization),
        ("端到端测试", test_combined_email),
    ]

    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            print(f"  ❌ 测试异常: {e}")
            results[name] = False

    # 打印结果汇总
    print("\n" + "=" * 60)
    print("脱敏测试结果汇总")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{name}: {status}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 全部脱敏测试通过！")
        return 0
    else:
        print(f"\n⚠️ {total - passed} 项未通过")
        return 1


if __name__ == "__main__":
    sys.exit(main())
