"""Tests for LogParser service."""

import hashlib
import json
from datetime import datetime, timezone

import pytest

from app.core.exceptions import LogParseError
from app.services.log_parser import LogParser, ParsedLog


@pytest.fixture
def parser():
    return LogParser()


@pytest.fixture
def valid_log_data():
    return {
        "timestamp": "2024-01-15T10:23:45Z",
        "level": "ERROR",
        "service": "auth-service",
        "message": "Connection timeout to database",
        "trace_id": "abc-123-xyz",
        "metadata": {"user_id": "12345"},
    }


# ---------------------------------------------------------------------------
# parse() - happy path
# ---------------------------------------------------------------------------

class TestParseHappyPath:

    def test_parse_valid_log(self, parser, valid_log_data):
        result = parser.parse(valid_log_data)
        assert isinstance(result, ParsedLog)
        assert result.level == "ERROR"
        assert result.service == "auth-service"
        assert result.message == "Connection timeout to database"
        assert result.trace_id == "abc-123-xyz"
        assert result.metadata == {"user_id": "12345"}

    def test_parse_sets_hash(self, parser, valid_log_data):
        result = parser.parse(valid_log_data)
        assert result.log_hash is not None
        assert len(result.log_hash) == 64  # SHA256 hex length

    def test_parse_sets_preview(self, parser, valid_log_data):
        result = parser.parse(valid_log_data)
        assert result.message_preview == "Connection timeout to database"

    def test_parse_normalizes_level_case(self, parser, valid_log_data):
        valid_log_data["level"] = "error"
        result = parser.parse(valid_log_data)
        assert result.level == "ERROR"

    def test_parse_optional_fields_absent(self, parser):
        data = {
            "timestamp": "2024-01-15T10:23:45Z",
            "level": "WARN",
            "service": "web-app",
            "message": "Slow query detected",
        }
        result = parser.parse(data)
        assert result.trace_id is None
        assert result.metadata == {}

    def test_parse_all_valid_levels(self, parser):
        for level in ["ERROR", "WARN", "INFO", "DEBUG"]:
            data = {
                "timestamp": "2024-06-01T00:00:00Z",
                "level": level,
                "service": "svc",
                "message": "msg",
            }
            result = parser.parse(data)
            assert result.level == level

    def test_parse_timestamp_as_datetime(self, parser):
        dt = datetime(2024, 1, 15, 10, 0, 0)
        data = {
            "timestamp": dt,
            "level": "INFO",
            "service": "svc",
            "message": "hello",
        }
        result = parser.parse(data)
        assert result.timestamp == dt


# ---------------------------------------------------------------------------
# parse() - validation errors
# ---------------------------------------------------------------------------

class TestParseValidationErrors:

    def test_missing_timestamp(self, parser):
        with pytest.raises(LogParseError, match="Missing required fields.*timestamp"):
            parser.parse({"level": "ERROR", "service": "s", "message": "m"})

    def test_missing_level(self, parser):
        with pytest.raises(LogParseError, match="Missing required fields.*level"):
            parser.parse({"timestamp": "2024-01-01T00:00:00Z", "service": "s", "message": "m"})

    def test_missing_service(self, parser):
        with pytest.raises(LogParseError, match="Missing required fields.*service"):
            parser.parse({"timestamp": "2024-01-01T00:00:00Z", "level": "ERROR", "message": "m"})

    def test_missing_message(self, parser):
        with pytest.raises(LogParseError, match="Missing required fields.*message"):
            parser.parse({"timestamp": "2024-01-01T00:00:00Z", "level": "ERROR", "service": "s"})

    def test_missing_multiple_fields(self, parser):
        with pytest.raises(LogParseError, match="Missing required fields"):
            parser.parse({"timestamp": "2024-01-01T00:00:00Z"})

    def test_empty_dict(self, parser):
        with pytest.raises(LogParseError):
            parser.parse({})

    def test_invalid_level(self, parser):
        with pytest.raises(LogParseError, match="Invalid level"):
            parser.parse({
                "timestamp": "2024-01-01T00:00:00Z",
                "level": "CRITICAL",
                "service": "s",
                "message": "m",
            })

    def test_non_string_level(self, parser):
        with pytest.raises(LogParseError, match="Level must be a string"):
            parser.parse({
                "timestamp": "2024-01-01T00:00:00Z",
                "level": 123,
                "service": "s",
                "message": "m",
            })

    def test_empty_service(self, parser):
        with pytest.raises(LogParseError, match="Service name cannot be empty"):
            parser.parse({
                "timestamp": "2024-01-01T00:00:00Z",
                "level": "ERROR",
                "service": "   ",
                "message": "m",
            })

    def test_service_too_long(self, parser):
        with pytest.raises(LogParseError, match="Service name too long"):
            parser.parse({
                "timestamp": "2024-01-01T00:00:00Z",
                "level": "ERROR",
                "service": "x" * 101,
                "message": "m",
            })

    def test_non_string_service(self, parser):
        with pytest.raises(LogParseError, match="Service must be a string"):
            parser.parse({
                "timestamp": "2024-01-01T00:00:00Z",
                "level": "ERROR",
                "service": 42,
                "message": "m",
            })

    def test_empty_message(self, parser):
        with pytest.raises(LogParseError, match="Message cannot be empty"):
            parser.parse({
                "timestamp": "2024-01-01T00:00:00Z",
                "level": "ERROR",
                "service": "svc",
                "message": "   ",
            })

    def test_non_string_message(self, parser):
        with pytest.raises(LogParseError, match="Message must be a string"):
            parser.parse({
                "timestamp": "2024-01-01T00:00:00Z",
                "level": "ERROR",
                "service": "svc",
                "message": 999,
            })


# ---------------------------------------------------------------------------
# generate_hash()
# ---------------------------------------------------------------------------

class TestGenerateHash:

    def test_hash_is_64_hex_chars(self, parser, valid_log_data):
        h = parser.generate_hash(valid_log_data)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_input_same_hash(self, parser, valid_log_data):
        h1 = parser.generate_hash(valid_log_data)
        h2 = parser.generate_hash(valid_log_data)
        assert h1 == h2

    def test_different_message_different_hash(self, parser, valid_log_data):
        h1 = parser.generate_hash(valid_log_data)
        valid_log_data["message"] = "Different error"
        h2 = parser.generate_hash(valid_log_data)
        assert h1 != h2

    def test_different_service_different_hash(self, parser, valid_log_data):
        h1 = parser.generate_hash(valid_log_data)
        valid_log_data["service"] = "other-service"
        h2 = parser.generate_hash(valid_log_data)
        assert h1 != h2

    def test_different_level_different_hash(self, parser, valid_log_data):
        h1 = parser.generate_hash(valid_log_data)
        valid_log_data["level"] = "WARN"
        h2 = parser.generate_hash(valid_log_data)
        assert h1 != h2

    def test_timestamp_excluded_from_hash(self, parser, valid_log_data):
        h1 = parser.generate_hash(valid_log_data)
        valid_log_data["timestamp"] = "2099-12-31T23:59:59Z"
        h2 = parser.generate_hash(valid_log_data)
        assert h1 == h2

    def test_different_trace_id_different_hash(self, parser, valid_log_data):
        h1 = parser.generate_hash(valid_log_data)
        valid_log_data["trace_id"] = "different-trace"
        h2 = parser.generate_hash(valid_log_data)
        assert h1 != h2

    def test_hash_without_trace_id(self, parser):
        data_a = {"level": "ERROR", "service": "svc", "message": "msg"}
        data_b = {"level": "ERROR", "service": "svc", "message": "msg", "trace_id": None}
        assert parser.generate_hash(data_a) == parser.generate_hash(data_b)

    def test_level_case_insensitive_for_hash(self, parser):
        data_lower = {"level": "error", "service": "svc", "message": "msg"}
        data_upper = {"level": "ERROR", "service": "svc", "message": "msg"}
        assert parser.generate_hash(data_lower) == parser.generate_hash(data_upper)

    def test_hash_matches_manual_sha256(self, parser):
        data = {"level": "ERROR", "service": "svc", "message": "msg"}
        canonical = {
            "level": "ERROR",
            "message": "msg",
            "service": "svc",
            "trace_id": "",
        }
        expected = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert parser.generate_hash(data) == expected


# ---------------------------------------------------------------------------
# normalize_timestamp()
# ---------------------------------------------------------------------------

class TestNormalizeTimestamp:

    def test_iso_format_string(self, parser):
        result = parser.normalize_timestamp("2024-01-15T10:23:45Z")
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_datetime_passthrough(self, parser):
        dt = datetime(2024, 6, 1, 12, 0, 0)
        assert parser.normalize_timestamp(dt) is dt

    def test_various_string_formats(self, parser):
        formats = [
            "2024-01-15T10:23:45+00:00",
            "2024-01-15 10:23:45",
            "Jan 15, 2024 10:23:45",
            "15/01/2024 10:23:45",
        ]
        for fmt in formats:
            result = parser.normalize_timestamp(fmt)
            assert isinstance(result, datetime), f"Failed for format: {fmt}"

    def test_invalid_string_raises(self, parser):
        with pytest.raises(LogParseError, match="Invalid timestamp format"):
            parser.normalize_timestamp("not-a-date")

    def test_non_string_non_datetime_raises(self, parser):
        with pytest.raises(LogParseError, match="Timestamp must be string or datetime"):
            parser.normalize_timestamp(12345)

    def test_non_string_non_datetime_list_raises(self, parser):
        with pytest.raises(LogParseError, match="Timestamp must be string or datetime"):
            parser.normalize_timestamp([2024, 1, 1])


# ---------------------------------------------------------------------------
# _create_preview()
# ---------------------------------------------------------------------------

class TestCreatePreview:

    def test_short_message_unchanged(self, parser):
        assert parser._create_preview("short") == "short"

    def test_exact_500_chars_unchanged(self, parser):
        msg = "x" * 500
        assert parser._create_preview(msg) == msg

    def test_long_message_truncated(self, parser):
        msg = "a" * 600
        preview = parser._create_preview(msg)
        assert len(preview) == 503  # 500 + "..."
        assert preview.endswith("...")

    def test_501_chars_truncated(self, parser):
        msg = "b" * 501
        preview = parser._create_preview(msg)
        assert preview == "b" * 500 + "..."
