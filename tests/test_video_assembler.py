from unittest.mock import MagicMock, patch

import pytest

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
    @patch("src.video_assembler.render_frames")
    @patch("src.video_assembler._image_top")
    @patch("src.video_assembler.subprocess.run")
    @patch("src.video_assembler.get_audio_duration")
    def test_calls_ffmpeg_with_correct_args(
        self, mock_duration, mock_run, mock_image_top, mock_render_frames, tmp_path
    ):
        mock_duration.return_value = 60.0
        mock_image_top.return_value = 600
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        mock_render_frames.return_value = (str(frames_dir), 5)

        images = [str(tmp_path / f"img{i}.jpg") for i in range(3)]
        mp3 = str(tmp_path / "audio.mp3")
        srt = str(tmp_path / "audio.vtt")
        output = str(tmp_path / "video.mp4")

        mock_run.return_value = MagicMock(returncode=0)
        result = assemble_video(images, mp3, srt, output)

        assert result == output
        cmd = mock_run.call_args[0][0]
        assert "ffmpeg" in cmd
        assert "-framerate" in cmd
        assert str(frames_dir / "%05d.jpg") in cmd
        assert "-r" in cmd
        assert "30" in cmd
        assert "adelay=1000:all=1" in cmd
        assert "63.000" in cmd
        assert output in cmd
        mock_render_frames.assert_called_once_with(
            image_paths=images,
            duration=63.0,
            per_image=5.0,
            srt_path=srt,
            title="",
            article_date="",
            output_dir=str(tmp_path),
            img_top=600,
            lead_in=1.0,
        )

    @patch("src.video_assembler.render_frames")
    @patch("src.video_assembler._image_top")
    @patch("src.video_assembler.subprocess.run")
    @patch("src.video_assembler.get_audio_duration")
    def test_uses_rendered_frame_sequence(
        self, mock_duration, mock_run, mock_image_top, mock_render_frames, tmp_path
    ):
        mock_duration.return_value = 30.0
        mock_image_top.return_value = 600
        frames_dir = tmp_path / "rendered-frames"
        frames_dir.mkdir()
        mock_render_frames.return_value = (str(frames_dir), 5)
        images = [str(tmp_path / "img0.jpg"), str(tmp_path / "img1.jpg")]

        mock_run.return_value = MagicMock(returncode=0)
        assemble_video(
            images,
            str(tmp_path / "audio.mp3"),
            str(tmp_path / "audio.vtt"),
            str(tmp_path / "video.mp4"),
        )

        assert not (tmp_path / "concat.txt").exists()
        assert mock_render_frames.called
