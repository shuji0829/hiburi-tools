"""HIBURI営業自動化システム - 厚生局スクレイピング

各地方厚生局が毎月公開する保険医療機関・保険薬局の新規指定一覧から
診療所名・住所・診療科・開設日を取得する。

対象URL例（関東信越厚生局）:
  https://kouseikyoku.mhlw.go.jp/kantoshinetsu/chousa/shitei.html

各厚生局はExcel/PDF形式でデータを公開しているため、
ページからファイルリンクを取得→ダウンロード→パースする流れ。
"""

import logging
import re
from datetime import datetime, date
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from src.config import PIPELINE_CLINIC
from src.notion_client import NotionClient

JST = ZoneInfo("Asia/Tokyo")
logger = logging.getLogger(__name__)

# 地方厚生局の新規指定一覧ページURL
REGIONAL_BUREAUS = {
    "関東信越": {
        "base_url": "https://kouseikyoku.mhlw.go.jp/kantoshinetsu/",
        "list_url": "https://kouseikyoku.mhlw.go.jp/kantoshinetsu/chousa/shitei.html",
    },
    "近畿": {
        "base_url": "https://kouseikyoku.mhlw.go.jp/kinki/",
        "list_url": "https://kouseikyoku.mhlw.go.jp/kinki/chousa/shitei.html",
    },
    "東海北陸": {
        "base_url": "https://kouseikyoku.mhlw.go.jp/tokaihokuriku/",
        "list_url": "https://kouseikyoku.mhlw.go.jp/tokaihokuriku/chousa/shitei.html",
    },
    "九州": {
        "base_url": "https://kouseikyoku.mhlw.go.jp/kyushu/",
        "list_url": "https://kouseikyoku.mhlw.go.jp/kyushu/chousa/shitei.html",
    },
    "東北": {
        "base_url": "https://kouseikyoku.mhlw.go.jp/tohoku/",
        "list_url": "https://kouseikyoku.mhlw.go.jp/tohoku/chousa/shitei.html",
    },
    "北海道": {
        "base_url": "https://kouseikyoku.mhlw.go.jp/hokkaido/",
        "list_url": "https://kouseikyoku.mhlw.go.jp/hokkaido/chousa/shitei.html",
    },
    "中国四国": {
        "base_url": "https://kouseikyoku.mhlw.go.jp/chugokushikoku/",
        "list_url": "https://kouseikyoku.mhlw.go.jp/chugokushikoku/chousa/shitei.html",
    },
}

# 診療科の分類マッピング
CATEGORY_PATTERNS = {
    "内科": re.compile(r"内科|消化器|循環器|呼吸器|糖尿|内分泌|腎臓|血液|神経内科"),
    "歯科": re.compile(r"歯科|矯正歯科|小児歯科|口腔外科"),
    "薬局": re.compile(r"薬局|調剤"),
    "整形外科": re.compile(r"整形外科|リハビリ|リウマチ"),
    "皮膚科": re.compile(r"皮膚科|美容皮膚"),
    "眼科": re.compile(r"眼科"),
    "耳鼻咽喉科": re.compile(r"耳鼻|咽喉"),
    "小児科": re.compile(r"小児科"),
    "産婦人科": re.compile(r"産婦人科|産科|婦人科"),
    "精神科": re.compile(r"精神|心療内科|メンタル"),
    "その他": re.compile(r".*"),
}


def classify_category(department_text: str) -> str:
    """診療科テキストからカテゴリを分類"""
    for category, pattern in CATEGORY_PATTERNS.items():
        if category == "その他":
            continue
        if pattern.search(department_text):
            return category
    return "その他"


class MedicalScraper:
    """厚生局の新規開業医データスクレイパー"""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        self.notion = NotionClient(dry_run=dry_run)

    def fetch_page(self, url: str) -> BeautifulSoup | None:
        """ページHTMLを取得してパース"""
        if self.dry_run:
            logger.info(f"[DRY_RUN] ページ取得スキップ: {url}")
            return None

        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            logger.error(f"ページ取得エラー: {url} - {e}")
            return None

    def find_excel_links(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """ページ内のExcel/CSVファイルリンクを抽出"""
        links = []
        if soup is None:
            return links

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            text = a_tag.get_text(strip=True)

            if any(ext in href.lower() for ext in [".xlsx", ".xls", ".csv"]):
                full_url = urljoin(base_url, href)
                links.append({
                    "url": full_url,
                    "text": text,
                    "filename": href.split("/")[-1],
                })

        logger.info(f"Excelリンク {len(links)}件 検出: {base_url}")
        return links

    def download_excel(self, url: str) -> BytesIO | None:
        """Excelファイルをダウンロード"""
        if self.dry_run:
            logger.info(f"[DRY_RUN] ダウンロードスキップ: {url}")
            return None

        try:
            resp = self.session.get(url, timeout=60)
            resp.raise_for_status()
            return BytesIO(resp.content)
        except requests.RequestException as e:
            logger.error(f"ダウンロードエラー: {url} - {e}")
            return None

    def parse_excel(self, file_data: BytesIO, filename: str) -> list[dict]:
        """Excelファイルから新規開業医データをパース

        一般的な厚生局のExcelフォーマット:
        | 番号 | 医療機関名 | 所在地 | 診療科 | 指定年月日 | ...
        """
        try:
            import openpyxl
        except ImportError:
            logger.error("openpyxlがインストールされていません: pip install openpyxl")
            return []

        records = []

        try:
            wb = openpyxl.load_workbook(file_data, read_only=True, data_only=True)
            for sheet in wb.worksheets:
                header_row = None
                col_map = {}

                for row_idx, row in enumerate(sheet.iter_rows(values_only=True), 1):
                    if row is None:
                        continue

                    row_text = [str(cell or "") for cell in row]
                    joined = "".join(row_text)

                    # ヘッダー行を検出
                    if header_row is None:
                        if any(kw in joined for kw in ["医療機関", "名称", "薬局名"]):
                            header_row = row_idx
                            for col_idx, cell_val in enumerate(row_text):
                                if any(k in cell_val for k in ["医療機関", "名称", "薬局"]):
                                    col_map["name"] = col_idx
                                elif any(k in cell_val for k in ["所在地", "住所"]):
                                    col_map["address"] = col_idx
                                elif any(k in cell_val for k in ["診療科", "標榜科"]):
                                    col_map["department"] = col_idx
                                elif any(k in cell_val for k in ["指定", "開設", "年月日"]):
                                    col_map["date"] = col_idx
                            continue

                    if header_row is None:
                        continue

                    # データ行をパース
                    name = row_text[col_map["name"]] if "name" in col_map else ""
                    if not name or name.strip() == "":
                        continue

                    address = row_text[col_map["address"]] if "address" in col_map else ""
                    department = row_text[col_map["department"]] if "department" in col_map else ""
                    open_date_str = row_text[col_map["date"]] if "date" in col_map else ""

                    records.append({
                        "name": name.strip(),
                        "address": address.strip(),
                        "department": department.strip(),
                        "category": classify_category(department),
                        "open_date": open_date_str.strip(),
                        "source_file": filename,
                    })

            wb.close()
        except Exception as e:
            logger.error(f"Excelパースエラー: {filename} - {e}")

        logger.info(f"パース完了: {filename} → {len(records)}件")
        return records

    def filter_current_month(self, records: list[dict], target_month: str | None = None) -> list[dict]:
        """当月の新規開業分のみ抽出

        Args:
            records: パース済みレコードリスト
            target_month: "YYYY-MM" 形式。未指定なら当月。
        """
        if target_month is None:
            today = date.today()
            target_month = today.strftime("%Y-%m")

        year, month = target_month.split("-")
        filtered = []

        for r in records:
            open_date = r.get("open_date", "")

            # 日付形式のバリエーションに対応
            if f"{year}年{int(month)}月" in open_date:
                filtered.append(r)
            elif f"{year}/{month}" in open_date or f"{year}-{month}" in open_date:
                filtered.append(r)
            elif f"R{int(year) - 2018}" in open_date and f"{int(month)}月" in open_date:
                # 令和対応 (例: R8年3月)
                filtered.append(r)

        logger.info(f"当月フィルタ ({target_month}): {len(records)}件 → {len(filtered)}件")
        return filtered

    def scrape_bureau(self, bureau_name: str) -> list[dict]:
        """指定した厚生局の新規開業医データを取得"""
        bureau = REGIONAL_BUREAUS.get(bureau_name)
        if not bureau:
            logger.error(f"未登録の厚生局: {bureau_name}")
            return []

        logger.info(f"=== {bureau_name}厚生局 スクレイピング開始 ===")

        soup = self.fetch_page(bureau["list_url"])
        if soup is None and not self.dry_run:
            return []

        if self.dry_run:
            logger.info(f"[DRY_RUN] {bureau_name}厚生局: ページ取得・パースをスキップ")
            return self._generate_sample_data(bureau_name)

        excel_links = self.find_excel_links(soup, bureau["base_url"])
        all_records = []

        for link in excel_links:
            file_data = self.download_excel(link["url"])
            if file_data is None:
                continue

            records = self.parse_excel(file_data, link["filename"])
            current_records = self.filter_current_month(records)
            all_records.extend(current_records)

        logger.info(f"=== {bureau_name}厚生局 完了: {len(all_records)}件 ===")
        return all_records

    def scrape_all_bureaus(self) -> list[dict]:
        """全厚生局をスクレイピング"""
        all_records = []
        for bureau_name in REGIONAL_BUREAUS:
            records = self.scrape_bureau(bureau_name)
            all_records.extend(records)

        logger.info(f"=== 全厚生局合計: {len(all_records)}件 ===")
        return all_records

    def register_to_notion(self, records: list[dict]) -> dict:
        """取得データをNotion CRMに登録

        Returns:
            {"registered": int, "skipped_duplicate": int, "failed": int}
        """
        result = {"registered": 0, "skipped_duplicate": 0, "failed": 0}

        for r in records:
            crm_data = {
                "name": r["name"],
                "email": "",  # スクレイピング時点ではメール未取得
                "pipeline": PIPELINE_CLINIC,
                "category": r.get("category", "その他"),
                "address": r.get("address", ""),
                "status": "new",
                "source": "厚生局",
            }

            try:
                self.notion.add_crm_record(crm_data)
                result["registered"] += 1
            except Exception as e:
                logger.error(f"Notion登録エラー: {r['name']} - {e}")
                result["failed"] += 1

        # 実行ログを記録
        self.notion.log_execution({
            "action": "scrape_medical",
            "pipeline": PIPELINE_CLINIC,
            "target": "厚生局新規開業医",
            "status": "success" if result["failed"] == 0 else "partial",
            "detail": (
                f"登録: {result['registered']}件 / "
                f"重複スキップ: {result['skipped_duplicate']}件 / "
                f"失敗: {result['failed']}件"
            ),
            "mode": "dry_run" if self.dry_run else "live",
        })

        return result

    def run(self, bureaus: list[str] | None = None) -> dict:
        """スクレイピング→Notion登録を一括実行

        Args:
            bureaus: 対象厚生局名リスト。Noneなら全局。
        """
        mode = "DRY_RUN" if self.dry_run else "LIVE"
        logger.info(f"=== 厚生局スクレイピング実行 [{mode}] ===")

        if bureaus:
            records = []
            for name in bureaus:
                records.extend(self.scrape_bureau(name))
        else:
            records = self.scrape_all_bureaus()

        reg_result = self.register_to_notion(records)

        summary = {
            "mode": mode,
            "total_scraped": len(records),
            "registration": reg_result,
            "by_category": {},
        }

        for r in records:
            cat = r.get("category", "その他")
            summary["by_category"][cat] = summary["by_category"].get(cat, 0) + 1

        logger.info(f"=== 実行結果: {summary} ===")
        return summary

    def _generate_sample_data(self, bureau_name: str) -> list[dict]:
        """dry_runモード用のサンプルデータ生成"""
        today = date.today()
        month_str = f"{today.year}年{today.month}月1日"

        samples = [
            {
                "name": f"サンプル内科クリニック（{bureau_name}）",
                "address": f"東京都千代田区サンプル1-2-3",
                "department": "内科、消化器内科",
                "category": "内科",
                "open_date": month_str,
                "source_file": "sample_data.xlsx",
            },
            {
                "name": f"サンプル歯科医院（{bureau_name}）",
                "address": f"東京都新宿区サンプル4-5-6",
                "department": "歯科、矯正歯科",
                "category": "歯科",
                "open_date": month_str,
                "source_file": "sample_data.xlsx",
            },
            {
                "name": f"サンプル調剤薬局（{bureau_name}）",
                "address": f"東京都渋谷区サンプル7-8-9",
                "department": "薬局",
                "category": "薬局",
                "open_date": month_str,
                "source_file": "sample_data.xlsx",
            },
        ]
        logger.info(f"[DRY_RUN] サンプルデータ {len(samples)}件 生成")
        return samples


if __name__ == "__main__":
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    scraper = MedicalScraper(dry_run=True)
    result = scraper.run(bureaus=["関東信越"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
