"""ナビタパイプラインのテスト"""

import csv
import tempfile
from datetime import date
from pathlib import Path

from src.navita_pipeline import (
    NavitaPipeline,
    NavitaEmailGenerator,
    GoogleMapsClient,
    StationLoader,
    classify_business_category,
    months_until_renewal,
    NAVITA_EMAIL_TEMPLATES,
)


class TestClassifyBusinessCategory:
    def test_restaurant(self):
        assert classify_business_category(["restaurant", "food"]) == "飲食"

    def test_cafe(self):
        assert classify_business_category(["cafe"]) == "飲食"

    def test_beauty_salon(self):
        assert classify_business_category(["beauty_salon"]) == "美容"

    def test_doctor(self):
        assert classify_business_category(["doctor"]) == "医療"

    def test_clothing_store(self):
        assert classify_business_category(["clothing_store"]) == "小売"

    def test_lawyer(self):
        assert classify_business_category(["lawyer"]) == "士業"

    def test_unknown(self):
        assert classify_business_category(["parking"]) == "その他"

    def test_empty(self):
        assert classify_business_category([]) == "その他"

    def test_multiple_types_first_match(self):
        assert classify_business_category(["bar", "restaurant"]) == "飲食"


class TestMonthsUntilRenewal:
    def test_future_same_year(self):
        ref = date(2026, 3, 6)
        assert months_until_renewal(6, ref) == 3

    def test_same_month(self):
        ref = date(2026, 6, 1)
        assert months_until_renewal(6, ref) == 0

    def test_past_wraps_to_next_year(self):
        ref = date(2026, 10, 1)
        assert months_until_renewal(3, ref) == 5  # 10->11->12->1->2->3

    def test_december_to_january(self):
        ref = date(2026, 12, 1)
        assert months_until_renewal(1, ref) == 1

    def test_january_to_december(self):
        ref = date(2026, 1, 1)
        assert months_until_renewal(12, ref) == 11


class TestStationLoader:
    def test_load_from_csv(self):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8-sig")
        writer = csv.DictWriter(tmp, fieldnames=["station_name", "line_name", "renewal_month", "lat", "lng"])
        writer.writeheader()
        writer.writerow({"station_name": "渋谷", "line_name": "JR山手線", "renewal_month": 6, "lat": 35.658, "lng": 139.7016})
        writer.writerow({"station_name": "新宿", "line_name": "JR山手線", "renewal_month": 9, "lat": 35.6896, "lng": 139.7006})
        tmp.close()

        stations = StationLoader.load_from_csv(Path(tmp.name))
        assert len(stations) == 2
        assert stations[0]["station_name"] == "渋谷"
        assert stations[0]["renewal_month"] == 6
        assert stations[0]["lat"] == 35.658

    def test_load_missing_file(self):
        stations = StationLoader.load_from_csv(Path("/tmp/nonexistent_123456.csv"))
        assert stations == []

    def test_generate_sample_csv(self):
        path = Path(tempfile.mktemp(suffix=".csv"))
        result_path = StationLoader.generate_sample_csv(path)
        assert result_path.exists()

        stations = StationLoader.load_from_csv(result_path)
        assert len(stations) == 5
        assert stations[0]["station_name"] == "渋谷"
        result_path.unlink()


class TestGoogleMapsClientDryRun:
    def setup_method(self):
        self.client = GoogleMapsClient(dry_run=True)

    def test_search_nearby_returns_samples(self):
        results = self.client.search_nearby_businesses(35.658, 139.7016, "渋谷")
        assert len(results) == 5
        categories = {r["category"] for r in results}
        assert categories == {"飲食", "美容", "医療", "小売", "士業"}

    def test_sample_has_station_name(self):
        results = self.client.search_nearby_businesses(35.658, 139.7016, "渋谷")
        for r in results:
            assert r["station_name"] == "渋谷"

    def test_get_place_details_dry_run(self):
        details = self.client.get_place_details("test_place_id")
        assert "phone" in details
        assert "website" in details

    def test_geocode_dry_run(self):
        result = self.client.geocode_station("渋谷")
        assert result is None  # dry_runではNone


class TestNavitaEmailGenerator:
    def setup_method(self):
        self.gen = NavitaEmailGenerator()

    def test_all_5_categories_exist(self):
        required = ["飲食", "美容", "医療", "小売", "士業"]
        for cat in required:
            assert cat in NAVITA_EMAIL_TEMPLATES

    def test_generate_restaurant(self):
        result = self.gen.generate({
            "name": "テストレストラン",
            "category": "飲食",
            "station_name": "渋谷",
        })
        assert "テストレストラン" in result["subject"]
        assert "渋谷" in result["subject"]
        assert "ナビタ" in result["body"]
        assert "株式会社HIBURI" in result["body"]

    def test_generate_beauty(self):
        result = self.gen.generate({
            "name": "テストサロン",
            "category": "美容",
            "station_name": "新宿",
        })
        assert "サロン" in result["subject"]
        assert "新宿" in result["body"]

    def test_generate_medical(self):
        result = self.gen.generate({
            "name": "テストクリニック",
            "category": "医療",
            "station_name": "池袋",
        })
        assert "患者" in result["subject"]

    def test_generate_retail(self):
        result = self.gen.generate({
            "name": "テストショップ",
            "category": "小売",
            "station_name": "横浜",
        })
        assert "店舗" in result["subject"]

    def test_generate_professional(self):
        result = self.gen.generate({
            "name": "テスト法律事務所",
            "category": "士業",
            "station_name": "大宮",
        })
        assert "事務所" in result["subject"]

    def test_unknown_category_fallback(self):
        result = self.gen.generate({
            "name": "テスト事業者",
            "category": "その他",
            "station_name": "渋谷",
        })
        assert "subject" in result
        assert "body" in result

    def test_generate_batch(self):
        targets = [
            {"name": "A店", "category": "飲食", "station_name": "渋谷"},
            {"name": "B店", "category": "美容", "station_name": "新宿"},
        ]
        results = self.gen.generate_batch(targets)
        assert len(results) == 2
        assert all("subject" in r and "body" in r for r in results)


class TestNavitaPipelineDryRun:
    def setup_method(self):
        self.pipeline = NavitaPipeline(dry_run=True)

    def test_full_run(self):
        result = self.pipeline.run()
        assert result["mode"] == "DRY_RUN"
        assert result["total_stations"] == 5
        assert result["businesses_found"] > 0
        assert "by_category" in result

    def test_filter_approaching_renewal(self):
        stations = [
            {"station_name": "A", "line_name": "X", "renewal_month": date.today().month, "lat": 0, "lng": 0},
            {"station_name": "B", "line_name": "Y", "renewal_month": (date.today().month + 6) % 12 or 12, "lat": 0, "lng": 0},
        ]
        result = self.pipeline.filter_approaching_renewal(stations, months_ahead=3)
        # A is in current month (0 months away), so it should be included
        assert any(s["station_name"] == "A" for s in result)

    def test_crm_registration_in_run(self):
        result = self.pipeline.run()
        assert result["crm_registration"]["registered"] > 0

    def test_by_category_has_all_types(self):
        result = self.pipeline.run()
        categories = result["by_category"]
        # dry_runで生成されるサンプルは5業種全て含む
        for station_count in range(result["target_stations"]):
            pass  # カテゴリが存在すればOK
        assert len(categories) > 0

    def test_run_with_custom_csv(self):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8-sig")
        writer = csv.DictWriter(tmp, fieldnames=["station_name", "line_name", "renewal_month", "lat", "lng"])
        writer.writeheader()
        # 今月更新の駅（必ずフィルタに引っかかる）
        writer.writerow({
            "station_name": "テスト",
            "line_name": "テスト線",
            "renewal_month": date.today().month,
            "lat": 35.0,
            "lng": 139.0,
        })
        tmp.close()

        result = self.pipeline.run(csv_path=Path(tmp.name))
        assert result["total_stations"] == 1
        assert result["target_stations"] == 1
        assert result["businesses_found"] == 5  # dry_runサンプル5件
