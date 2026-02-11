"""Tests for CLI utility functions (byod_cli/utils.py).

Covers formatting helpers: format_error, format_success, format_warning,
format_info, format_bytes, format_duration, and setup_logging.
"""

import logging

from byod_cli.utils import (
    format_bytes,
    format_duration,
    format_error,
    format_info,
    format_success,
    format_warning,
    setup_logging,
)

# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

class TestFormatMessages:
    def test_format_error(self):
        result = format_error("something broke")
        assert "Error" in result
        assert "something broke" in result

    def test_format_success(self):
        result = format_success("it worked")
        assert "OK" in result
        assert "it worked" in result

    def test_format_warning(self):
        result = format_warning("be careful")
        assert "Warning" in result
        assert "be careful" in result

    def test_format_info(self):
        result = format_info("fyi")
        assert "Info" in result
        assert "fyi" in result


# ---------------------------------------------------------------------------
# Byte formatting
# ---------------------------------------------------------------------------

class TestFormatBytes:
    def test_bytes(self):
        assert format_bytes(0) == "0.00 B"

    def test_kilobytes(self):
        result = format_bytes(1536)
        assert "KB" in result

    def test_megabytes(self):
        result = format_bytes(5 * 1024 * 1024)
        assert result == "5.00 MB"

    def test_gigabytes(self):
        result = format_bytes(2 * 1024 ** 3)
        assert "GB" in result

    def test_terabytes(self):
        result = format_bytes(3 * 1024 ** 4)
        assert "TB" in result

    def test_petabytes(self):
        result = format_bytes(1024 ** 5 + 1024 ** 5)
        assert "PB" in result


# ---------------------------------------------------------------------------
# Duration formatting
# ---------------------------------------------------------------------------

class TestFormatDuration:
    def test_seconds_only(self):
        assert format_duration(5.3) == "5.3s"

    def test_minutes_and_seconds(self):
        assert format_duration(150) == "2m 30s"

    def test_hours_and_minutes(self):
        assert format_duration(3661) == "1h 1m"

    def test_exact_minute(self):
        assert format_duration(60) == "1m 0s"

    def test_less_than_second(self):
        assert format_duration(0.5) == "0.5s"


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------

class TestSetupLogging:
    def test_sets_level(self):
        # Clear existing handlers so basicConfig takes effect
        root = logging.getLogger()
        root.handlers.clear()
        setup_logging("DEBUG")
        assert root.level == logging.DEBUG

    def test_default_level(self):
        root = logging.getLogger()
        root.handlers.clear()
        setup_logging()
        assert root.level == logging.INFO
