"""Tests for SMTP_RECIPIENTS env var parsing (B1 fix)."""

from unittest.mock import patch

from cic_daily_report.delivery.email_backup import EmailBackup, _parse_recipients


class TestParseRecipients:
    def test_empty_string(self):
        assert _parse_recipients("") == []

    def test_single_email(self):
        assert _parse_recipients("a@x.com") == ["a@x.com"]

    def test_multiple_emails(self):
        result = _parse_recipients("a@x.com, b@y.com, c@z.com")
        assert result == ["a@x.com", "b@y.com", "c@z.com"]

    def test_strips_whitespace(self):
        result = _parse_recipients("  a@x.com ,  b@y.com  ")
        assert result == ["a@x.com", "b@y.com"]

    def test_ignores_empty_parts(self):
        result = _parse_recipients("a@x.com,,b@y.com,")
        assert result == ["a@x.com", "b@y.com"]


class TestEmailBackupRecipients:
    def test_loads_from_env(self):
        with patch.dict("os.environ", {"SMTP_RECIPIENTS": "a@x.com,b@y.com"}):
            backup = EmailBackup(smtp_email="test@g.com", smtp_password="p")
            assert backup._recipients == ["a@x.com", "b@y.com"]

    def test_constructor_overrides_env(self):
        with patch.dict("os.environ", {"SMTP_RECIPIENTS": "env@x.com"}):
            backup = EmailBackup(
                smtp_email="test@g.com",
                smtp_password="p",
                recipients=["override@y.com"],
            )
            assert backup._recipients == ["override@y.com"]

    def test_empty_env_fallback(self):
        with patch.dict("os.environ", {}, clear=True):
            backup = EmailBackup(smtp_email="test@g.com", smtp_password="p")
            assert backup._recipients == []
