"""スケジューラーのユニットテスト"""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.scheduler import SendTimeValidator, DailyCounter, SendScheduler
from src.config import PIPELINE_CLINIC, PIPELINE_NAVITA

JST = ZoneInfo("Asia/Tokyo")


def make_dt(year=2026, month=3, day=6, hour=10, minute=0, weekday=None):
    """テスト用のdatetime生成（dayでweekdayを調整）"""
    dt = datetime(year, month, day, hour, minute, tzinfo=JST)
    return dt


class TestSendTimeValidator:
    def setup_method(self):
        self.v = SendTimeValidator()

    def test_weekday_monday(self):
        # 2026-03-02 = 月曜日
        dt = make_dt(day=2, hour=10)
        assert self.v.is_weekday(dt) is True

    def test_weekday_saturday(self):
        # 2026-03-07 = 土曜日
        dt = make_dt(day=7, hour=10)
        assert self.v.is_weekday(dt) is False

    def test_weekday_sunday(self):
        # 2026-03-08 = 日曜日
        dt = make_dt(day=8, hour=10)
        assert self.v.is_weekday(dt) is False

    def test_business_hours_morning_ok(self):
        dt = make_dt(day=2, hour=8)
        assert self.v.is_business_hours(dt) is True

    def test_business_hours_too_early(self):
        dt = make_dt(day=2, hour=7, minute=59)
        assert self.v.is_business_hours(dt) is False

    def test_business_hours_too_late(self):
        dt = make_dt(day=2, hour=18)
        assert self.v.is_business_hours(dt) is False

    def test_business_hours_lunch_blocked(self):
        dt = make_dt(day=2, hour=12, minute=30)
        assert self.v.is_business_hours(dt) is False

    def test_business_hours_after_lunch(self):
        dt = make_dt(day=2, hour=13, minute=0)
        assert self.v.is_business_hours(dt) is True

    def test_can_send_weekday_business(self):
        dt = make_dt(day=2, hour=10)
        ok, reason = self.v.can_send_now(dt)
        assert ok is True

    def test_can_send_weekend_blocked(self):
        dt = make_dt(day=7, hour=10)
        ok, reason = self.v.can_send_now(dt)
        assert ok is False
        assert "土曜日" in reason

    def test_can_send_lunch_blocked(self):
        dt = make_dt(day=2, hour=12)
        ok, reason = self.v.can_send_now(dt)
        assert ok is False
        assert "昼休み" in reason

    def test_next_available_from_lunch(self):
        dt = make_dt(day=2, hour=12, minute=30)
        nxt = self.v.next_available_time(dt)
        assert nxt.hour == 13
        assert nxt.minute == 0

    def test_next_available_from_evening(self):
        dt = make_dt(day=2, hour=19)
        nxt = self.v.next_available_time(dt)
        assert nxt.hour == 8
        assert nxt.day == 3  # 翌日

    def test_next_available_from_saturday(self):
        # 2026-03-07 = 土曜日 → 次は月曜 03-09
        dt = make_dt(day=7, hour=10)
        nxt = self.v.next_available_time(dt)
        assert nxt.weekday() == 0  # 月曜
        assert nxt.hour == 8


class TestDailyCounter:
    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.counter = DailyCounter(counter_file=Path(self.tmp.name))

    def test_initial_count_zero(self):
        assert self.counter.get_count(PIPELINE_CLINIC) == 0

    def test_increment(self):
        self.counter.increment(PIPELINE_CLINIC, 3)
        assert self.counter.get_count(PIPELINE_CLINIC) == 3

    def test_remaining(self):
        self.counter.increment(PIPELINE_CLINIC, 10)
        assert self.counter.remaining(PIPELINE_CLINIC) == 40  # 50 - 10

    def test_limit_reached(self):
        self.counter.increment(PIPELINE_CLINIC, 50)
        ok, reason = self.counter.can_send(PIPELINE_CLINIC)
        assert ok is False
        assert "上限" in reason

    def test_navita_limit(self):
        self.counter.increment(PIPELINE_NAVITA, 30)
        ok, _ = self.counter.can_send(PIPELINE_NAVITA)
        assert ok is False


class TestSendSchedulerDryRun:
    def test_dry_run_sends_nothing(self):
        scheduler = SendScheduler(dry_run=True)
        scheduler.counter = DailyCounter(
            counter_file=Path(tempfile.mktemp(suffix=".json"))
        )
        # 時間チェックをバイパスするため、常にTrueを返すバリデーターを注入
        scheduler.validator = type("MockValidator", (), {
            "can_send_now": lambda self, dt=None: (True, "テスト"),
            "now_jst": lambda self: datetime(2026, 3, 2, 10, 0, tzinfo=JST),
            "next_available_time": lambda self, dt=None: datetime(2026, 3, 2, 10, 0, tzinfo=JST),
        })()

        actual_sends = []
        def mock_send(target):
            actual_sends.append(target)
            return True

        targets = [
            {"name": "テストA", "email": "a@test.com"},
            {"name": "テストB", "email": "b@test.com"},
        ]

        result = scheduler.execute_send(PIPELINE_CLINIC, targets, mock_send)

        assert result["mode"] == "DRY_RUN"
        assert result["sent"] == 2
        assert len(actual_sends) == 0  # dry_runなので実送信なし

    def test_status_output(self):
        scheduler = SendScheduler(dry_run=True)
        status = scheduler.status()
        assert "dry_run" in status
        assert status["dry_run"] is True
        assert "clinic" in status
        assert "navita" in status
