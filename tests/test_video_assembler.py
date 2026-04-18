import os
import pytest
from unittest.mock import patch, MagicMock

from src.video_assembler import assemble_video, get_audio_duration


class TestGetAudioDuration:
    @patch("src.video_assembler.subprocess.run")
    def test_returns_duration_float(self, mock_run):
        mock_run.return_value = MagicMock(stdout="73.45\n")
        duration = get_audio_duration("/tmp/audio.mp3")
        assert duration == pytest.approx(73.45)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "ffprobe" in cmd
        assert "/tmp/audio.mp3" in cmd


class TestAssembleVideo:
    @patch("src.video_assembler.subprocess.run")
    @patch("src.video_assembler.get_audio_duration")
    def test_calls_ffmpeg_with_correct_args(self, mock_duration, mock_run, tmp_path):
        mock_duration.return_value = 60.0
        # Create fake image files
        images = []
        for i in range(3):
            p = str(tmp_path / f"img{i}.jpg")
            open(p, "wb").write(b"x")
            images.append(p)
        mp3 = str(tmp_path / "audio.mp3")
        srt = str(tmp_path / "audio.srt")
        output = str(tmp_path / "video.mp4")
        open(mp3, "wb").write(b"x")
        open(srt, "w").write("")

        mock_run.return_value = MagicMock(returncode=0)
        result = assemble_video(images, mp3, srt, output)

        assert result == output
        ffmpeg_call = mock_run.call_args_list[-1]
        cmd = ffmpeg_call[0][0]
        assert "ffmpeg" in cmd
        assert output in cmd

    @patch("src.video_assembler.subprocess.run")
    @patch("src.video_assembler.get_audio_duration")
    def test_creates_concat_file(self, mock_duration, mock_run, tmp_path):
        mock_duration.return_value = 30.0
        images = []
        for i in range(2):
            p = str(tmp_path / f"img{i}.jpg")
            open(p, "wb").write(b"x")
            images.append(p)

        mock_run.return_value = MagicMock(returncode=0)
        assemble_video(
            images,
            str(tmp_path / "audio.mp3"),
            str(tmp_path / "audio.srt"),
            str(tmp_path / "video.mp4"),
        )

        concat_path = str(tmp_path / "concat.txt")
        assert os.path.exists(concat_path)
        content = open(concat_path).read()
        assert "duration 15.000" in content  # 30s / 2 images
