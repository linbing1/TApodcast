import json
from unittest.mock import MagicMock

from src.content_quality import finalize_content, review_content
from src.models import (
    AnalyzedArticle,
    ContentReview,
    PodcastScript,
    QualityIssue,
    QualityScores,
    ScrapedArticle,
    SourceFact,
)


OPENING = "欢迎收听英超每日观察，今天是2026年8月18日，"
ENDING = "感谢收听，更多内容请关注英超每日观察。"


def _script(target_length: int = 880) -> PodcastScript:
    body_length = target_length - len(OPENING) - len(ENDING)
    body = ("阿森纳在主场取胜，球队依靠稳定防守和关键进球掌控比赛。" * 40)[
        :body_length
    ]
    return PodcastScript(text=f"{OPENING}{body}{ENDING}")


def _article() -> ScrapedArticle:
    return ScrapedArticle(
        title="Arsenal win",
        link="https://example.com/article",
        full_text="Arsenal won at home with a decisive goal and strong defending.",
    )


def _analyzed() -> AnalyzedArticle:
    return AnalyzedArticle(
        title_cn="阿森纳主场取胜",
        title_original="Arsenal win",
        article_type="赛后分析",
        overview="阿森纳依靠关键进球取胜。",
        detail="阿森纳在主场控制比赛并完成零封。",
        key_people_and_data="一粒关键进球。",
        impact="球队延续良好状态。",
        link="https://example.com/article",
        source_facts=[
            SourceFact(
                fact_id="F001",
                claim="阿森纳在主场取胜。",
                evidence="Arsenal won at home.",
                category="比赛",
                importance="critical",
            )
        ],
    )


def _review_response(*, overall: int = 92, issues: list[dict] | None = None) -> str:
    return json.dumps(
        {
            "passed": True,
            "scores": {
                "factual_accuracy": 95,
                "completeness": 90,
                "structure": 90,
                "spoken_style": 90,
                "title_quality": 90,
                "overall": overall,
            },
            "issues": issues or [],
            "summary": "事实准确，结构完整。",
        },
        ensure_ascii=False,
    )


def _rewrite_response(
    *,
    title: str = "阿森纳主场力克对手",
    script: str | None = None,
) -> str:
    return json.dumps(
        {"title_cn": title, "script": script or _script().text},
        ensure_ascii=False,
    )


def _failed_review() -> ContentReview:
    return ContentReview(
        passed=False,
        scores=QualityScores(
            factual_accuracy=70,
            completeness=70,
            structure=80,
            spoken_style=80,
            title_quality=80,
            overall=72,
        ),
        issues=[
            QualityIssue(
                dimension="completeness",
                severity="error",
                description="遗漏关键事实。",
                fact_ids=["F001"],
            )
        ],
        summary="需要补充关键事实。",
    )


def test_review_passes_when_scores_and_static_rules_pass():
    llm = MagicMock()
    llm.complete.return_value = _review_response()

    result = review_content(_article(), _analyzed(), _script(), llm)

    assert result.passed is True
    assert result.scores.overall == 92
    assert len(result.source_sha256) == 64
    assert len(result.title_sha256) == 64
    assert len(result.script_sha256) == 64
    request = json.loads(llm.complete.call_args.args[1])
    system_prompt = llm.complete.call_args.args[0]
    assert request["analysis"]["source_facts"][0]["fact_id"] == "F001"
    assert request["title_cn"] == "阿森纳主场取胜"
    assert request["source"]["full_text"].startswith("Arsenal won")
    assert "节目制作元数据" in system_prompt


def test_review_rejects_low_scores_even_if_llm_marks_passed():
    llm = MagicMock()
    llm.complete.return_value = _review_response(overall=70)

    result = review_content(_article(), _analyzed(), _script(), llm)

    assert result.passed is False
    assert "overall" in result.summary


def test_review_static_rules_reject_invalid_program_format():
    llm = MagicMock()
    llm.complete.return_value = _review_response()
    invalid_script = PodcastScript(text="这是一篇没有固定开头和结尾的短稿。")

    result = review_content(_article(), _analyzed(), invalid_script, llm)

    assert result.passed is False
    descriptions = {issue.description for issue in result.issues}
    assert "播报稿未使用规定的节目开头。" in descriptions
    assert "播报稿未使用规定的节目结尾。" in descriptions


def test_finalize_rewrites_and_reviews_until_quality_gate_passes():
    llm = MagicMock()
    revised_script = _script().text
    revised_title = "阿森纳主场力克对手"
    llm.complete.side_effect = [
        _rewrite_response(title=revised_title, script=revised_script),
        _review_response(),
    ]

    final_title, final_script, report = finalize_content(
        _article(),
        _analyzed(),
        PodcastScript(text="不合格初稿"),
        _failed_review(),
        llm,
        date_str="2026年8月18日",
    )

    assert final_title == revised_title
    assert final_script.text == revised_script
    assert report.passed is True
    assert len(report.revisions) == 1
    assert report.revisions[0].review.passed is True
    assert llm.complete.call_count == 2


def test_finalize_preserves_review_history_when_gate_never_passes():
    llm = MagicMock()
    revised_script = _script().text
    failing_response = _review_response(
        issues=[
            {
                "dimension": "factual_accuracy",
                "severity": "error",
                "description": "数字与原文不一致。",
                "evidence": "错误数字",
                "suggestion": "按原文修正。",
                "fact_ids": ["F001"],
            }
        ]
    )
    llm.complete.side_effect = [
        _rewrite_response(script=revised_script),
        failing_response,
        _rewrite_response(script=revised_script),
        failing_response,
    ]

    _, _, report = finalize_content(
        _article(),
        _analyzed(),
        PodcastScript(text="不合格初稿"),
        _failed_review(),
        llm,
        date_str="2026年8月18日",
    )

    assert report.passed is False
    assert len(report.revisions) == 2
    assert all(not revision.review.passed for revision in report.revisions)


def test_finalize_rechecks_a_stale_passing_review():
    llm = MagicMock()
    llm.complete.return_value = _review_response()
    stale_review = ContentReview(
        passed=True,
        scores=QualityScores(
            factual_accuracy=95,
            completeness=90,
            structure=90,
            spoken_style=90,
            title_quality=90,
            overall=92,
        ),
        summary="旧审校报告",
        source_sha256="old-source",
        script_sha256="old-script",
    )

    final_title, final_script, report = finalize_content(
        _article(),
        _analyzed(),
        _script(),
        stale_review,
        llm,
        date_str="2026年8月18日",
    )

    assert report.passed is True
    assert final_title == _analyzed().title_cn
    assert final_script.text == _script().text
    assert report.final_review.script_sha256 != "old-script"
    llm.complete.assert_called_once()
