import os
from unittest.mock import MagicMock, patch

import pytest

from src.models import PodcastScript
from src.tts_generator import generate_tts


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
        mock_submaker.get_srt.return_value = "1\n00:00:00,000 --> 00:00:01,000\n今天\n\n"

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


async def _fake_stream(chunks):
    for chunk in chunks:
        yield chunk
