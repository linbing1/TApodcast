from src.subtitle_renderer import parse_vtt, split_subtitle_text, write_ass_from_vtt


def test_parse_vtt_reads_timestamped_entries_and_strips_tags(tmp_path):
    subtitle_path = tmp_path / "audio.vtt"
    subtitle_path.write_text(
        "WEBVTT\n\n"
        "1\n00:00:00.100 --> 00:00:01.200\nhello <b>world</b>\n\n",
        encoding="utf-8",
    )

    assert parse_vtt(str(subtitle_path)) == [(0.1, 1.2, "hello world")]


def test_split_subtitle_text_keeps_dates_and_numbers_together():
    text = "今天是2026年8月11日，转会费1.17亿英镑。"

    result = split_subtitle_text(text, max_width=12)

    assert "2026年8月11日" in result
    assert "1.17亿英镑" in result
    assert "2026年8月11日\\N" not in result
    assert "1.17亿英镑\\N" not in result
    assert result.count("\\N") <= 1


def test_write_ass_uses_vertical_douyin_style(tmp_path):
    subtitle_path = tmp_path / "audio.vtt"
    subtitle_path.write_text(
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.500\n"
        "今天咱们聊聊切尔西的季前巡回赛，以及这次漫长的海外行程。\n\n",
        encoding="utf-8",
    )
    ass_path = tmp_path / "subtitles.ass"

    write_ass_from_vtt(str(subtitle_path), str(ass_path))
    content = ass_path.read_text(encoding="utf-8")

    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert "Style: Chinese,Noto Sans CJK SC,62,&H0000FFFF" in content
    assert ",2,50,50,380,1" in content
    assert "Dialogue: 0,0:00:00.00,0:00:02.50,Chinese" in content
    assert "\\N" in content
