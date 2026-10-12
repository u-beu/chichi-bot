import numpy as np
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_ydl():
    """yt_dlp.YoutubeDL을 패치하고 extract_info 결과를 제어할 수 있는 인스턴스를 제공."""
    with patch("yt_dlp.YoutubeDL") as mock_ydl_class:
        ydl_instance = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = ydl_instance
        yield ydl_instance


@pytest.fixture
def sample_mfcc() -> np.ndarray:
    """(40, 100) 형태의 더미 float32 MFCC 배열."""
    return np.zeros((40, 100), dtype=np.float32)
