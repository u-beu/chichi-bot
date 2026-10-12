import pytest
import torch
from unittest.mock import patch

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

    def test_returns_cpu_when_mps_unavailable(self):
        """[목적] mps 사용 불가능하면 cpu device로 폴백하는지 검증

        [검증]
        1. torch.device("cpu")가 반환됨
        """
        with patch("worker.model.torch.backends.mps.is_available", return_value=False):
            assert get_device().type == "cpu"


class TestGetModel:
    def test_returns_same_instance_on_repeated_calls(self):
        """[목적] get_model이 지연 초기화된 싱글턴을 재사용하는지 검증

        [검증]
        1. 두 번 호출해도 동일한 모델 인스턴스가 반환됨
        """
        with patch("worker.model.get_device", return_value=torch.device("cpu")):
            first = get_model(n_mfcc=40)
            second = get_model(n_mfcc=40)

        assert first is second

    def test_model_is_set_to_eval_mode(self):
        """[목적] 생성된 모델이 eval 모드로 전환되는지 검증

        [검증]
        1. model.training이 False임(eval() 호출 결과)
        """
        with patch("worker.model.get_device", return_value=torch.device("cpu")):
            model = get_model(n_mfcc=40)

        assert model.training is False
