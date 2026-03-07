"""Tests for Japanese date formatting utilities."""

import pytest
from datetime import date, datetime

from utils.date_utils import (
    to_wareki,
    to_wareki_short,
    format_date_ja,
    format_datetime_ja,
    get_era_name,
)


class TestToWareki:
    def test_reiwa(self):
        assert to_wareki(date(2026, 3, 7)) == "令和8年3月7日"

    def test_reiwa_first_year(self):
        assert to_wareki(date(2019, 5, 1)) == "令和元年5月1日"

    def test_heisei(self):
        assert to_wareki(date(2019, 4, 30)) == "平成31年4月30日"

    def test_heisei_first_year(self):
        assert to_wareki(date(1989, 1, 8)) == "平成元年1月8日"

    def test_showa(self):
        assert to_wareki(date(1985, 6, 15)) == "昭和60年6月15日"

    def test_taisho(self):
        assert to_wareki(date(1920, 1, 1)) == "大正9年1月1日"

    def test_meiji(self):
        assert to_wareki(date(1900, 12, 25)) == "明治33年12月25日"

    def test_before_meiji_raises(self):
        with pytest.raises(ValueError):
            to_wareki(date(1867, 1, 1))


class TestToWarekiShort:
    def test_reiwa(self):
        assert to_wareki_short(date(2026, 3, 7)) == "R08.03.07"

    def test_heisei(self):
        assert to_wareki_short(date(2000, 1, 1)) == "H12.01.01"

    def test_before_meiji_raises(self):
        with pytest.raises(ValueError):
            to_wareki_short(date(1867, 1, 1))


class TestFormatDateJa:
    def test_with_weekday(self):
        # 2026-03-07 is a Saturday
        assert format_date_ja(date(2026, 3, 7)) == "2026年3月7日(土)"

    def test_without_weekday(self):
        assert format_date_ja(date(2026, 3, 7), include_weekday=False) == "2026年3月7日"

    def test_monday(self):
        # 2026-03-02 is a Monday
        assert format_date_ja(date(2026, 3, 2)) == "2026年3月2日(月)"


class TestFormatDatetimeJa:
    def test_without_seconds(self):
        dt = datetime(2026, 3, 7, 14, 30, 45)
        assert format_datetime_ja(dt) == "2026年3月7日(土) 14:30"

    def test_with_seconds(self):
        dt = datetime(2026, 3, 7, 14, 30, 45)
        assert format_datetime_ja(dt, include_seconds=True) == "2026年3月7日(土) 14:30:45"


class TestGetEraName:
    def test_reiwa(self):
        assert get_era_name(date(2026, 1, 1)) == "令和"

    def test_heisei(self):
        assert get_era_name(date(2000, 1, 1)) == "平成"

    def test_before_meiji(self):
        assert get_era_name(date(1867, 1, 1)) is None
