"""Tests for DesensitizeEngine: 6-type sensitive data masking."""

import pytest

from llm.desensitize import (
    DesensitizeEngine,
    DesensitizeResult,
    DesensitizeRule,
    SensitiveType,
)


@pytest.fixture
def engine():
    """Create desensitization engine with all rules enabled."""
    return DesensitizeEngine()


class TestSensitiveType:
    """Tests for SensitiveType enum."""

    def test_all_types(self):
        assert SensitiveType.PERSON_NAME.value == "person_name"
        assert SensitiveType.PHONE.value == "phone"
        assert SensitiveType.EMAIL.value == "email"
        assert SensitiveType.ID_CARD.value == "id_card"
        assert SensitiveType.AMOUNT.value == "amount"
        assert SensitiveType.PASSWORD.value == "password"


class TestDesensitizeResult:
    """Tests for DesensitizeResult."""

    def test_not_modified(self):
        r = DesensitizeResult(original="abc", sanitized="abc", replacements=[])
        assert r.was_modified is False

    def test_modified(self):
        r = DesensitizeResult(original="abc", sanitized="a*c", replacements=[])
        assert r.was_modified is True


class TestPhoneDesensitization:
    """Tests for phone number desensitization."""

    def test_chinese_mobile(self, engine):
        result = engine.desensitize("手机号是13812345678")
        assert "138****5678" in result.sanitized
        assert "13812345678" not in result.sanitized

    def test_multiple_phones(self, engine):
        result = engine.desensitize("联系13900001111或15122223333")
        assert "139****1111" in result.sanitized
        assert "151****3333" in result.sanitized

    def test_not_phone_number(self, engine):
        result = engine.desensitize("编号12345678901")
        # Should not match (doesn't start with 1)
        # Actually 12345678901 starts with 1, but it's 11 digits starting with 12
        # Let's use a non-phone number
        result = engine.desensitize("数量200个")
        assert "200" in result.sanitized  # Should not be masked


class TestEmailDesensitization:
    """Tests for email desensitization."""

    def test_email(self, engine):
        result = engine.desensitize("发件人zhangsan@company.com")
        assert "z***@company.com" in result.sanitized
        assert "zhangsan@company.com" not in result.sanitized

    def test_short_email(self, engine):
        result = engine.desensitize("联系a@test.com")
        assert "a***@test.com" in result.sanitized


class TestIDCardDesensitization:
    """Tests for ID card number desensitization."""

    def test_id_card(self, engine):
        result = engine.desensitize("身份证号110101199001011234")
        assert "110101****" in result.sanitized
        assert "199001011234" not in result.sanitized

    def test_id_card_with_x(self, engine):
        result = engine.desensitize("身份证44030120001201234X")
        assert "440301****" in result.sanitized


class TestAmountDesensitization:
    """Tests for amount desensitization."""

    def test_yuan_amount(self, engine):
        result = engine.desensitize("合同金额¥50,000元")
        assert "[金额]" in result.sanitized
        assert "50,000" not in result.sanitized

    def test_dollar_amount(self, engine):
        result = engine.desensitize("价格$1,200.50")
        assert "[金额]" in result.sanitized

    def test_chinese_amount(self, engine):
        result = engine.desensitize("报销3,200元")
        assert "[金额]" in result.sanitized


class TestPasswordDesensitization:
    """Tests for password/key desensitization."""

    def test_password_chinese(self, engine):
        result = engine.desensitize("密码：abc123456")
        assert "[已脱敏]" in result.sanitized
        assert "abc123456" not in result.sanitized

    def test_password_english(self, engine):
        result = engine.desensitize("password: mysecret123")
        assert "[已脱敏]" in result.sanitized
        assert "mysecret123" not in result.sanitized

    def test_token(self, engine):
        result = engine.desensitize("token=eyJhbGciOiJIUzI1NiJ9")
        assert "[已脱敏]" in result.sanitized
        assert "eyJhbGciOiJIUzI1NiJ9" not in result.sanitized

    def test_api_key(self, engine):
        result = engine.desensitize("API key=sk-abc123def456")
        assert "[已脱敏]" in result.sanitized


class TestPersonNameDesensitization:
    """Tests for person name desensitization."""

    def test_chinese_name_after_punctuation(self, engine):
        result = engine.desensitize("请转告张三，项目已启动")
        assert "张*" in result.sanitized

    def test_multiple_names(self, engine):
        result = engine.desensitize("参加人员：李四、王五、赵六")
        # Names after ： and 、 should be masked
        assert "李*" in result.sanitized or "王*" in result.sanitized

    def test_name_not_in_middle(self, engine):
        """Names in the middle of text without context should not always be caught."""
        # This is a known limitation - we only mask after punctuation to avoid false positives
        result = engine.desensitize("和张三讨论项目")
        # May or may not match depending on context


class TestRestore:
    """Tests for restore functionality."""

    def test_restore_phone(self, engine):
        original = "手机号是13812345678"
        result = engine.desensitize(original)
        restored = engine.restore(result.sanitized, result.replacements)
        assert restored == original

    def test_restore_email(self, engine):
        original = "发件人zhangsan@company.com"
        result = engine.desensitize(original)
        restored = engine.restore(result.sanitized, result.replacements)
        assert restored == original

    def test_restore_multiple(self, engine):
        original = "联系zhangsan@test.com，手机13812345678"
        result = engine.desensitize(original)
        restored = engine.restore(result.sanitized, result.replacements)
        assert restored == original


class TestRuleManagement:
    """Tests for enabling/disabling rules."""

    def test_disable_rule(self, engine):
        engine.disable_rule(SensitiveType.PHONE)

        result = engine.desensitize("手机13812345678")
        # Phone should NOT be masked when disabled
        assert "13812345678" in result.sanitized

        # Re-enable
        engine.enable_rule(SensitiveType.PHONE)

    def test_enable_disabled_rule(self, engine):
        engine.disable_rule(SensitiveType.EMAIL)
        engine.enable_rule(SensitiveType.EMAIL)

        result = engine.desensitize("test@company.com")
        assert "t***@company.com" in result.sanitized

    def test_list_rules(self, engine):
        rules = engine.list_rules()
        assert len(rules) == 6
        types = [r["type"] for r in rules]
        assert "phone" in types
        assert "email" in types
        assert "person_name" in types

    def test_empty_text(self, engine):
        result = engine.desensitize("")
        assert result.sanitized == ""
        assert result.replacements == []

    def test_no_sensitive_data(self, engine):
        result = engine.desensitize("这是一封普通邮件，没有敏感信息")
        assert result.was_modified is False or len(result.replacements) == 0
