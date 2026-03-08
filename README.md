# HIBURI営業自動化システム

株式会社HIBURIの営業活動を自動化するPythonシステムです。

## システム概要

2つの営業パイプラインを自動化します。

| パイプライン | 内容 | 1日上限 |
|---|---|---|
| 新規開業医 | 厚生局の新規開業データ → 診療科別メール → Notion CRM | 50件/日 |
| ナビタ | 駅周辺事業者(Google Maps) → 業種別メール → Notion CRM | 30件/日 |

### 送信ルール

- 平日のみ（土日禁止）
- 8:00〜18:00のみ（昼休み12:00〜13:00は禁止）
- 全実行ログをNotionに自動記録
- dry_runモードで事前確認可能

## ファイル構成

```
hiburi-tools/
├── run_all_dry.py            # 統合dry_runスクリプト（まずこれを実行）
├── requirements.txt
├── .env.example              # 環境変数テンプレート
├── src/
│   ├── config.py             # 設定・送信ルール定義
│   ├── scheduler.py          # 時間制御付き送信スケジューラー
│   ├── notion_client.py      # Notion API連携（CRM・ログ）
│   ├── mail_sender.py        # Outlook VBA連携メール送信
│   ├── medical_scraper.py    # 厚生局スクレイピング
│   ├── email_generator.py    # 診療科別メールテンプレート（Claude API対応）
│   └── navita_pipeline.py    # ナビタパイプライン統合
├── tests/                    # テストスイート（83テスト）
├── vba/
│   └── SendFromCSV.bas       # Outlook VBAマクロ
├── data/                     # ランタイムデータ（gitignore）
└── logs/                     # 実行ログ（gitignore）
```

## 初回セットアップ手順

### 1. リポジトリのクローン

```bash
git clone https://github.com/shuji0829/hiburi-tools.git
cd hiburi-tools
```

### 2. Python環境の準備

Python 3.11以上が必要です。

```bash
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 3. 環境変数の設定

```bash
cp .env.example .env
```

`.env` ファイルを開き、以下のAPIキーを設定してください。

| 変数名 | 取得先 | 用途 |
|---|---|---|
| `NOTION_API_KEY` | [Notion Integrations](https://www.notion.so/my-integrations) | CRM・ログ管理 |
| `NOTION_CRM_DATABASE_ID` | NotionデータベースのURL | 事業者管理DB |
| `NOTION_LOG_DATABASE_ID` | NotionデータベースのURL | 実行ログDB |
| `GOOGLE_MAPS_API_KEY` | [Google Cloud Console](https://console.cloud.google.com/) | 周辺事業者検索 |
| `ANTHROPIC_API_KEY` | [Anthropic Console](https://console.anthropic.com/) | メールAI生成（任意） |

### 4. Notion データベースの準備

以下の2つのデータベースをNotionに作成してください。

#### CRM管理データベース

| プロパティ名 | タイプ |
|---|---|
| 事業者名 | タイトル |
| メールアドレス | メール |
| パイプライン | セレクト（clinic / navita） |
| カテゴリ | セレクト |
| 住所 | テキスト |
| ステータス | セレクト（new / contacted / replied） |
| データソース | セレクト（厚生局 / Googleマップ） |
| 登録日 | 日付 |

#### 実行ログデータベース

| プロパティ名 | タイプ |
|---|---|
| アクション | タイトル |
| パイプライン | セレクト |
| 対象 | テキスト |
| ステータス | セレクト（success / failed / dry_run） |
| 詳細 | テキスト |
| 実行モード | セレクト（dry_run / live） |
| 実行日時 | 日付 |

### 5. Google Maps APIの有効化

Google Cloud Consoleで以下のAPIを有効にしてください。

- Places API
- Geocoding API

### 6. テスト実行

```bash
python -m pytest tests/ -v
```

全83テストが通過すればセットアップ完了です。

### 7. 統合dry_run

```bash
python run_all_dry.py
```

全パイプラインがdry_runモードで実行され、以下を確認できます。

- 厚生局スクレイピング（サンプルデータ）
- 5診療科のメールテンプレート生成
- ナビタパイプライン（サンプル駅・事業者）
- スケジューラーの送信可否判定

実行結果は `logs/dry_run_YYYY-MM-DD.log` に保存されます。

## 本番運用への切り替え

dry_runで問題がなければ、各モジュールの `dry_run=False` に変更して実行します。

```python
# 開業医パイプライン
from src.medical_scraper import MedicalScraper
scraper = MedicalScraper(dry_run=False)  # False に変更
scraper.run(bureaus=["関東信越"])

# ナビタパイプライン
from src.navita_pipeline import NavitaPipeline
pipeline = NavitaPipeline(dry_run=False)  # False に変更
pipeline.run()
```

## ナビタ駅リストの設定

`data/navita_stations.csv` にナビタ設置駅の情報を登録してください。

```csv
station_name,line_name,renewal_month,lat,lng
渋谷,JR山手線,6,35.6580,139.7016
新宿,JR山手線,9,35.6896,139.7006
```

- `renewal_month`: ナビタ広告の年1回の更新月（1〜12）
- 更新月の3ヶ月前から自動でアプローチ対象になります

## VBAマクロ（Outlookメール送信）

Windows環境でOutlookから直接メール送信する場合:

1. Outlookを開く → Alt+F11 でVBAエディタを起動
2. `vba/SendFromCSV.bas` をインポート
3. Pythonで生成されたCSVキューファイルのパスを指定して実行

## 商材一覧

メールテンプレートに組み込まれているHIBURIの商材:

- ホームページ制作・リニューアル
- WEB広告運用（Google広告・SNS広告）
- DXサポート（予約システム・電子カルテ連携・業務効率化）
- 経営コンサルティング
