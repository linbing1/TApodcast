import os
from unittest.mock import MagicMock, patch

import pytest

from src.models import PodcastScript
from src.tts_generator import (
    TtsOutputTruncatedError,
    _last_cue_end_seconds,
    generate_tts,
    validate_tts_output,
)


class TestGenerateTTS:
    @pytest.mark.asyncio
    @patch("src.tts_generator.edge_tts.SubMaker")
    @patch("src.tts_generator.edge_tts.Communicate")
    async def test_writes_mp3_and_srt(self, mock_communicate_cls, mock_submaker_cls, tmp_path):
        mock_communicate = MagicMock()
        mock_communicate_cls.return_value = mock_communicate
        mock_communicate.stream.return_value = _fake_stream([
            {"type": "audio", "data": b"fake-audio-data"},
            {"type": "WordBoundary", "offset": 0, "duration": 1000, "text": "今天"},
        ])

        mock_submaker = MagicMock()
        mock_submaker_cls.return_value = mock_submaker
        mock_submaker.get_srt.return_value = (
            "1\n00:00:00,000 --> 00:00:01,000\n今天。更多内容关注每日英超快报\n\n"
        )

        script = PodcastScript(text="今天的英超快报——内容。更多内容关注每日英超快报")
        mp3_path, srt_path = await generate_tts(script, "zh-CN-XiaoxiaoNeural", str(tmp_path))

        assert os.path.exists(mp3_path)
        assert os.path.exists(srt_path)
        assert open(mp3_path, "rb").read() == b"fake-audio-data"
        assert "今天" in open(srt_path).read()
        mock_submaker.feed.assert_called_once()
        mock_submaker.get_srt.assert_called_once_with()

    @pytest.mark.asyncio
    @patch("src.tts_generator.edge_tts.SubMaker")
    @patch("src.tts_generator.edge_tts.Communicate")
    async def test_uses_specified_voice(self, mock_communicate_cls, mock_submaker_cls, tmp_path):
        mock_communicate = MagicMock()
        mock_communicate_cls.return_value = mock_communicate
        mock_communicate.stream.return_value = _fake_stream([])
        mock_submaker_cls.return_value.get_srt.return_value = ""

        script = PodcastScript(text="内容")
        await generate_tts(script, "zh-CN-YunxiNeural", str(tmp_path), rate="+25%")

        mock_communicate_cls.assert_called_once_with(
            "内容", "zh-CN-YunxiNeural", rate="+25%"
        )

    @pytest.mark.asyncio
    @patch("src.tts_generator.probe_audio_duration", return_value=152.4)
    @patch("src.tts_generator.asyncio.sleep")
    @patch("src.tts_generator.edge_tts.SubMaker")
    @patch("src.tts_generator.edge_tts.Communicate")
    async def test_retries_and_succeeds_after_truncated_stream(
        self, mock_communicate_cls, mock_submaker_cls, mock_sleep, mock_probe, tmp_path
    ):
        mock_communicate = MagicMock()
        mock_communicate_cls.return_value = mock_communicate
        mock_communicate.stream.side_effect = lambda: _fake_stream([
            {"type": "audio", "data": b"fake-audio-data"},
            {"type": "WordBoundary", "offset": 0, "duration": 1000, "text": "今天"},
        ])

        script_text = "今天聊日本门将铃木彩艳。感谢收听，更多内容请关注英超每日观察。"
        truncated = (
            "1\n00:00:00,000 --> 00:00:01,000\n今天聊日本门将铃木彩艳。\n\n"
            "2\n00:00:01,000 --> 00:02:37,988\n感谢收听，更多内容请关注英超每日观察。\n"
        )
        complete = (
            "1\n00:00:00,000 --> 00:00:01,000\n今天聊日本门将铃木彩艳。\n\n"
            "2\n00:00:01,000 --> 00:00:08,000\n感谢收听，更多内容请关注英超每日观察。\n"
        )
        mock_submaker = MagicMock()
        mock_submaker_cls.return_value = mock_submaker
        mock_submaker.get_srt.side_effect = [truncated, truncated, complete]

        script = PodcastScript(text=script_text)
        mp3_path, srt_path = await generate_tts(
            script, "zh-CN-XiaoxiaoNeural", str(tmp_path)
        )

        assert mock_sleep.await_count == 2
        assert open(srt_path).read() == complete
        assert os.path.exists(mp3_path)


class TestValidateTtsOutput:
    def test_truncated_audio_duration_raises(self):
        # 复现真实故障：最后一条字幕的词边界已到达，但音频流在 152.4s 提前结束。
        script = "场外他喜欢打高尔夫，爱听日本说唱歌手AK-69的歌找动力。感谢收听，更多内容请关注英超每日观察。"
        srt = "1\n00:00:00,000 --> 00:02:37,988\n" + script + "\n"
        with pytest.raises(TtsOutputTruncatedError):
            validate_tts_output(script, srt, 152.4)

    def test_missing_script_tail_raises(self):
        # 复现真实故障：字幕停在稿件中段，结尾句子完全没有词边界。
        script = "铃木终于要踏上英超舞台。感谢收听，更多内容请关注英超每日观察。"
        srt = "1\n00:00:00,000 --> 00:00:05,000\n今天聊日本门将铃木彩艳。\n"
        with pytest.raises(TtsOutputTruncatedError):
            validate_tts_output(script, srt, 10.0)

    def test_complete_output_passes(self):
        script = "欢迎收听英超每日观察。感谢收听，更多内容请关注英超每日观察。"
        srt = (
            "1\n00:00:00,000 --> 00:00:04,800\n欢迎收听英超每日观察。\n\n"
            "2\n00:00:04,800 --> 00:00:09,500\n感谢收听，更多内容请关注英超每日观察。\n"
        )
        validate_tts_output(script, srt, 9.2)

    def test_duration_none_skips_duration_check(self):
        script = "内容。"
        srt = "1\n00:00:00,000 --> 00:00:05,000\n内容。\n"
        validate_tts_output(script, srt, None)

    def test_last_cue_end_parses_srt_and_vtt_styles(self):
        assert _last_cue_end_seconds("1\n00:00:01,500 --> 00:00:04,800\n今天\n") == 4.8
        assert _last_cue_end_seconds("00:00:00.100 --> 00:04:37.988\n今天\n") == 277.988
        assert _last_cue_end_seconds("") is None


async def _fake_stream(chunks):
    for chunk in chunks:
        yield chunk
