"""Tests for custom exceptions."""

import pytest

from app.core.exceptions import (
    LogAnalysisError,
    LogParseError,
    AnalysisError,
    LogNotFoundError,
    AnalysisNotFoundError,
    DuplicateLogError,
)


class TestLogAnalysisError:
    """Tests for the base LogAnalysisError."""

    def test_default_message(self):
        err = LogAnalysisError()
        assert err.message is None
        assert err.details == {}

    def test_custom_message(self):
        err = LogAnalysisError("something broke")
        assert err.message == "something broke"
        assert str(err) == "something broke"

    def test_custom_details(self):
        details = {"key": "value"}
        err = LogAnalysisError("msg", details)
        assert err.details == details

    def test_is_exception(self):
        err = LogAnalysisError("test")
        assert isinstance(err, Exception)


class TestLogParseError:
    """Tests for LogParseError."""

    def test_default_message(self):
        err = LogParseError()
        assert err.message == "Invalid log format"

    def test_custom_message(self):
        err = LogParseError("bad field")
        assert err.message == "bad field"

    def test_inherits_base(self):
        err = LogParseError()
        assert isinstance(err, LogAnalysisError)
        assert isinstance(err, Exception)

    def test_with_details(self):
        err = LogParseError("err", {"field": "level"})
        assert err.details["field"] == "level"


class TestAnalysisError:
    """Tests for AnalysisError."""

    def test_default_message(self):
        err = AnalysisError()
        assert err.message == "Analysis failed"

    def test_custom_message(self):
        err = AnalysisError("AI timeout")
        assert err.message == "AI timeout"

    def test_inherits_base(self):
        assert isinstance(AnalysisError(), LogAnalysisError)


class TestLogNotFoundError:
    """Tests for LogNotFoundError."""

    def test_without_id(self):
        err = LogNotFoundError()
        assert "Log entry not found" in err.message
        assert err.details["log_id"] is None

    def test_with_id(self):
        err = LogNotFoundError("abc-123")
        assert "abc-123" in err.message
        assert err.details["log_id"] == "abc-123"

    def test_inherits_base(self):
        assert isinstance(LogNotFoundError(), LogAnalysisError)


class TestAnalysisNotFoundError:
    """Tests for AnalysisNotFoundError."""

    def test_without_id(self):
        err = AnalysisNotFoundError()
        assert "Analysis result not found" in err.message
        assert err.details["analysis_id"] is None

    def test_with_id(self):
        err = AnalysisNotFoundError("xyz-789")
        assert "xyz-789" in err.message
        assert err.details["analysis_id"] == "xyz-789"

    def test_inherits_base(self):
        assert isinstance(AnalysisNotFoundError(), LogAnalysisError)


class TestDuplicateLogError:
    """Tests for DuplicateLogError."""

    def test_without_hash(self):
        err = DuplicateLogError()
        assert "Duplicate log entry detected" in err.message
        assert err.details["log_hash"] is None

    def test_with_hash(self):
        err = DuplicateLogError("sha256hash")
        assert "sha256hash" in err.message
        assert err.details["log_hash"] == "sha256hash"

    def test_inherits_base(self):
        assert isinstance(DuplicateLogError(), LogAnalysisError)
