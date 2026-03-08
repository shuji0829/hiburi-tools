"""
医療機関ホームページ・メールアドレス検索スクリプト

Google Custom Search API を使って事業者名+住所からHPを特定し、
HPからメールアドレスを抽出してExcelに反映する。

使い方:
  python hp_search.py --input 厚生局_新規指定一覧_R0704-R0803.xlsx --limit 100
  python hp_search.py --input 厚生局_新規指定一覧_R0704-R0803.xlsx --resume

環境変数:
  GOOGLE_API_KEY=AIzaSy...
  GOOGLE_CSE_ID=c5323375b80fa4449
"""

import argparse
import json
import os
import re
import sys
import time

import openpyxl
import requests
from urllib.parse import urlparse

# Google Custom Search API 設定
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_CSE_ID = os.environ.get("GOOGLE_CSE_ID", "")

# 除外ドメイン（ポータルサイト等、公式HPではないもの）
EXCLUDE_DOMAINS = {
    "byoinnavi.jp", "caloo.jp", "fdoc.jp", "doctorsfile.jp",
    "medley.life", "hospita.jp", "myclinic.ne.jp", "scuel.me",
    "doctor-map.info", "epark.jp", "google.com", "google.co.jp",
    "yahoo.co.jp", "bing.com", "facebook.com", "twitter.com",
    "instagram.com", "youtube.com", "wikipedia.org",
    "itp.ne.jp", "mapion.co.jp", "navitime.co.jp",
    "ekiten.jp", "qlife.jp", "10man-doc.co.jp",
    "medinew.jp", "medimap.jp", "hospiten.jp",
    "kamponavi.com", "clinicnavi.jp", "mynavi.jp",
    "iryou.teikyouseido.mhlw.go.jp", "kurashi.yahoo.co.jp",
}

# メールアドレスの正規表現
EMAIL_PATTERN = re.compile(
    r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    re.IGNORECASE
)

# 除外メールアドレスパターン
EXCLUDE_EMAIL_PATTERNS = [
    r'.*@example\.com',
    r'.*@test\.com',
    r'.*\.png$',
    r'.*\.jpg$',
    r'.*\.gif$',
    r'.*\.svg$',
    r'wixpress\.com',
    r'sentry\.io',
]

# 進捗ファイル
PROGRESS_FILE = "hp_search_progress.json"


def search_google(query, api_key, cse_id, num=5):
    """Google Custom Search API で検索"""
    resp = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={
            "key": api_key,
            "cx": cse_id,
            "q": query,
            "num": num,
            "lr": "lang_ja",
            "gl": "jp",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("items", [])


def is_official_domain(url, name):
    """ポータルサイトを除外して公式HPらしいか判定"""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    # www.を除去
    if domain.startswith("www."):
        domain = domain[4:]

    # 除外ドメインチェック
    for excl in EXCLUDE_DOMAINS:
        if domain == excl or domain.endswith("." + excl):
            return False

    return True


def extract_emails_from_page(url):
    """URLからメールアドレスを抽出"""
    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; HiburiBot/1.0)"
        })
        if resp.status_code != 200:
            return []
        text = resp.text

        emails = EMAIL_PATTERN.findall(text)
        # フィルタリング
        filtered = []
        for email in emails:
            skip = False
            for pattern in EXCLUDE_EMAIL_PATTERNS:
                if re.match(pattern, email, re.IGNORECASE):
                    skip = True
                    break
            if not skip and email not in filtered:
                filtered.append(email)
        return filtered
    except Exception:
        return []


def find_hp_and_email(name, address, api_key, cse_id):
    """事業者名+住所から公式HPとメールアドレスを検索"""
    # 住所から都道府県+市区町村を抽出（短縮）
    addr_short = ""
    addr_match = re.search(r'[^\d〒\s]{2,3}[都道府県].{2,6}[市区町村郡]', address or "")
    if addr_match:
        addr_short = addr_match.group()

    query = f"{name} {addr_short} 公式"
    results = search_google(query, api_key, cse_id, num=5)

    hp_url = None
    email = None

    # 検索結果から公式HPを特定
    for item in results:
        url = item.get("link", "")
        if is_official_domain(url, name):
            hp_url = url
            break

    # HPが見つかった場合、メールアドレスを抽出
    if hp_url:
        # ドメインのトップページも確認
        parsed = urlparse(hp_url)
        top_url = f"{parsed.scheme}://{parsed.netloc}/"
        urls_to_check = [hp_url]
        if hp_url != top_url:
            urls_to_check.append(top_url)

        for check_url in urls_to_check:
            emails = extract_emails_from_page(check_url)
            if emails:
                email = emails[0]  # 最初のメールアドレスを使用
                break

        # メール見つからない場合、/contact や /about ページも試行
        if not email:
            for suffix in ["/contact", "/contact/", "/about", "/access"]:
                contact_url = top_url.rstrip("/") + suffix
                emails = extract_emails_from_page(contact_url)
                if emails:
                    email = emails[0]
                    break

    return hp_url, email


def load_progress():
    """進捗ファイルを読み込み"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(progress):
    """進捗ファイルを保存"""
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="医療機関HP・メール検索")
    parser.add_argument("--input", required=True, help="入力Excelファイル")
    parser.add_argument("--sheet", default="新規指定一覧", help="シート名")
    parser.add_argument("--limit", type=int, default=0, help="処理件数上限 (0=全件)")
    parser.add_argument("--resume", action="store_true", help="前回の続きから再開")
    parser.add_argument("--delay", type=float, default=1.0, help="API呼び出し間隔(秒)")
    parser.add_argument("--api-key", default=None, help="Google API Key")
    parser.add_argument("--cse-id", default=None, help="Google CSE ID")
    args = parser.parse_args()

    api_key = args.api_key or GOOGLE_API_KEY
    cse_id = args.cse_id or GOOGLE_CSE_ID

    if not api_key or not cse_id:
        print("エラー: GOOGLE_API_KEY と GOOGLE_CSE_ID を環境変数またはオプションで指定してください")
        print("  export GOOGLE_API_KEY=AIzaSy...")
        print("  export GOOGLE_CSE_ID=c5323375b80fa4449")
        sys.exit(1)

    # Excel読み込み
    wb = openpyxl.load_workbook(args.input)
    ws = wb[args.sheet]
    rows = list(ws.iter_rows(values_only=True))
    headers = list(rows[0])

    # 列インデックス特定
    name_idx = headers.index("事業者名")
    addr_idx = headers.index("住所")
    hp_idx = headers.index("ホームページ")
    email_idx = headers.index("メールアドレス")
    wb.close()

    # 進捗管理
    progress = load_progress() if args.resume else {}

    total = len(rows) - 1
    limit = args.limit if args.limit > 0 else total
    searched = 0
    found_hp = 0
    found_email = 0
    api_calls = 0

    print(f"対象: {total} 件 (上限: {limit} 件)")
    print(f"既処理: {len(progress)} 件")
    print()

    # 書き込み用にExcelを再オープン
    wb = openpyxl.load_workbook(args.input)
    ws = wb[args.sheet]

    try:
        for row_num, row in enumerate(rows[1:], start=2):
            if searched >= limit:
                break

            name = str(row[name_idx] or "").strip()
            address = str(row[addr_idx] or "").strip()

            if not name:
                continue

            # 既にHPが入力済みならスキップ
            existing_hp = row[hp_idx]
            if existing_hp:
                continue

            # 進捗チェック
            if name in progress:
                # 進捗にあるが未書き込みの場合は書き込み
                hp = progress[name].get("hp")
                em = progress[name].get("email")
                if hp:
                    ws.cell(row=row_num, column=hp_idx + 1, value=hp)
                if em:
                    ws.cell(row=row_num, column=email_idx + 1, value=em)
                continue

            # Google検索
            try:
                hp, em = find_hp_and_email(name, address, api_key, cse_id)
                api_calls += 1
            except requests.exceptions.HTTPError as e:
                if "429" in str(e) or "403" in str(e):
                    print(f"\nAPI制限到達 ({e}). 中間保存して終了します。")
                    break
                raise

            # 結果保存
            progress[name] = {"hp": hp, "email": em}

            if hp:
                ws.cell(row=row_num, column=hp_idx + 1, value=hp)
                found_hp += 1
            if em:
                ws.cell(row=row_num, column=email_idx + 1, value=em)
                found_email += 1

            searched += 1
            if searched % 10 == 0:
                print(f"  {searched}/{limit} 件処理 (HP: {found_hp}, Email: {found_email}, API: {api_calls}回)")
                # 中間保存
                save_progress(progress)
                wb.save(args.input)

            time.sleep(args.delay)

    except KeyboardInterrupt:
        print("\n中断されました。保存中...")

    # 最終保存
    save_progress(progress)
    wb.save(args.input)
    wb.close()

    print(f"\n完了:")
    print(f"  処理件数: {searched}")
    print(f"  HP発見: {found_hp}")
    print(f"  メール発見: {found_email}")
    print(f"  API呼び出し: {api_calls} 回")
    print(f"  進捗保存: {PROGRESS_FILE}")


if __name__ == "__main__":
    main()
