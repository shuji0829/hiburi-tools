"""
厚生局スクレイパー
関東信越厚生局の保険医療機関・保険薬局の新規指定PDFから
医療機関情報を取得してExcel/Notionに出力する

対象: https://kouseikyoku.mhlw.go.jp/kantoshinetsu/chousa/shitei.html

取得項目:
  - 医療機関名称（事業者名）
  - 住所
  - 電話番号
  - ホームページ（ドメイン推定）
  - メールアドレス（ドメインから推定）
"""

import argparse
import os
import re
import sys
import tempfile
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

from config import (
    KOUSEIKYOKU_BASE_URL, NOTION_TOKEN, NOTION_DATABASE_ID,
    DEFAULT_DATA_SOURCE,
)
from notion_client import build_notion_properties, query_existing_pages, create_page
from excel_client import write_excel


# 都道府県コード → 名前
PREFECTURE_CODES = {
    "08": "茨城県", "09": "栃木県", "10": "群馬県",
    "11": "埼玉県", "12": "千葉県", "13": "東京都",
    "14": "神奈川県", "15": "新潟県", "19": "山梨県", "20": "長野県",
}

# 新規指定PDFのURLパターン
SHINKI_PDF_PATTERN = re.compile(
    r'(\d{2,3})shinki_[a-z]+_r(\d{4})\.pdf', re.IGNORECASE
)


def fetch_pdf_links(page_url):
    """指定ページからshinki(新規)PDFリンクを全て取得"""
    print(f"ページ取得中: {page_url}")
    resp = requests.get(page_url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")

    pdf_links = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "shinki" in href.lower() and href.endswith(".pdf"):
            full_url = urljoin(page_url, href)
            match = SHINKI_PDF_PATTERN.search(href)
            if match:
                pref_code = match.group(1)
                # 3桁の場合は先頭2桁が都道府県コード
                if len(pref_code) == 3:
                    pref_code = pref_code[:2]
                period = match.group(2)  # e.g. "0803" = 令和8年3月
                pref_name = PREFECTURE_CODES.get(pref_code, f"不明({pref_code})")
                pdf_links.append({
                    "url": full_url,
                    "prefecture": pref_name,
                    "pref_code": pref_code,
                    "period": f"令和{period[:2]}年{period[2:]}月",
                    "period_raw": period,
                })
            else:
                pdf_links.append({
                    "url": full_url,
                    "prefecture": "不明",
                    "pref_code": "",
                    "period": "",
                    "period_raw": "",
                })

    print(f"  → 新規指定PDF: {len(pdf_links)} 件検出")
    return pdf_links


def download_pdf(url, dest_dir):
    """PDFをダウンロードして保存"""
    filename = url.split("/")[-1]
    filepath = os.path.join(dest_dir, filename)
    if os.path.exists(filepath):
        return filepath
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with open(filepath, "wb") as f:
        f.write(resp.content)
    return filepath


def extract_from_pdf(pdf_path, prefecture):
    """PDFからテーブルデータを抽出"""
    if pdfplumber is None:
        print("  警告: pdfplumber がインストールされていません。pip install pdfplumber")
        return []

    records = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                    records.extend(
                        _parse_table_rows(table, prefecture)
                    )
    except Exception as e:
        print(f"  PDF解析エラー ({pdf_path}): {e}")
    return records


def _parse_table_rows(table, prefecture):
    """テーブル行から医療機関情報を抽出"""
    records = []
    if not table or len(table) < 2:
        return records

    # ヘッダー行を探す
    header_idx = _find_header_in_table(table)
    if header_idx is None:
        return records

    headers = [str(c).strip().replace("\n", "") if c else "" for c in table[header_idx]]
    col_map = _map_columns(headers)

    if "name" not in col_map:
        return records

    for row in table[header_idx + 1:]:
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue

        name = _get_cell(row, col_map.get("name"))
        if not name or len(name) < 2:
            continue

        # 明らかにヘッダー行やフッター行をスキップ
        if any(kw in name for kw in ["名称", "合計", "件数", "※"]):
            continue

        address = _get_cell(row, col_map.get("address")) or ""
        phone = _get_cell(row, col_map.get("phone")) or ""
        category = _get_cell(row, col_map.get("category")) or ""

        # 改行やスペースをクリーン
        name = re.sub(r'\s+', ' ', name).strip()
        address = re.sub(r'\s+', ' ', address).strip()
        phone = re.sub(r'[^\d\-()]', '', phone).strip()

        record = {
            "事業者名": name,
            "住所": f"{prefecture}{address}" if address and prefecture not in address else address,
            "電話番号": phone,
            "カテゴリ": category if category else "医療機関",
            "データソース": DEFAULT_DATA_SOURCE,
            "パイプライン": "新規",
        }

        # ドメイン・メールアドレス推定
        homepage, email = _guess_web_presence(name, address)
        if homepage:
            record["ホームページ"] = homepage
        if email:
            record["メールアドレス"] = email

        records.append(record)

    return records


def _find_header_in_table(table):
    """テーブル内でヘッダー行を探す"""
    header_keywords = ["名称", "所在地", "住所", "電話", "開設者"]
    for idx, row in enumerate(table):
        if not row:
            continue
        text = " ".join(str(c) for c in row if c)
        matches = sum(1 for kw in header_keywords if kw in text)
        if matches >= 2:
            return idx
    return None


def _map_columns(headers):
    """ヘッダーからカラムインデックスマッピングを作成"""
    col_map = {}
    for idx, h in enumerate(headers):
        if not h:
            continue
        if any(kw in h for kw in ["名称", "医療機関名"]):
            col_map["name"] = idx
        elif any(kw in h for kw in ["所在地", "住所"]):
            col_map["address"] = idx
        elif "電話" in h:
            col_map["phone"] = idx
        elif any(kw in h for kw in ["種別", "区分", "診療科"]):
            col_map["category"] = idx
    return col_map


def _get_cell(row, idx):
    """行からセル値を安全に取得"""
    if idx is None or idx >= len(row):
        return None
    val = row[idx]
    if val is None:
        return None
    return str(val).strip()


def _guess_web_presence(name, address):
    """医療機関名からホームページ・メールアドレスを推定

    注: あくまで推定。実際のURL確認は別途必要。
    今後、Google検索API等で実際のURLを取得する拡張が可能。
    """
    # 現時点では推定せず空を返す
    # 将来的にはGoogle Custom Search APIやwhois等で取得可能
    return None, None


def scrape_all(page_url, output_dir=None, target_period=None, target_prefecture=None):
    """メインスクレイピング処理"""
    pdf_links = fetch_pdf_links(page_url)

    # フィルタリング
    if target_period:
        pdf_links = [p for p in pdf_links if target_period in p["period_raw"]]
        print(f"  期間フィルタ ({target_period}): {len(pdf_links)} 件")
    if target_prefecture:
        pdf_links = [p for p in pdf_links if target_prefecture in p["prefecture"]]
        print(f"  都道府県フィルタ ({target_prefecture}): {len(pdf_links)} 件")

    if not pdf_links:
        print("対象PDFが見つかりません")
        return []

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="kouseikyoku_")
    os.makedirs(output_dir, exist_ok=True)

    all_records = []
    for info in pdf_links:
        print(f"\n--- {info['prefecture']} ({info['period']}) ---")
        print(f"  PDF: {info['url']}")
        try:
            pdf_path = download_pdf(info["url"], output_dir)
            records = extract_from_pdf(pdf_path, info["prefecture"])
            for r in records:
                r["_period"] = info["period"]
                r["_prefecture"] = info["prefecture"]
            print(f"  → {len(records)} 件抽出")
            all_records.extend(records)
        except Exception as e:
            print(f"  エラー: {e}")

    print(f"\n合計: {len(all_records)} 件の医療機関を抽出")
    return all_records


def output_to_excel(records, file_path):
    """結果をExcelに出力"""
    headers = ["事業者名", "住所", "電話番号", "ホームページ", "メールアドレス",
               "カテゴリ", "パイプライン", "データソース"]
    write_excel(file_path, "新規指定一覧", records, headers=headers)


def output_to_notion(records, dry_run=False):
    """結果をNotionに出力（重複チェック付き）"""
    print("\nNotionへ出力中...")
    existing = query_existing_pages()
    print(f"  既存ページ: {len(existing)} 件")

    created = 0
    skipped = 0
    failed = 0

    for record in records:
        name = record.get("事業者名", "")
        if not name:
            skipped += 1
            continue
        if name in existing:
            skipped += 1
            continue

        properties = build_notion_properties(record)
        if dry_run:
            print(f"  [新規作成(予定)] {name}")
            created += 1
        else:
            try:
                create_page(properties)
                created += 1
                existing[name] = True  # 重複防止
            except Exception as e:
                print(f"  [エラー] {name}: {e}")
                failed += 1

    print(f"\nNotion出力完了: 新規 {created}, スキップ {skipped}, 失敗 {failed}")


def main():
    parser = argparse.ArgumentParser(description="厚生局 新規指定医療機関スクレイパー")
    parser.add_argument("--url", default="https://kouseikyoku.mhlw.go.jp/kantoshinetsu/chousa/shitei.html",
                        help="厚生局ページURL")
    parser.add_argument("--period", default=None,
                        help="対象期間 (例: 0803 = 令和8年3月)")
    parser.add_argument("--prefecture", default=None,
                        help="対象都道府県 (例: 東京都)")
    parser.add_argument("--output-dir", default="./pdf_cache",
                        help="PDFダウンロード先ディレクトリ")
    parser.add_argument("--to-excel", default=None,
                        help="結果をExcelに出力 (ファイルパス指定)")
    parser.add_argument("--to-notion", action="store_true",
                        help="結果をNotionに出力")
    parser.add_argument("--dry-run", action="store_true",
                        help="確認のみ")
    args = parser.parse_args()

    if args.to_notion and not NOTION_TOKEN:
        print("エラー: NOTION_TOKEN 環境変数を設定してください")
        sys.exit(1)

    records = scrape_all(
        args.url,
        output_dir=args.output_dir,
        target_period=args.period,
        target_prefecture=args.prefecture,
    )

    if not records:
        print("抽出データなし")
        return

    # デフォルト出力: Excel
    if args.to_excel:
        output_to_excel(records, args.to_excel)
    elif args.to_notion:
        output_to_notion(records, dry_run=args.dry_run)
    else:
        # デフォルト: Excelに出力
        default_path = "厚生局_新規指定一覧.xlsx"
        output_to_excel(records, default_path)

    # 抽出サマリー
    prefectures = set(r.get("_prefecture", "") for r in records)
    periods = set(r.get("_period", "") for r in records)
    print(f"\nサマリー:")
    print(f"  都道府県: {', '.join(sorted(prefectures))}")
    print(f"  期間: {', '.join(sorted(periods))}")
    print(f"  合計件数: {len(records)}")


if __name__ == "__main__":
    main()
