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

    def test_wraps_decoding_failure_with_masked_url(self):
        """[목적] librosa.load 실패가 URL이 마스킹된 AudioDecodingError로 래핑되는지 검증

        [검증]
        1. AudioDecodingError가 발생함
        2. 메시지에 원본/소스 URL이 없고 <url>로 대체됨
        3. 원본 예외 체인이 차단됨(__cause__ 없음, __suppress_context__)
        """
        original = Exception("디코딩 실패: https://stream.example.com/audio?sig=secret")
        with patch("worker.preprocessing.audioread.ffdec.FFmpegAudioFile", return_value=object()), \
                patch("worker.preprocessing.librosa.load", side_effect=original):
            with pytest.raises(AudioDecodingError) as exc_info:
                load_audio("https://stream.example.com/audio?sig=secret")

        assert "stream.example.com" not in str(exc_info.value)
        assert "secret" not in str(exc_info.value)
        assert "<url>" in str(exc_info.value)
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__suppress_context__


@pytest.fixture(autouse=True)
def reset_feature_extractor():
    preprocessing_module._feature_extractor = None
    yield
    preprocessing_module._feature_extractor = None


def _fake_extractor():
    """입력 조각 개수만큼 (n, 1024, 128) 배열을 반환하는 feature extractor mock."""
    return MagicMock(side_effect=lambda chunks, **kw: {"input_values": np.zeros((len(chunks), 1024, 128), dtype=np.float64)})


class TestExtractFeatures:
    def test_splits_30s_into_three_chunks_and_returns_float32(self):
        """[목적] 30초 파형이 10초 3조각으로 나뉘어 16kHz로 추출되고 float32 3D 배열로 반환되는지 검증

        [검증]
        1. from_pretrained가 MODEL_ID로 호출됨
        2. extractor가 길이 160000짜리 3개 조각 리스트와 sampling_rate=16000, return_tensors="np"로 호출됨
        3. 반환 배열의 shape이 (3, 1024, 128)이고 dtype이 float32임
        """
        y = np.zeros(30 * 16000, dtype=np.float32)
        extractor = _fake_extractor()
        with patch("worker.preprocessing.ASTFeatureExtractor.from_pretrained", return_value=extractor) as mock_load:
            result = extract_features(y)

        mock_load.assert_called_once_with(preprocessing_module.MODEL_ID)
        chunks = extractor.call_args.args[0]
        assert [len(c) for c in chunks] == [160000, 160000, 160000]
        assert extractor.call_args.kwargs == {"sampling_rate": 16000, "return_tensors": "np"}
        assert result.shape == (3, 1024, 128)
        assert result.dtype == np.float32

    @pytest.mark.parametrize(
        "seconds, expected_chunk_lens",
        [(3, [3 * 16000]), (10, [160000]), (14, [160000]), (15, [160000, 5 * 16000]), (25, [160000, 160000, 5 * 16000])],
        ids=["shorter_than_chunk", "exactly_one_chunk", "drop_short_tail", "keep_tail_at_min", "keep_tail_two_and_half"],
    )
    def test_short_audio_chunking(self, seconds, expected_chunk_lens):
        """[목적] 30초 미만 음원에서 첫 조각은 항상 유지하고 5초 미만 마지막 조각만 버리는지 검증

        [검증]
        1. extractor에 전달된 조각 길이가 기대값과 일치함
        """
        y = np.zeros(seconds * 16000, dtype=np.float32)
        extractor = _fake_extractor()
        with patch("worker.preprocessing.ASTFeatureExtractor.from_pretrained", return_value=extractor):
            extract_features(y)

        assert [len(c) for c in extractor.call_args.args[0]] == expected_chunk_lens

    def test_reuses_feature_extractor(self):
        """[목적] feature extractor가 지연 초기화 후 재사용되는지 검증

        [검증]
        1. 두 번 호출해도 from_pretrained는 한 번만 호출됨
        """
        y = np.zeros(1000, dtype=np.float32)
        with patch("worker.preprocessing.ASTFeatureExtractor.from_pretrained", return_value=_fake_extractor()) as mock_load:
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
        fake_features = np.zeros((3, 1024, 128), dtype=np.float32)
        with patch("worker.preprocessing.load_audio", return_value=fake_y) as mock_load, \
                patch("worker.preprocessing.extract_features", return_value=fake_features) as mock_extract:
            result = preprocess("https://stream.example.com/audio")

        mock_load.assert_called_once_with("https://stream.example.com/audio")
        mock_extract.assert_called_once_with(fake_y)
        assert result is fake_features
