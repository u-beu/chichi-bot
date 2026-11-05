import asyncio

import pytest
from unittest.mock import MagicMock, patch

from bot.music import MAX_DURATION, VideoTooLongError, get_info_async, get_song_info


class TestGetSongInfo:
    def test_success_maps_fields_and_builds_search_query(self, mock_ydl):
        """[목적] 검색어로 정상 조회 시 song dict 변환 결과를 검증

        [검증]
        1. extract_info가 "ytsearch1:{query}"와 download=False로 호출됨
        2. 반환값이 source/title/uploader/image/video_id로 매핑됨
        """
        mock_ydl.extract_info.return_value = {
            "duration": 120,
            "url": "stream-url",
            "title": "title",
            "uploader": "uploader",
            "thumbnail": "thumb",
            "display_id": "vid123",
        }

        result = get_song_info("query", from_url=False)

        mock_ydl.extract_info.assert_called_once_with("ytsearch1:query", download=False)
        assert result == {
            "source": "stream-url",
            "title": "title",
            "uploader": "uploader",
            "image": "thumb",
            "video_id": "vid123",
        }

    def test_from_url_uses_raw_query(self, mock_ydl):
        """[목적] from_url=True일 때 쿼리를 가공하지 않고 그대로 전달하는지 검증

        [검증]
        1. extract_info가 원본 url 문자열과 download=False로 호출됨
        """
        mock_ydl.extract_info.return_value = {
            "duration": 60,
            "url": "u",
            "title": "t",
            "uploader": "up",
            "thumbnail": "th",
            "display_id": "id1",
        }

        get_song_info("https://youtu.be/x", from_url=True)

        mock_ydl.extract_info.assert_called_once_with("https://youtu.be/x", download=False)

    def test_entries_takes_first(self, mock_ydl):
        """[목적] extract_info 결과에 entries 리스트가 있을 때 첫 항목을 사용하는지 검증

        [검증]
        1. 반환된 video_id가 entries[0]의 display_id와 일치함
        """
        entry = {
            "duration": 60,
            "url": "u",
            "title": "t",
            "uploader": "up",
            "thumbnail": "th",
            "display_id": "id1",
        }
        mock_ydl.extract_info.return_value = {"entries": [entry]}

        result = get_song_info("query")

        assert result["video_id"] == "id1"

    def test_too_long_raises(self, mock_ydl):
        """[목적] 영상 길이가 MAX_DURATION을 초과하면 예외가 발생하는지 검증

        [검증]
        1. VideoTooLongError가 발생함
        """
        mock_ydl.extract_info.return_value = {
            "duration": MAX_DURATION + 1,
            "url": "u",
            "title": "t",
            "uploader": "up",
            "thumbnail": "th",
            "display_id": "id1",
        }

        with pytest.raises(VideoTooLongError):
            get_song_info("query")


class TestGetInfoAsync:
    @pytest.mark.asyncio
    async def test_delegates_to_executor(self):
        """[목적] get_info_async가 executor를 통해 get_song_info를 호출하고 결과를 반환하는지 검증

        [검증]
        1. get_song_info가 query와 from_url 인자로 호출됨
        2. 반환값이 get_song_info 결과와 동일함
        """
        ctx = MagicMock()
        ctx.bot.loop = asyncio.get_event_loop()

        with patch("bot.music.get_song_info", return_value={"title": "t"}) as mock_get_song_info:
            result = await get_info_async(ctx, "query", is_url=True)

        mock_get_song_info.assert_called_once_with("query", from_url=True)
        assert result == {"title": "t"}
