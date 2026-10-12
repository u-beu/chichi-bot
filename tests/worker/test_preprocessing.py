import numpy as np
import pytest
from unittest.mock import patch

from worker.preprocessing import AudioDecodingError, extract_mfcc, load_audio, preprocess


class TestLoadAudio:
    def test_loads_with_expected_params_and_casts_float32(self):
        """[목적] ffmpeg 백엔드로 연 reader가 30초/22050Hz/mono 파라미터로 librosa.load에 전달되고
        float32로 캐스팅되는지 검증

        [검증]
        1. audioread.ffdec.FFmpegAudioFile이 소스 URL로 열림
        2. librosa.load가 그 reader와 duration=30, sr=22050, mono=True로 호출됨
        3. 반환된 배열의 dtype이 float32임
        """
        fake_y = np.zeros(1000, dtype=np.float64)
        fake_reader = object()
        with patch("worker.preprocessing.audioread.ffdec.FFmpegAudioFile", return_value=fake_reader) as mock_ffdec, \
                patch("worker.preprocessing.librosa.load", return_value=(fake_y, 22050)) as mock_load:
            result = load_audio("https://stream.example.com/audio")

        mock_ffdec.assert_called_once_with("https://stream.example.com/audio")
        mock_load.assert_called_once_with(fake_reader, duration=30, sr=22050, mono=True)
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


class TestExtractMfcc:
    def test_passes_expected_params(self):
        """[목적] librosa.feature.mfcc가 기대한 n_mfcc/sr로 호출되는지 검증

        [검증]
        1. librosa.feature.mfcc가 sr=22050, n_mfcc=40으로 호출됨
        2. 반환된 배열의 dtype이 float32임
        """
        y = np.zeros(1000, dtype=np.float32)
        fake_mfcc = np.zeros((40, 10), dtype=np.float64)
        with patch("worker.preprocessing.librosa.feature.mfcc", return_value=fake_mfcc) as mock_mfcc:
            result = extract_mfcc(y)

        mock_mfcc.assert_called_once_with(y=y, sr=22050, n_mfcc=40)
        assert result.dtype == np.float32


class TestPreprocess:
    def test_calls_load_then_extract(self):
        """[목적] preprocess가 load_audio 결과를 extract_mfcc로 전달하는지 검증

        [검증]
        1. load_audio 반환값이 extract_mfcc의 입력으로 사용됨
        2. 최종 결과가 extract_mfcc의 반환값과 동일함
        """
        fake_y = np.zeros(10, dtype=np.float32)
        fake_mfcc = np.zeros((40, 1), dtype=np.float32)
        with patch("worker.preprocessing.load_audio", return_value=fake_y) as mock_load, \
                patch("worker.preprocessing.extract_mfcc", return_value=fake_mfcc) as mock_extract:
            result = preprocess("https://stream.example.com/audio")

        mock_load.assert_called_once_with("https://stream.example.com/audio")
        mock_extract.assert_called_once_with(fake_y)
        assert result is fake_mfcc
