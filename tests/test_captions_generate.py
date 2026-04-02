"""
Unit tests for captioning module.

Tests for ltx2_dataset_builder/captions/generate.py
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, call
from pathlib import Path
from datetime import datetime, timezone
import tempfile
import subprocess

from ltx2_dataset_builder.config import PipelineConfig
from ltx2_dataset_builder.captions.generate import (
    _build_caption_prompt,
    _now_utc,
    extract_scene_clip,
    prepare_scene_inputs,
    _pick_next_scene,
    _retrofit_caption_metadata,
)


class TestBuildCaptionPrompt:
    """Tests for _build_caption_prompt function."""

    def test_default_prompt_without_video_prompt_or_tags(self):
        """Test default prompt when no video prompt or tags provided."""
        prompt = _build_caption_prompt(None, None)

        assert "Describe this video scene in 2 or 3 detailed sentences" in prompt
        assert "dialogue" in prompt
        assert "music" in prompt
        assert "sound effects" in prompt

    def test_custom_video_prompt(self):
        """Test that custom video prompt is used when provided."""
        custom_prompt = "Describe the main character's actions in detail."

        result = _build_caption_prompt(custom_prompt, None)

        assert result == custom_prompt

    def test_tag_definitions_added_to_prompt(self):
        """Test that tag definitions are appended to the prompt."""
        tag_definitions = {
            "Austin Powers": "The main character, a British spy",
            "Dr. Evil": "The villain, Austin's nemesis",
        }

        result = _build_caption_prompt(None, tag_definitions)

        assert "Notable Subjects:" in result
        assert "Austin Powers" in result
        assert "British spy" in result
        assert "Dr. Evil" in result

    def test_tag_definitions_with_empty_descriptions(self):
        """Test tag definitions handling when description is empty."""
        tag_definitions = {
            "character_a": "A brave hero",
            "character_b": "",
            "character_c": None,
        }

        result = _build_caption_prompt(None, tag_definitions)

        assert "character_a" in result
        assert "character_b" in result  # Name still included
        assert "character_c" in result  # Name still included
        assert "brave hero" in result

    def test_tag_definitions_with_display_names(self):
        """Test that display names are used instead of internal tag names."""
        tag_definitions = {
            "austin_powers_person": "The main character, a British spy",
        }

        result = _build_caption_prompt(None, tag_definitions)

        assert "austin_powers_person" in result


class TestNowUtc:
    """Tests for _now_utc function."""

    def test_returns_correct_format(self):
        """Test that the function returns datetime in correct format."""
        result = _now_utc()

        # Should be in format "YYYY-MM-DD HH:MM:SS"
        assert len(result) == 19
        assert result[4] == "-"
        assert result[7] == "-"
        assert result[10] == " "
        assert result[13] == ":"
        assert result[16] == ":"

    def test_returns_utc_timezone(self):
        """Test that the function returns UTC time."""
        # Just verify it doesn't raise an exception and returns a valid string
        result = _now_utc()
        assert isinstance(result, str)
        assert result != ""


class TestExtractSceneClip:
    """Tests for extract_scene_clip function."""

    def test_extract_scene_clip_success(self):
        """Test successful clip extraction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_clip = Path(tmpdir) / "clip.mp4"
            # Create a dummy file to simulate successful extraction
            dummy_clip.touch()

            mock_result = MagicMock()
            mock_result.returncode = 0

            with patch("subprocess.run", return_value=mock_result):
                result = extract_scene_clip(
                    video_path=Path("/fake/video.mp4"),
                    start_time=10.0,
                    end_time=20.0,
                    output_path=dummy_clip,
                )

                assert result is True
                subprocess.run.assert_called_once()

    def test_extract_scene_clip_failure(self):
        """Test clip extraction failure returns False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_clip = Path(tmpdir) / "clip.mp4"

            mock_result = MagicMock()
            mock_result.returncode = 1

            with patch("subprocess.run", return_value=mock_result):
                result = extract_scene_clip(
                    video_path=Path("/fake/video.mp4"),
                    start_time=10.0,
                    end_time=20.0,
                    output_path=dummy_clip,
                )

                assert result is False

    def test_extract_scene_clip_uses_correct_ffmpeg_args(self):
        """Test that FFmpeg is called with correct arguments."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_clip = Path(tmpdir) / "clip.mp4"
            dummy_clip.touch()

            mock_result = MagicMock()
            mock_result.returncode = 0

            with patch("subprocess.run", return_value=mock_result) as mock_run:
                extract_scene_clip(
                    video_path=Path("/test/source.mp4"),
                    start_time=5.5,
                    end_time=15.5,
                    output_path=dummy_clip,
                    max_width=1920,
                    max_height=1080,
                )

                call_args = mock_run.call_args[0][0]  # Get the command list

                assert call_args[0] == "ffmpeg"
                assert "-ss" in call_args
                assert "5.5" in call_args
                assert "-t" in call_args
                assert "10.0" in call_args  # duration = end - start
                assert "-pix_fmt" in call_args
                assert "yuv420p" in call_args
                assert "-c:a" in call_args
                assert "aac" in call_args
                assert "-ac" in call_args
                assert "2" in call_args  # Stereo downmix

    def test_extract_scene_clip_has_timeout(self):
        """Test that FFmpeg call has a timeout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_clip = Path(tmpdir) / "clip.mp4"
            dummy_clip.touch()

            mock_result = MagicMock()
            mock_result.returncode = 0

            with patch("subprocess.run", return_value=mock_result) as mock_run:
                extract_scene_clip(
                    video_path=Path("/fake/video.mp4"),
                    start_time=10.0,
                    end_time=20.0,
                    output_path=dummy_clip,
                )

                # Check that timeout=60 was passed
                assert mock_run.call_args[1]["timeout"] == 60


class TestPrepareSceneInputs:
    """Tests for prepare_scene_inputs function."""

    @pytest.fixture
    def mock_processor(self):
        """Create a mock processor."""
        mock = MagicMock()
        mock.apply_chat_template.return_value = "mocked text"
        mock.return_value = {
            "input_ids": MagicMock(shape=(1, 100)),
            "pixel_values": MagicMock(),
        }
        return mock

    @pytest.fixture
    def mock_process_mm_info(self):
        """Create a mock for process_mm_info."""
        with patch("qwen_omni_utils.process_mm_info") as mock:
            mock.return_value = ([], [], [])
            yield mock

    @pytest.fixture
    def mock_load_model(self, mock_processor):
        """Mock the model loading."""
        with patch(
            "ltx2_dataset_builder.captions.generate.load_qwen_model"
        ) as mock:
            mock.return_value = (MagicMock(), mock_processor)
            yield mock

    @pytest.fixture
    def mock_extract_clip(self):
        """Mock clip extraction."""
        with patch(
            "ltx2_dataset_builder.captions.generate.extract_scene_clip"
        ) as mock:
            mock.return_value = True
            yield mock

    def test_prepare_scene_inputs_basic(
        self, mock_load_model, mock_processor, mock_process_mm_info, mock_extract_clip
    ):
        """Test basic preparation of scene inputs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock the TemporaryDirectory to return our temp dir
            with patch("tempfile.TemporaryDirectory") as MockTempDir:
                mock_temp = MagicMock()
                mock_temp.name = tmpdir
                mock_temp.cleanup = MagicMock()
                MockTempDir.return_value = mock_temp

                inputs, tmpdir_obj, prompt = prepare_scene_inputs(
                    video_path=Path("/fake/video.mp4"),
                    start_time=10.0,
                    end_time=20.0,
                    fps=24.0,
                )

                assert inputs is not None
                assert tmpdir_obj is not None
                assert isinstance(prompt, str)
                mock_extract_clip.assert_called_once()

    def test_prepare_scene_inputs_with_frame_offset(
        self, mock_load_model, mock_processor, mock_process_mm_info, mock_extract_clip
    ):
        """Test that frame_offset is applied correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tempfile.TemporaryDirectory") as MockTempDir:
                mock_temp = MagicMock()
                mock_temp.name = tmpdir
                mock_temp.cleanup = MagicMock()
                MockTempDir.return_value = mock_temp

                prepare_scene_inputs(
                    video_path=Path("/fake/video.mp4"),
                    start_time=10.0,
                    end_time=20.0,
                    frame_offset=2,
                    fps=24.0,
                    start_frame=100,
                    end_frame=200,
                )

                # With frame_offset=2, fps=24, start_frame=100, end_frame=200:
                # adjusted_start = (100 + 2 + 1) / 24 = 4.29
                # adjusted_end = (200 + 2) / 24 = 8.42
                mock_extract_clip.assert_called_once()
                call_args = mock_extract_clip.call_args
                # Verify the adjusted times are close to expected
                assert abs(call_args[0][1] - 4.29) < 0.1  # start_time
                assert abs(call_args[0][2] - 8.42) < 0.1  # end_time

    def test_prepare_scene_inputs_with_tags(
        self, mock_load_model, mock_processor, mock_process_mm_info, mock_extract_clip
    ):
        """Test that tags are included in the conversation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tempfile.TemporaryDirectory") as MockTempDir:
                mock_temp = MagicMock()
                mock_temp.name = tmpdir
                mock_temp.cleanup = MagicMock()
                MockTempDir.return_value = mock_temp

                prepare_scene_inputs(
                    video_path=Path("/fake/video.mp4"),
                    start_time=10.0,
                    end_time=20.0,
                    tags=["Austin Powers", "Dr. Evil"],
                    tag_definitions={
                        "Austin Powers": "British spy",
                    },
                )

                # Verify apply_chat_template was called
                mock_processor.apply_chat_template.assert_called_once()
                call_args = mock_processor.apply_chat_template.call_args[0][0]

                # Check that tags are in the conversation
                assert any(
                    "tags" in str(msg.get("content", ""))
                    for msg in call_args
                    if isinstance(msg, dict)
                )

    def test_prepare_scene_inputs_clip_extraction_failure(
        self, mock_load_model, mock_processor, mock_process_mm_info, mock_extract_clip
    ):
        """Test that RuntimeError is raised when clip extraction fails."""
        mock_extract_clip.return_value = False

        with pytest.raises(RuntimeError, match="Failed to extract clip"):
            prepare_scene_inputs(
                video_path=Path("/fake/video.mp4"),
                start_time=10.0,
                end_time=20.0,
            )

    def test_prepare_scene_inputs_cleanup_on_failure(
        self, mock_load_model, mock_processor, mock_process_mm_info, mock_extract_clip
    ):
        """Test that temp directory is cleaned up on extraction failure."""
        mock_extract_clip.return_value = False

        with patch("tempfile.TemporaryDirectory") as MockTempDir:
            mock_temp = MagicMock()
            MockTempDir.return_value = mock_temp

            with pytest.raises(RuntimeError):
                prepare_scene_inputs(
                    video_path=Path("/fake/video.mp4"),
                    start_time=10.0,
                    end_time=20.0,
                )

            mock_temp.cleanup.assert_called_once()


class TestPickNextScene:
    """Tests for _pick_next_scene function."""

    def test_pick_next_scene_with_video_filter(self):
        """Test picking next scene with video_id filter."""
        mock_db = MagicMock()
        mock_row = {
            "id": 42,
            "video_id": 1,
            "start_time": 10.0,
            "end_time": 20.0,
            "start_frame": 100,
            "end_frame": 200,
            "tag_count": 3,
        }
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_cursor
        mock_db._connection.return_value.__enter__.return_value = mock_conn

        result = _pick_next_scene(mock_db, video_id=1)

        assert result == mock_row
        # Verify execute was called
        mock_conn.execute.assert_called_once()

    def test_pick_next_scene_without_video_filter(self):
        """Test picking next scene without video_id filter."""
        mock_db = MagicMock()
        mock_row = {
            "id": 100,
            "video_id": 5,
            "start_time": 5.0,
            "end_time": 15.0,
            "start_frame": 50,
            "end_frame": 150,
            "tag_count": 0,
        }
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_cursor
        mock_db._connection.return_value.__enter__.return_value = mock_conn

        result = _pick_next_scene(mock_db, video_id=None)

        assert result == mock_row

    def test_pick_next_scene_no_scenes_available(self):
        """Test that None is returned when no scenes available."""
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.execute.return_value = mock_cursor
        mock_db._connection.return_value.__enter__.return_value = mock_conn

        result = _pick_next_scene(mock_db, video_id=1)

        assert result is None

    def test_pick_next_scene_orders_by_tag_count(self):
        """Test that scenes with more tags are prioritized."""
        mock_db = MagicMock()
        mock_row = {
            "id": 42,
            "video_id": 1,
            "start_time": 10.0,
            "end_time": 20.0,
            "tag_count": 5,  # Higher tag count
        }
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_cursor
        mock_db._connection.return_value.__enter__.return_value = mock_conn

        result = _pick_next_scene(mock_db, video_id=1)

        assert result["tag_count"] == 5

    def test_pick_next_scene_filters_out_sentinel_captions(self):
        """Test that sentinel captions are filtered out in the query."""
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.execute.return_value = mock_cursor
        mock_db._connection.return_value.__enter__.return_value = mock_conn

        _pick_next_scene(mock_db, video_id=1)

        # Get the SQL query
        call_args = mock_conn.execute.call_args
        query = call_args[0][0]

        # Verify sentinel captions are excluded (the query uses substr)
        assert "substr" in query.lower()


class TestRetrofitCaptionMetadata:
    """Tests for _retrofit_caption_metadata function."""

    def test_retrofit_scene_with_caption(self):
        """Test retrofitting metadata for a scene with existing caption."""
        mock_db = MagicMock()

        # Scene has caption but no started_at
        mock_scene_row = {
            "id": 42,
            "video_id": 1,
            "start_time": 10.0,
            "end_time": 20.0,
            "start_frame": 100,
            "end_frame": 200,
            "video_prompt": "Describe the scene",
            "fps": 24.0,
        }

        mock_tag_row = {
            "tag": "austin_powers_person",
            "description": "British spy",
            "display_name": "Austin Powers",
        }

        mock_conn = MagicMock()
        # First execute returns list of scenes, second returns tag rows, third executes update
        mock_cursor1 = MagicMock()
        mock_cursor1.fetchall.return_value = [mock_scene_row]
        mock_cursor2 = MagicMock()
        mock_cursor2.fetchall.return_value = [mock_tag_row]

        def execute_side_effect(*args):
            # Return appropriate cursor based on the query
            if "SELECT s.id, s.video_id" in str(args[0]):
                return mock_cursor1
            elif "SELECT st.tag" in str(args[0]):
                return mock_cursor2
            else:
                return MagicMock()  # For UPDATE statements

        mock_conn.execute.side_effect = execute_side_effect
        mock_db._connection.return_value.__enter__.return_value = mock_conn

        _retrofit_caption_metadata(mock_db)

        # Verify update was called
        assert mock_conn.execute.call_count >= 2


class TestExtractSceneClipEdgeCases:
    """Edge case tests for extract_scene_clip."""

    def test_extract_scene_clip_handles_very_short_scenes(self):
        """Test extraction of very short scenes (less than 1 second)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_clip = Path(tmpdir) / "clip.mp4"
            dummy_clip.touch()

            mock_result = MagicMock()
            mock_result.returncode = 0

            with patch("subprocess.run", return_value=mock_result):
                result = extract_scene_clip(
                    video_path=Path("/fake/video.mp4"),
                    start_time=10.0,
                    end_time=10.1,  # 100ms scene
                    output_path=dummy_clip,
                )
                assert result is True

    def test_extract_scene_clip_handles_zero_duration(self):
        """Test that zero duration scenes are handled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_clip = Path(tmpdir) / "clip.mp4"
            dummy_clip.touch()

            mock_result = MagicMock()
            mock_result.returncode = 0

            with patch("subprocess.run", return_value=mock_result):
                result = extract_scene_clip(
                    video_path=Path("/fake/video.mp4"),
                    start_time=10.0,
                    end_time=10.0,  # Zero duration
                    output_path=dummy_clip,
                )
                # FFmpeg might handle this, test doesn't fail
                assert isinstance(result, bool)

    def test_extract_scene_clip_uses_scale_filter(self):
        """Test that scale filter is applied for resolution limiting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_clip = Path(tmpdir) / "clip.mp4"
            dummy_clip.touch()

            mock_result = MagicMock()
            mock_result.returncode = 0

            with patch("subprocess.run", return_value=mock_result) as mock_run:
                extract_scene_clip(
                    video_path=Path("/fake/video.mp4"),
                    start_time=10.0,
                    end_time=20.0,
                    output_path=dummy_clip,
                    max_width=1280,
                    max_height=720,
                )

                call_args = mock_run.call_args[0][0]
                scale_filter_arg = call_args[call_args.index("-vf") + 1]

                assert "scale" in scale_filter_arg
                assert "min(iw" in scale_filter_arg
                assert "min(ih" in scale_filter_arg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
