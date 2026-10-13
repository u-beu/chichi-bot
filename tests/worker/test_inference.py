import torch
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from worker.inference import _release_memory, run_inference
from worker.model import GENRE_LABELS, MOOD_LABELS


LABEL2ID = {label: i for i, label in enumerate(GENRE_LABELS + MOOD_LABELS)}


def _fake_model(genre_label: str, mood_label: str, n_chunks: int = 3) -> MagicMock:
    """모든 조각에서 지정한 장르/무드 라벨의 logit만 가장 크게 설정한 모델 mock."""
    logits = torch.zeros(n_chunks, len(LABEL2ID))
    logits[:, LABEL2ID[genre_label]] = 9.0
    logits[:, LABEL2ID[mood_label]] = 9.0
    model = MagicMock(return_value=SimpleNamespace(logits=logits))
    model.config.label2id = LABEL2ID
    return model


class TestRunInference:
    def test_returns_label_from_subset_argmax(self, sample_features):
        """[목적] 장르/무드 라벨 부분집합 logits의 argmax로 라벨을 매핑하는지 검증

        [검증]
        1. 반환 딕셔너리가 genre/mood 키만 포함함
        2. 각 값이 고정 logits의 argmax에 해당하는 AudioSet 라벨 문자열임
        """
        fake_model = _fake_model("Rock music", "Exciting music")

        with patch("worker.inference.get_model", return_value=fake_model), \
                patch("worker.inference.get_device", return_value=torch.device("cpu")):
            result = run_inference(sample_features)

        assert set(result.keys()) == {"genre", "mood"}
        assert result["genre"] == "Rock music"
        assert result["mood"] == "Exciting music"

    def test_averages_logits_across_chunks(self, sample_features):
        """[목적] 조각별 logits를 평균낸 뒤 argmax로 라벨을 정하는지 검증

        [검증]
        1. 조각 2개에선 Rock이 최대지만 평균은 Pop이 최대일 때 genre가 Pop임
        2. 같은 방식으로 mood도 평균 기준(Sad)으로 결정됨
        """
        logits = torch.zeros(3, len(LABEL2ID))
        logits[0, LABEL2ID["Pop music"]] = 6.0
        logits[1, LABEL2ID["Pop music"]] = 6.0
        logits[2, LABEL2ID["Pop music"]] = 6.0
        logits[0, LABEL2ID["Rock music"]] = 9.0
        logits[1, LABEL2ID["Rock music"]] = 0.0
        logits[2, LABEL2ID["Rock music"]] = 0.0
        logits[0, LABEL2ID["Happy music"]] = 9.0
        logits[1, LABEL2ID["Sad music"]] = 5.0
        logits[2, LABEL2ID["Sad music"]] = 5.0
        fake_model = MagicMock(return_value=SimpleNamespace(logits=logits))
        fake_model.config.label2id = LABEL2ID

        with patch("worker.inference.get_model", return_value=fake_model), \
                patch("worker.inference.get_device", return_value=torch.device("cpu")):
            result = run_inference(sample_features)

        assert result == {"genre": "Pop music", "mood": "Sad music"}

    def test_passes_batched_float32_input_without_grad(self, sample_features):
        """[목적] 특징 배열이 (n_chunks, time, mel) float32 텐서로 모델에 한 번에 전달되고 gradient가 꺼져 있는지 검증

        [검증]
        1. 모델이 input_values 키워드로 한 번 호출됨
        2. input_values의 shape이 (3, 1024, 128), dtype이 float32임
        3. 추론 중 torch.is_grad_enabled()가 False임
        """
        fake_model = _fake_model("Pop music", "Happy music")
        grad_states = []
        fake_model.side_effect = lambda **kw: (grad_states.append(torch.is_grad_enabled()), fake_model.return_value)[1]

        with patch("worker.inference.get_model", return_value=fake_model), \
                patch("worker.inference.get_device", return_value=torch.device("cpu")):
            run_inference(sample_features)

        fake_model.assert_called_once()
        input_values = fake_model.call_args.kwargs["input_values"]
        assert input_values.shape == (3, 1024, 128)
        assert input_values.dtype == torch.float32
        assert grad_states == [False]


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

    def test_releases_cuda_cache_on_cuda(self):
        """[목적] cuda device일 때 torch.cuda.empty_cache가 호출되는지 검증

        [검증]
        1. gc.collect가 호출됨
        2. torch.cuda.empty_cache가 호출됨
        3. torch.mps.empty_cache는 호출되지 않음
        """
        with patch("worker.inference.gc.collect") as mock_gc, \
                patch("worker.inference.torch.cuda.empty_cache") as mock_cuda_cache, \
                patch("worker.inference.torch.mps.empty_cache") as mock_mps_cache:
            _release_memory(torch.device("cuda"))

        mock_gc.assert_called_once()
        mock_cuda_cache.assert_called_once()
        mock_mps_cache.assert_not_called()

    def test_skips_cache_clear_on_cpu(self):
        """[목적] cpu device일 때는 mps/cuda 캐시 해제를 호출하지 않는지 검증

        [검증]
        1. gc.collect는 호출됨
        2. torch.mps.empty_cache, torch.cuda.empty_cache는 호출되지 않음
        """
        with patch("worker.inference.gc.collect") as mock_gc, \
                patch("worker.inference.torch.mps.empty_cache") as mock_mps_cache, \
                patch("worker.inference.torch.cuda.empty_cache") as mock_cuda_cache:
            _release_memory(torch.device("cpu"))

        mock_gc.assert_called_once()
        mock_mps_cache.assert_not_called()
        mock_cuda_cache.assert_not_called()
