"""厚生局スクレイピングのテスト"""

from datetime import date

from src.medical_scraper import (
    MedicalScraper,
    classify_category,
    REGIONAL_BUREAUS,
)


class TestClassifyCategory:
    def test_naika(self):
        assert classify_category("内科") == "内科"
        assert classify_category("消化器内科") == "内科"
        assert classify_category("循環器内科") == "内科"

    def test_shika(self):
        assert classify_category("歯科") == "歯科"
        assert classify_category("矯正歯科、小児歯科") == "歯科"

    def test_yakkyoku(self):
        assert classify_category("薬局") == "薬局"
        assert classify_category("調剤薬局") == "薬局"

    def test_seikeigeka(self):
        assert classify_category("整形外科") == "整形外科"
        assert classify_category("リハビリテーション科") == "整形外科"

    def test_hifuka(self):
        assert classify_category("皮膚科") == "皮膚科"
        assert classify_category("美容皮膚科") == "皮膚科"

    def test_other(self):
        assert classify_category("放射線科") == "その他"

    def test_empty(self):
        assert classify_category("") == "その他"


class TestMedicalScraperDryRun:
    def setup_method(self):
        self.scraper = MedicalScraper(dry_run=True)

    def test_dry_run_scrape_bureau(self):
        records = self.scraper.scrape_bureau("関東信越")
        assert len(records) == 3
        assert records[0]["category"] == "内科"
        assert records[1]["category"] == "歯科"
        assert records[2]["category"] == "薬局"

    def test_dry_run_scrape_unknown_bureau(self):
        records = self.scraper.scrape_bureau("存在しない局")
        assert records == []

    def test_dry_run_run_single(self):
        result = self.scraper.run(bureaus=["関東信越"])
        assert result["mode"] == "DRY_RUN"
        assert result["total_scraped"] == 3
        assert result["registration"]["registered"] == 3

    def test_dry_run_run_all(self):
        result = self.scraper.run()
        assert result["mode"] == "DRY_RUN"
        assert result["total_scraped"] == 3 * len(REGIONAL_BUREAUS)

    def test_by_category_breakdown(self):
        result = self.scraper.run(bureaus=["関東信越"])
        assert "内科" in result["by_category"]
        assert "歯科" in result["by_category"]
        assert "薬局" in result["by_category"]

    def test_sample_data_has_current_month(self):
        records = self.scraper.scrape_bureau("関東信越")
        today = date.today()
        expected = f"{today.year}年{today.month}月"
        for r in records:
            assert expected in r["open_date"]


class TestFilterCurrentMonth:
    def setup_method(self):
        self.scraper = MedicalScraper(dry_run=True)

    def test_filter_yyyy_mm_format(self):
        records = [
            {"name": "A", "open_date": "2026年3月1日"},
            {"name": "B", "open_date": "2026年2月15日"},
            {"name": "C", "open_date": "2026/03/10"},
        ]
        result = self.scraper.filter_current_month(records, "2026-03")
        names = [r["name"] for r in result]
        assert "A" in names
        assert "C" in names
        assert "B" not in names

    def test_filter_reiwa(self):
        records = [
            {"name": "D", "open_date": "R8年3月1日"},
        ]
        result = self.scraper.filter_current_month(records, "2026-03")
        assert len(result) == 1

    def test_filter_no_match(self):
        records = [
            {"name": "E", "open_date": "2025年12月1日"},
        ]
        result = self.scraper.filter_current_month(records, "2026-03")
        assert len(result) == 0
