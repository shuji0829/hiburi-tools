"""HIBURI営業自動化システム - 時間制御付き送信スケジューラー

送信ルール:
- 平日のみ（月〜金）
- 8:00〜18:00のみ送信可
- 昼休み（12:00〜13:00）は送信禁止
- 1日の送信上限: 開業医50件 / ナビタ30件
- dry_runモード対応
"""

import json
import logging
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import SEND_RULES, PIPELINE_CLINIC, PIPELINE_NAVITA

JST = ZoneInfo("Asia/Tokyo")

logger = logging.getLogger(__name__)

COUNTER_FILE = Path(__file__).parent.parent / "data" / "daily_counter.json"


class SendTimeValidator:
    """送信可能時間を判定するバリデーター"""

    def __init__(self, rules: dict | None = None):
        self.rules = rules or SEND_RULES

    def now_jst(self) -> datetime:
        return datetime.now(JST)

    def is_weekday(self, dt: datetime | None = None) -> bool:
        dt = dt or self.now_jst()
        return dt.weekday() in self.rules["allowed_days"]

    def is_business_hours(self, dt: datetime | None = None) -> bool:
        dt = dt or self.now_jst()
        hour = dt.hour
        minute = dt.minute
        start = self.rules["allowed_hours_start"]
        end = self.rules["allowed_hours_end"]
        lunch_start = self.rules["lunch_start"]
        lunch_end = self.rules["lunch_end"]

        if hour < start or (hour >= end):
            return False
        if lunch_start <= hour < lunch_end:
            return False
        return True

    def can_send_now(self, dt: datetime | None = None) -> tuple[bool, str]:
        """現在送信可能かどうかを判定し、理由を返す"""
        dt = dt or self.now_jst()

        if not self.is_weekday(dt):
            day_name = ["月", "火", "水", "木", "金", "土", "日"][dt.weekday()]
            return False, f"{day_name}曜日は送信禁止です"

        if dt.hour < self.rules["allowed_hours_start"]:
            return False, f'{self.rules["allowed_hours_start"]}:00より前は送信禁止です'

        if dt.hour >= self.rules["allowed_hours_end"]:
            return False, f'{self.rules["allowed_hours_end"]}:00以降は送信禁止です'

        if self.rules["lunch_start"] <= dt.hour < self.rules["lunch_end"]:
            return False, "昼休み（12:00〜13:00）は送信禁止です"

        return True, "送信可能"

    def next_available_time(self, dt: datetime | None = None) -> datetime:
        """次に送信可能になる日時を返す"""
        dt = dt or self.now_jst()
        candidate = dt.replace(second=0, microsecond=0)

        for _ in range(14 * 24):  # 最大2週間先まで探索
            if candidate.weekday() not in self.rules["allowed_days"]:
                candidate = candidate.replace(
                    hour=self.rules["allowed_hours_start"], minute=0
                )
                days_until_monday = (7 - candidate.weekday()) % 7
                if days_until_monday == 0:
                    days_until_monday = 7
                from datetime import timedelta
                candidate += timedelta(days=days_until_monday)
                continue

            if candidate.hour < self.rules["allowed_hours_start"]:
                candidate = candidate.replace(
                    hour=self.rules["allowed_hours_start"], minute=0
                )
                return candidate

            if candidate.hour >= self.rules["allowed_hours_end"]:
                from datetime import timedelta
                candidate += timedelta(days=1)
                candidate = candidate.replace(
                    hour=self.rules["allowed_hours_start"], minute=0
                )
                continue

            if self.rules["lunch_start"] <= candidate.hour < self.rules["lunch_end"]:
                candidate = candidate.replace(
                    hour=self.rules["lunch_end"], minute=0
                )
                return candidate

            return candidate

        return candidate


class DailyCounter:
    """1日あたりの送信数を管理するカウンター"""

    def __init__(self, counter_file: Path | None = None):
        self.counter_file = counter_file or COUNTER_FILE
        self._ensure_file()

    def _ensure_file(self):
        self.counter_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.counter_file.exists():
            self._reset()

    def _reset(self):
        data = {
            "date": date.today().isoformat(),
            PIPELINE_CLINIC: 0,
            PIPELINE_NAVITA: 0,
        }
        self._save(data)

    def _load(self) -> dict:
        try:
            with open(self.counter_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            self._reset()
            with open(self.counter_file) as f:
                data = json.load(f)

        if data.get("date") != date.today().isoformat():
            self._reset()
            with open(self.counter_file) as f:
                data = json.load(f)

        return data

    def _save(self, data: dict):
        with open(self.counter_file, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_count(self, pipeline: str) -> int:
        data = self._load()
        return data.get(pipeline, 0)

    def get_limit(self, pipeline: str) -> int:
        if pipeline == PIPELINE_CLINIC:
            return SEND_RULES["daily_limit_clinic"]
        elif pipeline == PIPELINE_NAVITA:
            return SEND_RULES["daily_limit_navita"]
        return 0

    def remaining(self, pipeline: str) -> int:
        return max(0, self.get_limit(pipeline) - self.get_count(pipeline))

    def can_send(self, pipeline: str) -> tuple[bool, str]:
        count = self.get_count(pipeline)
        limit = self.get_limit(pipeline)
        if count >= limit:
            return False, f"{pipeline}の1日上限({limit}件)に達しました（送信済: {count}件）"
        return True, f"送信可能（残り: {limit - count}件）"

    def increment(self, pipeline: str, count: int = 1):
        data = self._load()
        data[pipeline] = data.get(pipeline, 0) + count
        self._save(data)
        logger.info(f"[カウンター] {pipeline}: {data[pipeline]}/{self.get_limit(pipeline)}")


class SendScheduler:
    """時間制御と送信数制限を統合したスケジューラー"""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.validator = SendTimeValidator()
        self.counter = DailyCounter()
        self._setup_logging()

    def _setup_logging(self):
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"scheduler_{date.today().isoformat()}.log"

        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in logger.handlers):
            console = logging.StreamHandler()
            console.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            )
            logger.addHandler(console)

    def check_send_permission(self, pipeline: str) -> tuple[bool, str]:
        """送信可否を総合的にチェック"""
        can_time, time_reason = self.validator.can_send_now()
        if not can_time:
            next_time = self.validator.next_available_time()
            return False, f"{time_reason}（次回送信可能: {next_time.strftime('%Y-%m-%d %H:%M')}）"

        can_count, count_reason = self.counter.can_send(pipeline)
        if not can_count:
            return False, count_reason

        return True, "送信許可"

    def execute_send(self, pipeline: str, targets: list[dict], send_func) -> dict:
        """送信を実行する（dry_run対応）

        Args:
            pipeline: パイプライン種別 (clinic/navita)
            targets: 送信先リスト [{"name": str, "email": str, ...}, ...]
            send_func: 実際の送信関数 (target) -> bool

        Returns:
            実行結果の辞書
        """
        mode = "DRY_RUN" if self.dry_run else "LIVE"
        logger.info(f"=== 送信バッチ開始 [{mode}] pipeline={pipeline} 対象={len(targets)}件 ===")

        result = {
            "mode": mode,
            "pipeline": pipeline,
            "total": len(targets),
            "sent": 0,
            "skipped": 0,
            "failed": 0,
            "details": [],
        }

        remaining = self.counter.remaining(pipeline)
        if len(targets) > remaining:
            logger.warning(
                f"対象数({len(targets)})が残り上限({remaining})を超えています。"
                f"上限まで送信します。"
            )
            targets = targets[:remaining]

        for i, target in enumerate(targets):
            can_send, reason = self.check_send_permission(pipeline)
            if not can_send:
                logger.warning(f"[{i+1}/{len(targets)}] 送信不可: {reason}")
                result["skipped"] += len(targets) - i
                for remaining_target in targets[i:]:
                    result["details"].append({
                        "target": remaining_target.get("name", "不明"),
                        "email": remaining_target.get("email", "不明"),
                        "status": "skipped",
                        "reason": reason,
                    })
                break

            target_name = target.get("name", "不明")
            target_email = target.get("email", "不明")

            if self.dry_run:
                logger.info(
                    f"[DRY_RUN] [{i+1}/{len(targets)}] "
                    f"送信予定: {target_name} <{target_email}>"
                )
                result["sent"] += 1
                result["details"].append({
                    "target": target_name,
                    "email": target_email,
                    "status": "dry_run_ok",
                    "reason": "dry_runモードのため実送信なし",
                })
                self.counter.increment(pipeline)
            else:
                try:
                    success = send_func(target)
                    if success:
                        logger.info(
                            f"[SENT] [{i+1}/{len(targets)}] "
                            f"{target_name} <{target_email}>"
                        )
                        result["sent"] += 1
                        result["details"].append({
                            "target": target_name,
                            "email": target_email,
                            "status": "sent",
                        })
                        self.counter.increment(pipeline)
                    else:
                        logger.error(
                            f"[FAILED] [{i+1}/{len(targets)}] "
                            f"{target_name} <{target_email}>"
                        )
                        result["failed"] += 1
                        result["details"].append({
                            "target": target_name,
                            "email": target_email,
                            "status": "failed",
                            "reason": "send_funcがFalseを返しました",
                        })
                except Exception as e:
                    logger.error(
                        f"[ERROR] [{i+1}/{len(targets)}] "
                        f"{target_name} <{target_email}> - {e}"
                    )
                    result["failed"] += 1
                    result["details"].append({
                        "target": target_name,
                        "email": target_email,
                        "status": "error",
                        "reason": str(e),
                    })

        logger.info(
            f"=== 送信バッチ完了 [{mode}] "
            f"送信: {result['sent']} / スキップ: {result['skipped']} / "
            f"失敗: {result['failed']} ==="
        )

        return result

    def status(self) -> dict:
        """現在のスケジューラー状態を返す"""
        now = self.validator.now_jst()
        can_send, reason = self.validator.can_send_now()

        return {
            "current_time": now.strftime("%Y-%m-%d %H:%M:%S (JST)"),
            "dry_run": self.dry_run,
            "can_send_now": can_send,
            "reason": reason,
            "next_available": (
                self.validator.next_available_time().strftime("%Y-%m-%d %H:%M")
                if not can_send else None
            ),
            "clinic": {
                "sent_today": self.counter.get_count(PIPELINE_CLINIC),
                "limit": self.counter.get_limit(PIPELINE_CLINIC),
                "remaining": self.counter.remaining(PIPELINE_CLINIC),
            },
            "navita": {
                "sent_today": self.counter.get_count(PIPELINE_NAVITA),
                "limit": self.counter.get_limit(PIPELINE_NAVITA),
                "remaining": self.counter.remaining(PIPELINE_NAVITA),
            },
        }


if __name__ == "__main__":
    scheduler = SendScheduler(dry_run=True)
    import json as _json
    print(_json.dumps(scheduler.status(), ensure_ascii=False, indent=2))

    # dry_runテスト
    test_targets = [
        {"name": "テスト医院A", "email": "test_a@example.com"},
        {"name": "テスト医院B", "email": "test_b@example.com"},
        {"name": "テスト医院C", "email": "test_c@example.com"},
    ]

    result = scheduler.execute_send(
        pipeline=PIPELINE_CLINIC,
        targets=test_targets,
        send_func=lambda t: True,
    )
    print(_json.dumps(result, ensure_ascii=False, indent=2))
