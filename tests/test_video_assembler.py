import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.video_assembler import (
    assemble_video,
    cleanup_frames,
    find_ffmpeg,
    get_audio_duration,
    validate_video,
)


class TestCleanupFrames:
    def test_removes_frames_directory(self, tmp_path):
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        (frames_dir / "00000.jpg").write_bytes(b"jpg")

        assert cleanup_frames(str(tmp_path)) is True
        assert not frames_dir.exists()

    def test_returns_false_when_no_frames_directory(self, tmp_path):
        assert cleanup_frames(str(tmp_path)) is False


class TestFindFfmpeg:
    @patch("src.video_assembler._supports_libass", return_value=True)
    def test_prefers_configured_ffmpeg(self, mock_supports):
        with patch.dict(os.environ, {"FFMPEG_BIN": "/custom/ffmpeg"}):
            assert find_ffmpeg() == "/custom/ffmpeg"

        mock_supports.assert_called_once_with("/custom/ffmpeg")


class TestGetAudioDuration:
    @patch("src.video_assembler.subprocess.run")
    def test_returns_duration_float(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='{"format": {"duration": "73.45"}, "streams": []}'
        )

        duration = get_audio_duration("/tmp/audio.mp3")

        assert duration == pytest.approx(73.45)
        mock_run.assert_called_once()
        command = mock_run.call_args.args[0]
        assert command[0].endswith("ffprobe")
        assert "/tmp/audio.mp3" in command


class TestValidateVideo:
    @patch("src.video_assembler.probe_media")
    def test_accepts_expected_vertical_h264_aac_video(self, mock_probe, tmp_path):
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"mp4")
        mock_probe.return_value = {
            "format": {"duration": "12.5"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1080,
                    "height": 1920,
                    "avg_frame_rate": "30/1",
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        }

        validate_video(str(video_path))

    @patch("src.video_assembler.probe_media")
    def test_rejects_invalid_video_properties(self, mock_probe, tmp_path):
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"mp4")
        mock_probe.return_value = {
            "format": {"duration": "0"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "mpeg4",
                    "width": 720,
                    "height": 1280,
                    "avg_frame_rate": "25/1",
                }
            ],
        }

        with pytest.raises(ValueError, match="视频校验失败"):
            validate_video(str(video_path))


class TestAssembleVideo:
    @patch("src.video_assembler.write_ass_from_vtt")
    @patch("src.video_assembler.find_cjk_font")
    @patch("src.video_assembler.find_ffmpeg")
    @patch("src.video_assembler.render_frames")
    @patch("src.video_assembler.subprocess.run")
    @patch("src.video_assembler.get_audio_duration")
    @patch("src.video_assembler.validate_video")
    def test_calls_ffmpeg_with_fixed_vertical_subtitle_pipeline(
        self,
        mock_validate,
        mock_duration,
        mock_run,
        mock_render_frames,
        mock_find_ffmpeg,
        mock_find_font,
        mock_write_ass,
        tmp_path,
    ):
        mock_duration.return_value = 60.0
        mock_find_ffmpeg.return_value = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
        mock_find_font.return_value = "/fonts/NotoSansCJKsc-Regular.otf"
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        mock_render_frames.return_value = (str(frames_dir), 15)

        images = [str(tmp_path / f"img{i}.jpg") for i in range(3)]
        mp3 = str(tmp_path / "audio.mp3")
        vtt = str(tmp_path / "audio.vtt")
        output = str(tmp_path / "video.mp4")

        result = assemble_video(images, mp3, vtt, output)

        assert result == output
        assert not frames_dir.exists()
        command = mock_run.call_args.args[0]
        assert command[0] == "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
        assert "-framerate" in command
        assert str(frames_dir / "%05d.jpg") in command
        assert "-vf" in command
        subtitle_filter = command[command.index("-vf") + 1]
        assert "ass=filename=" in subtitle_filter
        assert "subtitles.ass" in subtitle_filter
        assert "fontsdir='/fonts'" in subtitle_filter
        assert "adelay" not in command
        assert "60.000" in command
        assert "63.000" not in command
        temporary_output = command[-1]
        assert temporary_output != output
        assert temporary_output.endswith(".tmp.mp4")
        assert not os.path.exists(temporary_output)

        mock_write_ass.assert_called_once_with(vtt, str(tmp_path / "subtitles.ass"))
        mock_render_frames.assert_called_once_with(
            image_paths=images,
            duration=60.0,
            per_image=5.0,
            output_dir=str(tmp_path),
            image_captions=None,
            font_path="/fonts/NotoSansCJKsc-Regular.otf",
        )
        mock_validate.assert_called_once_with(temporary_output)

    @patch("src.video_assembler.write_ass_from_vtt")
    @patch("src.video_assembler.find_cjk_font", return_value="/fonts/font.otf")
    @patch("src.video_assembler.find_ffmpeg", return_value="ffmpeg-full")
    @patch("src.video_assembler.render_frames")
    @patch("src.video_assembler.subprocess.run")
    @patch("src.video_assembler.get_audio_duration", return_value=30.0)
    @patch("src.video_assembler.validate_video")
    def test_uses_rendered_frame_sequence(
        self,
        mock_validate,
        mock_duration,
        mock_run,
        mock_render_frames,
        mock_find_ffmpeg,
        mock_find_font,
        mock_write_ass,
        tmp_path,
    ):
        frames_dir = tmp_path / "rendered-frames"
        frames_dir.mkdir()
        mock_render_frames.return_value = (str(frames_dir), 15)

        assemble_video(
            [str(tmp_path / "img0.jpg"), str(tmp_path / "img1.jpg")],
            str(tmp_path / "audio.mp3"),
            str(tmp_path / "audio.vtt"),
            str(tmp_path / "video.mp4"),
        )

        assert not (tmp_path / "concat.txt").exists()
        assert mock_render_frames.called
        assert mock_duration.called
        assert mock_run.called

    @patch("src.video_assembler.write_ass_from_vtt")
    @patch("src.video_assembler.find_cjk_font", return_value="/fonts/font.otf")
    @patch("src.video_assembler.find_ffmpeg", return_value="ffmpeg-full")
    @patch("src.video_assembler.render_frames")
    @patch("src.video_assembler.subprocess.run")
    @patch("src.video_assembler.get_audio_duration", return_value=30.0)
    @patch("src.video_assembler.validate_video")
    def test_keeps_frames_when_ffmpeg_fails(
        self,
        mock_validate,
        mock_duration,
        mock_run,
        mock_render_frames,
        mock_find_ffmpeg,
        mock_find_font,
        mock_write_ass,
        tmp_path,
    ):
        mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        mock_render_frames.return_value = (str(frames_dir), 15)

        with pytest.raises(subprocess.CalledProcessError):
            assemble_video(
                [str(tmp_path / "img0.jpg"), str(tmp_path / "img1.jpg")],
                str(tmp_path / "audio.mp3"),
                str(tmp_path / "audio.vtt"),
                str(tmp_path / "video.mp4"),
            )

        assert frames_dir.exists()
        assert not list(tmp_path.glob("*.tmp.mp4"))

    @patch("src.video_assembler.write_ass_from_vtt")
    @patch("src.video_assembler.find_cjk_font", return_value="/fonts/font.otf")
    @patch("src.video_assembler.find_ffmpeg", return_value="ffmpeg-full")
    @patch("src.video_assembler.render_frames")
    @patch("src.video_assembler.subprocess.run")
    @patch("src.video_assembler.get_audio_duration", return_value=30.0)
    @patch("src.video_assembler.validate_video")
    def test_preserves_existing_video_when_validation_fails(
        self,
        mock_validate,
        mock_duration,
        mock_run,
        mock_render_frames,
        mock_find_ffmpeg,
        mock_find_font,
        mock_write_ass,
        tmp_path,
    ):
        del mock_duration, mock_find_ffmpeg, mock_find_font, mock_write_ass
        output_path = tmp_path / "video.mp4"
        output_path.write_bytes(b"existing-video")
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        mock_render_frames.return_value = (str(frames_dir), 15)
        mock_validate.side_effect = ValueError("invalid video")

        with pytest.raises(ValueError, match="invalid video"):
            assemble_video(
                [str(tmp_path / "img0.jpg")],
                str(tmp_path / "audio.mp3"),
                str(tmp_path / "audio.vtt"),
                str(output_path),
            )

        assert output_path.read_bytes() == b"existing-video"
        assert frames_dir.exists()
        assert not list(tmp_path.glob("*.tmp.mp4"))
        mock_run.assert_called_once()
