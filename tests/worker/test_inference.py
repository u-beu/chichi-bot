import torch
from unittest.mock import MagicMock, patch

from worker.inference import _release_memory, run_inference


class TestRunInference:
    def test_returns_label_from_argmax(self, sample_mfcc):
        """[목적] 모델이 반환한 logits의 argmax로 genre/mood 라벨을 매핑하는지 검증

        [검증]
        1. 반환 딕셔너리가 genre/mood 키만 포함함
        2. 각 값이 고정 logits의 argmax에 해당하는 라벨 문자열임
        """
        fake_model = MagicMock(return_value=(
            torch.tensor([0.0, 0.0, 9.0, 0.0, 0.0, 0.0]),
            torch.tensor([0.0, 0.0, 0.0, 9.0, 0.0]),
        ))

        with patch("worker.inference.get_model", return_value=fake_model), \
                patch("worker.inference.get_device", return_value=torch.device("cpu")):
            result = run_inference(sample_mfcc)

        assert set(result.keys()) == {"genre", "mood"}
        assert result["genre"] == "rock"
        assert result["mood"] == "energetic"


class TestReleaseMemory:
    def test_releases_memory_with_mps_guard(self):
        """[목적] mps device일 때만 torch.mps.empty_cache가 호출되는지 검증

        [검증]
        1. gc.collect가 호출됨
        2. device.type == "mps"일 때 torch.mps.empty_cache가 호출됨
        """
        with patch("worker.inference.gc.collect") as mock_gc, \
                patch("worker.inference.torch.mps.empty_cache") as mock_empty_cache:
            _release_memory(torch.device("mps"))

        mock_gc.assert_called_once()
        mock_empty_cache.assert_called_once()

    def test_skips_mps_cache_clear_on_cpu(self):
        """[목적] cpu device일 때는 torch.mps.empty_cache를 호출하지 않는지 검증

        [검증]
        1. gc.collect는 호출됨
        2. torch.mps.empty_cache는 호출되지 않음
        """
        with patch("worker.inference.gc.collect") as mock_gc, \
                patch("worker.inference.torch.mps.empty_cache") as mock_empty_cache:
            _release_memory(torch.device("cpu"))

        mock_gc.assert_called_once()
        mock_empty_cache.assert_not_called()
