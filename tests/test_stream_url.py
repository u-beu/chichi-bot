import pytest
from unittest.mock import patch, MagicMock
from bot.music import get_stream_url_by_query, VideoTooLongError

@patch("yt_dlp.YoutubeDL")
def test_get_stream_url_by_query(mock_ydl_class):
    mock_ydl_instance = MagicMock()
    mock_ydl_instance.extract_info.return_value = {
        'entries': [{
            'url': 'https://example.com/audio',
            'title': 'Test Song',
            'webpage_url': 'https://youtube.com/watch?v=1234',
            'duration': 100
        }]
    }
    mock_ydl_class.return_value.__enter__.return_value = mock_ydl_instance

    result = get_stream_url_by_query("test song")
    assert result['source'] == 'https://example.com/audio'
    assert result['title'] == 'Test Song'
    assert result['webpage_url'] == 'https://youtube.com/watch?v=1234'

@patch("yt_dlp.YoutubeDL")
def test_get_stream_url_too_long(mock_ydl_class):
    mock_ydl_instance = MagicMock()
    mock_ydl_instance.extract_info.return_value = {
        'entries': [{
            'url': 'https://example.com/audio',
            'title': 'Too Long Test Song',
            'webpage_url': 'https://youtube.com/watch?v=5678',
            'duration': 99999
        }]
    }
    mock_ydl_class.return_value.__enter__.return_value = mock_ydl_instance
    with pytest.raises(VideoTooLongError):
        get_stream_url_by_query("too long test song")