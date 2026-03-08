"""
厚生局スクレイパー
関東信越厚生局の保険医療機関・保険薬局の新規指定PDFから
医療機関情報を取得してExcel/Notionに出力する

対象: https://kouseikyoku.mhlw.go.jp/kantoshinetsu/chousa/shitei.html

PDF列構造 (実測):
  [0] 項番
  [1] 医療機関番号
  [2] 医療機関名称          ← 取得対象
  [3] 医療機関所在地        ← 取得対象 (〒付き、改行区切り)
  [4] 電話番号/勤務医数/診療科名 ← 電話番号を抽出 (1行目が電話番号)
  [5] 開設者氏名
  [6] 管理者氏名
  [7] 点数表
  [8] 指定年月日/指定期間終
  [9] 病床数/登録理由
  [10] 備考
"""

import argparse
import os
import re
import sys
import tempfile
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

pdfplumber = None  # 遅延インポート（extract_from_pdf内で読み込み）

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

# 新規指定PDFのURLパターン（-1, -2 等のサフィックス対応）
SHINKI_PDF_PATTERN = re.compile(
    r'(\d{2,3})shinki_([a-z]+)_r(\d{4})(?:-\d+)?\.pdf', re.IGNORECASE
)

# 電話番号パターン
PHONE_PATTERN = re.compile(r'[\d０-９][\d０-９\-－()（）]{8,}')


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
            # 保険医登録PDF(toroku)は除外
            if "toroku" in href.lower():
                continue
            full_url = urljoin(page_url, href)
            match = SHINKI_PDF_PATTERN.search(href)
            if match:
                pref_code = match.group(1)
                # 3桁の場合は先頭2桁が都道府県コード
                if len(pref_code) == 3:
                    pref_code = pref_code[:2]
                pref_label = match.group(2)  # e.g. "tokyo"
                period = match.group(3)  # e.g. "0803" = 令和8年3月
                pref_name = PREFECTURE_CODES.get(pref_code, f"不明({pref_code})")
                pdf_links.append({
                    "url": full_url,
                    "prefecture": pref_name,
                    "pref_code": pref_code,
                    "period": f"令和{period[:2]}年{period[2:]}月",
                    "period_raw": period,
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
    global pdfplumber
    if pdfplumber is None:
        try:
            import pdfplumber as _pdfplumber
            pdfplumber = _pdfplumber
        except Exception:
            print("  警告: pdfplumber がインストールされていません。pip install pdfplumber")
            return []

    records = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
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
    """厚生局PDF固有のテーブル構造からデータ抽出

    列構造:
      [0] 項番  [1] 医療機関番号  [2] 名称  [3] 住所
      [4] 電話/勤務医/診療科  [5] 開設者  [6] 管理者
      [7] 点数表  [8] 指定日  [9] 病床数  [10] 備考
    """
    records = []
    if not table or len(table) < 2:
        return records

    # ヘッダー行を特定
    header_idx = None
    for idx, row in enumerate(table):
        if not row:
            continue
        text = " ".join(str(c) for c in row if c)
        # 「名称」と「所在地」の両方を含む行がヘッダー
        if "名称" in text and ("所在地" in text or "住所" in text):
            header_idx = idx
            break

    # ヘッダーが見つからない場合、最初のページ以降では
    # ヘッダーなしでデータが続くことがある（項番で判定）
    start_idx = header_idx + 1 if header_idx is not None else 0

    for row in table[start_idx:]:
        if not row or len(row) < 5:
            continue

        # 項番列が数字の行のみデータ行とみなす
        item_num = str(row[0]).strip() if row[0] else ""
        if not item_num or not item_num.replace(",", "").replace(".", "").isdigit():
            # 項番なしでも名称があればデータ行の可能性
            name_cell = str(row[2]).strip() if len(row) > 2 and row[2] else ""
            if not name_cell or len(name_cell) < 2:
                continue
            # ヘッダー文字列は除外
            if any(kw in name_cell for kw in ["名称", "合計", "件数", "※", "番号"]):
                continue

        record = _extract_record(row, prefecture)
        if record:
            records.append(record)

    return records


def _extract_record(row, prefecture):
    """1行からレコードを抽出"""
    # 名称 (列2)
    name_raw = str(row[2]).strip() if len(row) > 2 and row[2] else ""
    if not name_raw or len(name_raw) < 2:
        return None
    # PDF内の改行・スペースを除去して結合
    name = name_raw.replace("\n", "").replace(" ", "").replace("　", "").strip()
    # ヘッダー行・フッター行を除外
    if any(kw in name for kw in ["名称", "合計", "件数", "※", "番号", "機関名"]):
        return None

    # 住所 (列3) - 〒と改行を整理
    address_raw = str(row[3]).strip() if len(row) > 3 and row[3] else ""
    address = _clean_address(address_raw, prefecture)

    # 電話番号 (列4) - 最初の行が電話番号、残りは勤務医数・診療科
    phone_raw = str(row[4]).strip() if len(row) > 4 and row[4] else ""
    phone, category = _extract_phone_and_category(phone_raw)

    # 点数表 (列7) - 医/歯/薬 で大分類を判定
    score_type = str(row[7]).strip() if len(row) > 7 and row[7] else ""
    if not category:
        if "歯" in score_type:
            category = "歯科"
        elif "薬" in score_type:
            category = "薬局"
        else:
            category = "医療機関"

    # 開設者 (列5) / 管理者 (列6)
    founder = str(row[5]).strip() if len(row) > 5 and row[5] else ""
    manager = str(row[6]).strip() if len(row) > 6 and row[6] else ""
    # PDF内改行・余計な空白を除去
    founder = founder.replace("\n", "").replace("　", " ").strip()
    manager = manager.replace("\n", "").replace("　", " ").strip()

    record = {
        "事業者名": name,
        "住所": address,
        "電話番号": phone,
        "カテゴリ": category,
        "開設者": founder,
        "管理者": manager,
        "データソース": DEFAULT_DATA_SOURCE,
        "パイプライン": "新規",
    }

    return record


def _clean_address(raw, prefecture):
    """住所文字列をクリーニング"""
    if not raw:
        return ""
    # 改行で分割
    lines = raw.split("\n")
    parts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 〒の全角ハイフンを半角に
        line = line.replace("－", "-")
        parts.append(line)

    address = " ".join(parts)

    # 〒を抽出して先頭に置く
    zip_match = re.search(r'〒\s*(\d{3}-?\d{4})', address)
    zip_code = ""
    if zip_match:
        zip_code = f"〒{zip_match.group(1)} "
        address = address[:zip_match.start()] + address[zip_match.end():]
        address = address.strip()

    # 都道府県が含まれていない場合は追加
    has_pref = any(p in address for p in ["都", "道", "府", "県"])
    if not has_pref and prefecture:
        address = prefecture + address

    return f"{zip_code}{address}".strip()


def _extract_phone_and_category(raw):
    """電話番号/勤務医数/診療科名の複合列から電話番号と診療科を抽出"""
    if not raw:
        return "", ""

    lines = raw.split("\n")
    phone = ""
    category_parts = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 電話番号を抽出（最初にマッチしたもの）
        if not phone:
            # 全角数字を半角に変換してからマッチ
            normalized = line.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
            match = PHONE_PATTERN.search(normalized)
            if match:
                phone = match.group(0)
                phone = phone.replace("－", "-").replace("（", "(").replace("）", ")")
                continue

        # 「常 勤」「非常勤」「医 N」等の勤務医情報はスキップ
        if any(kw in line for kw in ["常 勤", "非常勤", "常勤", "医 ", "歯 ("]):
            continue

        # 残りは診療科名の候補
        # 1-2文字の省略形（内、外、皮、整外 等）が並ぶ
        if len(line) >= 1 and not line[0].isdigit():
            category_parts.append(line)

    # 診療科名を結合
    category = " ".join(category_parts).strip() if category_parts else ""

    return phone, category


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
                r["指定期間"] = info["period"]
                r["都道府県"] = info["prefecture"]
            print(f"  → {len(records)} 件抽出")
            all_records.extend(records)
        except Exception as e:
            print(f"  エラー: {e}")

    print(f"\n合計: {len(all_records)} 件の医療機関を抽出（重複除去前）")
    return all_records


def deduplicate(records):
    """重複レコードを除去（事業者名+住所で判定、最新の期間を保持）"""
    seen = {}  # key: (事業者名, 住所の先頭20文字) → record
    for r in records:
        name = r.get("事業者名", "")
        addr = r.get("住所", "")[:20]  # 住所先頭で照合（PDF改行による微差を吸収）
        key = (name, addr)
        if key not in seen:
            seen[key] = r
        else:
            # 同じ施設が複数月にある場合、最新の期間を保持
            existing_period = seen[key].get("指定期間", "")
            new_period = r.get("指定期間", "")
            if new_period > existing_period:
                seen[key] = r
    unique = list(seen.values())
    removed = len(records) - len(unique)
    if removed > 0:
        print(f"  重複除去: {removed} 件削除 → {len(unique)} 件")
    return unique


def output_to_excel(records, file_path):
    """結果をExcelに出力"""
    headers = ["事業者名", "住所", "電話番号", "ホームページ", "メールアドレス",
               "カテゴリ", "開設者", "管理者", "パイプライン", "データソース", "指定期間", "都道府県"]
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

    # 重複除去
    records = deduplicate(records)

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
    prefectures = set(r.get("都道府県", "") for r in records)
    periods = set(r.get("指定期間", "") for r in records)
    print(f"\nサマリー:")
    print(f"  都道府県: {', '.join(sorted(prefectures))}")
    print(f"  期間: {', '.join(sorted(periods))}")
    print(f"  合計件数: {len(records)}")


if __name__ == "__main__":
    main()
