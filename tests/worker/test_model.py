import pytest
import torch
from unittest.mock import MagicMock, patch

import worker.model as model_module
from worker.model import get_device, get_model


@pytest.fixture(autouse=True)
def reset_model_singleton():
    model_module._model = None
    yield
    model_module._model = None


class TestGetDevice:
    def test_returns_mps_when_available(self):
        """[목적] mps 사용 가능하면 mps device를 반환하는지 검증

        [검증]
        1. torch.device("mps")가 반환됨
        """
        with patch("worker.model.torch.backends.mps.is_available", return_value=True):
            assert get_device().type == "mps"

    def test_returns_cuda_when_mps_unavailable_and_cuda_available(self):
        """[목적] mps 불가 + cuda 가능하면 cuda device를 반환하는지 검증

        [검증]
        1. torch.device("cuda")가 반환됨
        """
        with patch("worker.model.torch.backends.mps.is_available", return_value=False), \
                patch("worker.model.torch.cuda.is_available", return_value=True):
            assert get_device().type == "cuda"

    def test_returns_cpu_when_no_accelerator(self):
        """[목적] mps/cuda 모두 불가능하면 cpu device로 폴백하는지 검증

        [검증]
        1. torch.device("cpu")가 반환됨
        """
        with patch("worker.model.torch.backends.mps.is_available", return_value=False), \
                patch("worker.model.torch.cuda.is_available", return_value=False):
            assert get_device().type == "cpu"


class TestGetModel:
    def test_returns_same_instance_on_repeated_calls(self):
        """[목적] get_model이 지연 초기화된 싱글턴을 재사용하는지 검증

        [검증]
        1. from_pretrained가 사전학습 모델 ID로 한 번만 호출됨
        2. 두 번 호출해도 동일한 모델 인스턴스가 반환됨
        """
        fake_model = MagicMock()
        fake_model.to.return_value = fake_model
        with patch("worker.model.get_device", return_value=torch.device("cpu")), \
                patch("worker.model.ASTForAudioClassification.from_pretrained", return_value=fake_model) as mock_load:
            first = get_model()
            second = get_model()

        mock_load.assert_called_once_with(model_module.MODEL_ID)
        assert first is second

    def test_model_is_moved_to_device_and_set_to_eval_mode(self):
        """[목적] 로드된 모델이 device로 이동하고 eval 모드로 전환되는지 검증

        [검증]
        1. model.to가 선택된 device로 호출됨
        2. model.eval()이 호출됨
        """
        fake_model = MagicMock()
        fake_model.to.return_value = fake_model
        device = torch.device("cpu")
        with patch("worker.model.get_device", return_value=device), \
                patch("worker.model.ASTForAudioClassification.from_pretrained", return_value=fake_model):
            get_model()

        fake_model.to.assert_called_once_with(device)
        fake_model.eval.assert_called_once()
