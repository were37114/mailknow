#!/usr/bin/env python3
"""
MailKnow V5.2 审批边界测试

验证审批邮件的边界分类：
- CC审批：低置信度，不进入卡片
- 已完成通知：Gate1分类，不推送
- 系统转发：正确识别审批类型
"""

import sys
import os
import json
import asyncio
from pathlib import Path

# 添加src路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from scenes.approval.detector import ApprovalDetector
from sync.models import Email, EmailAddress
from datetime import datetime, timezone


def dict_to_email(email_data: dict) -> Email:
    """将字典转换为Email对象"""
    return Email(
        message_id=f"<test_{email_data.get('subject', '')[:10]}@test.com>",
        subject=email_data.get('subject', ''),
        from_addr=EmailAddress(
            name='',
            address=email_data.get('from_addr', 'test@test.com')
        ),
        to_addrs=[EmailAddress(name='', address=a) for a in email_data.get('to_addrs', [])],
        cc_addrs=[EmailAddress(name='', address=a) for a in email_data.get('cc_addrs', [])],
        text_body=email_data.get('content', ''),
        date=datetime.now(timezone.utc),
        flags=[],
    )


def load_test_samples():
    """加载审批边界测试数据"""
    dataset_path = Path(__file__).parent.parent / "datasets" / "approval_samples.json"
    
    if not dataset_path.exists():
        print(f"⚠️ 测试数据集不存在: {dataset_path}")
        return []
    
    with open(dataset_path, 'r', encoding='utf-8') as f:
        samples = json.load(f)
    
    return samples


async def test_approval_boundary_async():
    """测试审批边界分类（异步）"""
    print("=" * 60)
    print("MailKnow V5.2 审批边界测试")
    print("=" * 60)
    
    samples = load_test_samples()
    
    if not samples:
        print("⚠️ 无测试数据，测试跳过")
        return True
    
    detector = ApprovalDetector()
    
    passed = 0
    total = len(samples)
    
    for sample in samples:
        sample_id = sample.get('id', 'unknown')
        description = sample.get('description', '')
        email_data = sample.get('email', {})
        expected = sample.get('expected', {})
        
        print(f"\n测试: {sample_id}")
        print(f"  描述: {description}")
        
        # 构造Email对象
        email_obj = dict_to_email(email_data)
        
        try:
            # 异步检测审批
            result = await detector.detect(email_obj)
            
            # 验证结果
            is_approval_match = result.is_approval == expected.get('is_approval', False)
            approval_type_match = result.approval_type.value if hasattr(result.approval_type, 'value') else str(result.approval_type) == expected.get('approval_type', '')
            
            # 置信度检查（如果预期有置信度上限）
            confidence_ok = True
            if 'confidence_max' in expected:
                confidence_ok = result.confidence <= expected['confidence_max']
            
            if is_approval_match and approval_type_match and confidence_ok:
                print(f"  ✅ 通过: is_approval={result.is_approval}, type={result.approval_type}, confidence={result.confidence:.2f}")
                passed += 1
            else:
                print(f"  ❌ 失败:")
                print(f"     预期: is_approval={expected.get('is_approval')}, type={expected.get('approval_type')}")
                print(f"     实际: is_approval={result.is_approval}, type={result.approval_type}, confidence={result.confidence:.2f}")
        
        except Exception as e:
            print(f"  ❌ 异常: {e}")
    
    # 结果汇总
    print("\n" + "=" * 60)
    print("审批边界测试结果")
    print("=" * 60)
    print(f"通过: {passed}/{total}")
    
    if passed == total:
        print("\n🎉 全部审批边界测试通过！")
        return True
    else:
        print(f"\n⚠️ {total - passed} 项未通过")
        return False


def main():
    success = asyncio.run(test_approval_boundary_async())
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())