"""
HIBURI Tools 共通設定
"""

import os
from pathlib import Path

# .envファイルの読み込み（python-dotenvが無くても動作）
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

# Notion API 設定
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Excel列名 → Notionプロパティ名のマッピング
# クリニック顧客データベースのスキーマに合わせる
COLUMN_ALIASES = {
    "施設名": "会社名",
    "事業者名": "会社名",
    "メールアドレス": "メールアドレス",
    "区分": "診療科目",
    "カテゴリ": "診療科目",
    "住所": "所在地",
    "データソース": "リードソース",
    "電話番号": "電話番号",
    "ホームページ": "備考",  # 備考フィールドにHP URLを記載
}

# データソースのデフォルト値（リードソースの選択肢に合わせる）
DEFAULT_DATA_SOURCE = "DMアウトバウンド"

# Notionプロパティ名 → タイプ定義（クリニック顧客データベース）
PROPERTY_TYPES = {
    "会社名": "title",
    "メールアドレス": "email",
    "ステータス": "select",        # リード / 見込み / アクティブ顧客 / 非アクティブ顧客
    "診療科目": "multi_select",    # 内科 / 歯科 / 薬局 etc.
    "所在地": "rich_text",
    "リードソース": "select",      # DMアウトバウンド / リファラル etc.
    "電話番号": "phone_number",
    "備考": "rich_text",
    "院長名": "rich_text",
    "担当者氏名": "rich_text",
}

# 厚生局スクレイパー設定
KOUSEIKYOKU_BASE_URL = "https://kouseikyoku.mhlw.go.jp"
KOUSEIKYOKU_REGIONS = {
    "関東信越": "/kantoshinetsu/chousa/shitei.html",
}

# メール送信設定（Google Workspace / Gmail）
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "shuji.tomitaka@hiburi.co.jp")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")  # Googleアプリパスワード
FROM_EMAIL = os.environ.get("FROM_EMAIL", "shuji.tomitaka@hiburi.co.jp")
FROM_NAME = os.environ.get("FROM_NAME", "HIBURI株式会社 富高修司")

# メール送信制限
EMAIL_BATCH_SIZE = 50       # 1回の実行で送信する最大件数
EMAIL_DELAY_SECONDS = 5     # メール間の待機時間（秒）

# スケジューラ設定
SCHEDULE_SCRAPER_DAY = "monday"  # 毎週月曜
SCHEDULE_SCRAPER_TIME = "09:00"
SCHEDULE_SYNC_TIME = "00:00"    # 毎日0時（Notion同期）
SCHEDULE_HP_SEARCH_TIME = "20:00"  # 毎日20時（HP検索）
SCHEDULE_PIPELINE_TIME = "09:00"  # 毎日9時（メール送信）

# HP検索設定
HP_SEARCH_DAILY_LIMIT = 200  # 1日あたりの検索件数上限
HP_SEARCH_EXCEL = os.environ.get(
    "HP_SEARCH_EXCEL", "厚生局_新規指定一覧_R0704-R0803.xlsx"
)
