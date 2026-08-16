from backend.app.middleware.pii import pii_redactor


def test_pii_redaction():
    text = pii_redactor.redact("电话13812345678，身份证33010219900101123X，邮箱user@example.com")
    assert "13812345678" not in text and "[PHONE]" in text
    assert "33010219900101123X" not in text and "[ID_CARD]" in text
    assert "user@example.com" not in text and "[EMAIL]" in text
