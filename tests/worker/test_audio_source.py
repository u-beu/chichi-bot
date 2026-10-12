import pytest

from worker.audio_source import AudioSourceError, get_audio_source_url


class TestGetAudioSourceUrl:
    def test_returns_streaming_url(self, mock_ydl):
        """[목적] 정상적인 videoId를 받으면 yt-dlp가 추출한 스트리밍 URL을 그대로 반환하는지 검증

        [검증]
        1. extract_info가 유튜브 워치 URL로 호출됨
        2. info['url'] 값이 그대로 반환됨
        """
        mock_ydl.extract_info.return_value = {"url": "https://stream.example.com/audio"}

        result = get_audio_source_url("abc123")

        mock_ydl.extract_info.assert_called_once_with(
            "https://www.youtube.com/watch?v=abc123", download=False
        )
        assert result == "https://stream.example.com/audio"

    def test_uses_first_entry_when_entries_present(self, mock_ydl):
        """[목적] 응답에 entries(플레이리스트 형태)가 포함되면 첫 entry를 사용하는지 검증

        [검증]
        1. entries[0]의 url 값이 반환됨
        """
        mock_ydl.extract_info.return_value = {
            "entries": [{"url": "https://stream.example.com/first"}]
        }

        result = get_audio_source_url("abc123")

        assert result == "https://stream.example.com/first"

    def test_wraps_extraction_failure(self, mock_ydl):
        """[목적] yt-dlp 추출 중 예외가 발생하면 AudioSourceError로 래핑되는지 검증

        [검증]
        1. AudioSourceError가 발생함
        2. 원본 예외가 체이닝됨(__cause__)
        """
        original = Exception("yt-dlp 실패")
        mock_ydl.extract_info.side_effect = original

        with pytest.raises(AudioSourceError) as exc_info:
            get_audio_source_url("abc123")

        assert exc_info.value.__cause__ is original
