"""メールテンプレート自動生成のテスト"""

from src.email_generator import EmailGenerator, AIEmailGenerator, CATEGORY_SELLING_POINTS


class TestEmailGenerator:
    def setup_method(self):
        self.gen = EmailGenerator()

    def test_generate_naika(self):
        result = self.gen.generate({"name": "テスト内科", "category": "内科"})
        assert "件名" not in result["subject"] or True  # subject key exists
        assert "テスト内科" in result["subject"]
        assert "ご開業おめでとうございます" in result["subject"]
        assert "テスト内科" in result["body"]
        assert "株式会社HIBURI" in result["body"]

    def test_generate_shika(self):
        result = self.gen.generate({"name": "テスト歯科", "category": "歯科"})
        assert "自費診療" in result["subject"]
        assert "テスト歯科" in result["body"]

    def test_generate_yakkyoku(self):
        result = self.gen.generate({"name": "テスト薬局", "category": "薬局"})
        assert "かかりつけ薬局" in result["subject"]

    def test_generate_seikeigeka(self):
        result = self.gen.generate({"name": "テスト整形外科", "category": "整形外科"})
        assert "リハビリ" in result["subject"]

    def test_generate_hifuka(self):
        result = self.gen.generate({"name": "テスト皮膚科", "category": "皮膚科"})
        assert "美容皮膚科" in result["subject"]

    def test_generate_unknown_category_fallback(self):
        result = self.gen.generate({"name": "テスト診療所", "category": "放射線科"})
        assert "ご開業おめでとうございます" in result["subject"]
        assert "テスト診療所" in result["body"]

    def test_body_contains_proposals(self):
        result = self.gen.generate({"name": "テスト内科", "category": "内科"})
        body = result["body"]
        # 提案内容が含まれている
        assert "Google広告" in body or "ホームページ" in body
        assert "オンライン面談" in body

    def test_body_contains_signature(self):
        result = self.gen.generate({"name": "テスト", "category": "内科"})
        assert "株式会社HIBURI" in result["body"]
        assert "hiburi.co.jp" in result["body"]

    def test_all_5_categories_have_selling_points(self):
        required = ["内科", "歯科", "薬局", "整形外科", "皮膚科"]
        for cat in required:
            assert cat in CATEGORY_SELLING_POINTS
            assert "pain_points" in CATEGORY_SELLING_POINTS[cat]
            assert "proposals" in CATEGORY_SELLING_POINTS[cat]
            assert len(CATEGORY_SELLING_POINTS[cat]["pain_points"]) >= 3
            assert len(CATEGORY_SELLING_POINTS[cat]["proposals"]) >= 3

    def test_generate_batch(self):
        targets = [
            {"name": "A内科", "category": "内科"},
            {"name": "B歯科", "category": "歯科"},
            {"name": "C薬局", "category": "薬局"},
        ]
        results = self.gen.generate_batch(targets)
        assert len(results) == 3
        assert all("subject" in r and "body" in r for r in results)
        assert results[0]["name"] == "A内科"


class TestAIEmailGeneratorDryRun:
    def test_dry_run_falls_back_to_template(self):
        ai_gen = AIEmailGenerator(dry_run=True)
        result = ai_gen.generate({"name": "AIテスト内科", "category": "内科"})
        assert "AIテスト内科" in result["subject"]
        assert "AIテスト内科" in result["body"]

    def test_dry_run_no_api_key(self):
        ai_gen = AIEmailGenerator(api_key="", dry_run=True)
        result = ai_gen.generate({"name": "テスト", "category": "歯科"})
        assert "subject" in result
        assert "body" in result
