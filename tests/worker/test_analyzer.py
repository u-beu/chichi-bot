import subprocess
import sys
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from worker.analyzer import analyze_video
from worker.audio_source import AudioSourceError
from worker.preprocessing import AudioDecodingError

ROOT = Path(__file__).resolve().parents[2]


class TestLazyImport:
    def test_parent_import_does_not_load_heavy_libs(self):
        """[목적] 부모 프로세스가 worker.subscriber를 import해도 torch/transformers/librosa가 로드되지 않는지 검증

        [검증]
        1. 세 라이브러리 모두 sys.modules에 없음 (분석 자식 프로세스에서만 로드)
        """
        code = (
            f"import sys; sys.path.insert(0, {str(ROOT)!r}); "
            "import worker.subscriber; "
            "print(any(m in sys.modules for m in ('torch', 'transformers', 'librosa')))"
        )

        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

        assert result.stdout.strip().splitlines()[-1] == "False"


class TestAnalyzeVideo:
    def test_calls_pipeline_in_order_and_includes_video_id(self):
        """[목적] audio_source -> preprocessing -> inference 순서로 호출되고 결과에 videoId가 포함되는지 검증

        [검증]
        1. get_audio_source_url이 video_id로 호출됨
        2. preprocess가 소스 URL로 호출됨
        3. run_inference가 전처리 결과로 호출됨
        4. 최종 결과에 videoId가 추가됨
        """
        with patch("worker.audio_source.get_audio_source_url", return_value="https://stream.example.com") as mock_source, \
                patch("worker.preprocessing.preprocess", return_value="features-array") as mock_preprocess, \
                patch("worker.inference.run_inference", return_value={"genre": "pop", "mood": "happy"}) as mock_infer:
            result = analyze_video("abc123")

        mock_source.assert_called_once_with("abc123")
        mock_preprocess.assert_called_once_with("https://stream.example.com")
        mock_infer.assert_called_once_with("features-array")
        assert result == {"genre": "pop", "mood": "happy", "videoId": "abc123"}

    def test_propagates_audio_source_error(self):
        """[목적] 오디오 소스 추출 실패 시 예외가 그대로 전파되는지 검증

        [검증]
        1. AudioSourceError가 전파됨
        """
        with patch("worker.audio_source.get_audio_source_url", side_effect=AudioSourceError("boom")):
            with pytest.raises(AudioSourceError):
                analyze_video("abc123")

    def test_propagates_decoding_error(self):
        """[목적] 전처리(디코딩) 실패 시 예외가 그대로 전파되는지 검증

        [검증]
        1. AudioDecodingError가 전파됨
        """
        with patch("worker.audio_source.get_audio_source_url", return_value="https://stream.example.com"), \
                patch("worker.preprocessing.preprocess", side_effect=AudioDecodingError("boom")):
            with pytest.raises(AudioDecodingError):
                analyze_video("abc123")

    def test_decoding_failure_log_does_not_leak_stream_url(self, caplog):
        """[목적] 디코딩 실패 로그(traceback 포함)에 스트리밍 URL이 남지 않는지 검증

        [검증]
        1. 원본 예외 메시지에 URL이 있어도 로그 전체에 URL/서명이 없음
        """
        url = "https://stream.example.com/audio?sig=secret"
        with patch("worker.audio_source.get_audio_source_url", return_value=url), \
                patch("worker.preprocessing.audioread.ffdec.FFmpegAudioFile", side_effect=Exception(f"ffmpeg 실패: {url}")):
            with pytest.raises(AudioDecodingError):
                analyze_video("abc123")

        assert "stream.example.com" not in caplog.text
        assert "secret" not in caplog.text
