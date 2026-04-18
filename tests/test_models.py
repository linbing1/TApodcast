from src.models import ScrapedArticle, AnalyzedArticle, PodcastScript


class TestScrapedArticle:
    def test_defaults(self):
        a = ScrapedArticle(title="Arsenal", link="https://example.com", full_text="text")
        assert a.image_paths == []

    def test_with_images(self):
        a = ScrapedArticle(
            title="Arsenal", link="https://example.com",
            full_text="text", image_paths=["/tmp/img1.jpg", "/tmp/img2.jpg"]
        )
        assert len(a.image_paths) == 2


class TestAnalyzedArticle:
    def test_instantiation(self):
        a = AnalyzedArticle(
            title_cn="标题", title_original="Title", article_type="新闻报道",
            importance=4, overview="概述", detail="详情",
            key_people_and_data="萨卡", impact="影响", link="https://example.com"
        )
        assert a.importance == 4


class TestPodcastScript:
    def test_instantiation(self):
        s = PodcastScript(text="今天的英超快报——阿森纳胜利。更多内容关注每日英超快报")
        assert "英超" in s.text
