from src.models import AnalyzedArticle, PodcastScript, ScrapedArticle


def test_scraped_article_contains_source_text():
    article = ScrapedArticle(
        title="Arsenal",
        link="https://example.com",
        full_text="text",
    )

    assert article.title == "Arsenal"
    assert article.full_text == "text"


class TestAnalyzedArticle:
    def test_instantiation(self):
        a = AnalyzedArticle(
            title_cn="标题", title_original="Title", article_type="新闻报道",
            overview="概述", detail="详情",
            key_people_and_data="萨卡", impact="影响", link="https://example.com"
        )
        assert a.title_cn == "标题"


class TestPodcastScript:
    def test_instantiation(self):
        s = PodcastScript(text="今天的英超快报——阿森纳胜利。更多内容关注每日英超快报")
        assert "英超" in s.text
