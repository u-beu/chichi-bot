import pytest
from unittest.mock import patch, MagicMock
from bot.music import get_stream_url_by_query, VideoTooLongError

@patch("yt_dlp.YoutubeDL")
def test_get_stream_url_by_query(mock_ydl_class):
    mock_ydl_instance = MagicMock()
    mock_ydl_instance.extract_info.return_value = {
        'entries': [{
            'url': 'https://test/audio',
            'title': 'test-song',
            'uploader': 'test-uploader',
            'thumbnail': 'https://test/thumbnail',
            'display_id': 'A1B2C3D4',
            'duration': 100
        }]
    }
    mock_ydl_class.return_value.__enter__.return_value = mock_ydl_instance

    result = get_stream_url_by_query("song query")
    assert result['source'] == 'https://test/audio'
    assert result['title'] == 'test-song'
    assert result['video_id'] == 'A1B2C3D4'

@patch("yt_dlp.YoutubeDL")
def test_get_stream_url_too_long(mock_ydl_class):
    mock_ydl_instance = MagicMock()
    mock_ydl_instance.extract_info.return_value = {
        'entries': [{
            'url': 'https://test/audio',
            'title': 'test-song',
            'uploader': 'test-uploader',
            'thumbnail': 'https://test/thumbnail',
            'display_id': 'A1B2C3D4',
            'duration': 99999
        }]
    }
    mock_ydl_class.return_value.__enter__.return_value = mock_ydl_instance
    with pytest.raises(VideoTooLongError):
        get_stream_url_by_query("too long test song")