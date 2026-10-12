import numpy as np
import pytest
from unittest.mock import MagicMock, patch

import worker.preprocessing as preprocessing_module

from worker.preprocessing import AudioDecodingError, extract_features, load_audio, preprocess


class TestLoadAudio:
    def test_loads_with_expected_params_and_casts_float32(self):
        """[목적] ffmpeg 백엔드로 연 reader가 30초/16000Hz/mono 파라미터로 librosa.load에 전달되고
        float32로 캐스팅되는지 검증

        [검증]
        1. audioread.ffdec.FFmpegAudioFile이 소스 URL로 열림
        2. librosa.load가 그 reader와 duration=30, sr=16000, mono=True로 호출됨
        3. 반환된 배열의 dtype이 float32임
        """
        fake_y = np.zeros(1000, dtype=np.float64)
        fake_reader = object()
        with patch("worker.preprocessing.audioread.ffdec.FFmpegAudioFile", return_value=fake_reader) as mock_ffdec, \
                patch("worker.preprocessing.librosa.load", return_value=(fake_y, 16000)) as mock_load:
            result = load_audio("https://stream.example.com/audio")

        mock_ffdec.assert_called_once_with("https://stream.example.com/audio")
        mock_load.assert_called_once_with(fake_reader, duration=30, sr=16000, mono=True)
        assert result.dtype == np.float32

    def test_wraps_decoding_failure(self):
        """[목적] librosa.load 실패(네트워크/디코딩 오류)가 AudioDecodingError로 래핑되는지 검증

        [검증]
        1. AudioDecodingError가 발생함
        2. 원본 예외가 체이닝됨(__cause__)
        """
        original = Exception("디코딩 실패")
        with patch("worker.preprocessing.audioread.ffdec.FFmpegAudioFile", return_value=object()), \
                patch("worker.preprocessing.librosa.load", side_effect=original):
            with pytest.raises(AudioDecodingError) as exc_info:
                load_audio("https://stream.example.com/audio")

        assert exc_info.value.__cause__ is original


@pytest.fixture(autouse=True)
def reset_feature_extractor():
    preprocessing_module._feature_extractor = None
    yield
    preprocessing_module._feature_extractor = None


class TestExtractFeatures:
    def test_passes_expected_params_and_returns_float32(self):
        """[목적] ASTFeatureExtractor가 16kHz로 호출되고 결과가 float32 2D 배열로 반환되는지 검증

        [검증]
        1. from_pretrained가 MODEL_ID로 호출됨
        2. extractor가 sampling_rate=16000, return_tensors="np"로 호출됨
        3. 반환 배열의 shape이 (time, mel)이고 dtype이 float32임
        """
        y = np.zeros(1000, dtype=np.float32)
        fake_extractor = MagicMock(return_value={"input_values": np.zeros((1, 1024, 128), dtype=np.float64)})
        with patch("worker.preprocessing.ASTFeatureExtractor.from_pretrained", return_value=fake_extractor) as mock_load:
            result = extract_features(y)

        mock_load.assert_called_once_with(preprocessing_module.MODEL_ID)
        fake_extractor.assert_called_once_with(y, sampling_rate=16000, return_tensors="np")
        assert result.shape == (1024, 128)
        assert result.dtype == np.float32

    def test_reuses_feature_extractor(self):
        """[목적] feature extractor가 지연 초기화 후 재사용되는지 검증

        [검증]
        1. 두 번 호출해도 from_pretrained는 한 번만 호출됨
        """
        y = np.zeros(1000, dtype=np.float32)
        fake_extractor = MagicMock(return_value={"input_values": np.zeros((1, 1024, 128))})
        with patch("worker.preprocessing.ASTFeatureExtractor.from_pretrained", return_value=fake_extractor) as mock_load:
            extract_features(y)
            extract_features(y)

        mock_load.assert_called_once()


class TestPreprocess:
    def test_calls_load_then_extract(self):
        """[목적] preprocess가 load_audio 결과를 extract_features로 전달하는지 검증

        [검증]
        1. load_audio 반환값이 extract_features의 입력으로 사용됨
        2. 최종 결과가 extract_features의 반환값과 동일함
        """
        fake_y = np.zeros(10, dtype=np.float32)
        fake_features = np.zeros((1024, 128), dtype=np.float32)
        with patch("worker.preprocessing.load_audio", return_value=fake_y) as mock_load, \
                patch("worker.preprocessing.extract_features", return_value=fake_features) as mock_extract:
            result = preprocess("https://stream.example.com/audio")

        mock_load.assert_called_once_with("https://stream.example.com/audio")
        mock_extract.assert_called_once_with(fake_y)
        assert result is fake_features
