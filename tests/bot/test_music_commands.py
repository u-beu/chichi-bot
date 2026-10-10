import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.music import MusicCog


class TestCogPlay:
    @pytest.mark.asyncio
    async def test_user_not_in_voice(self, mock_ctx):
        """[목적] 호출자가 음성 채널에 없으면 안내 메시지만 전송하는지 검증

        [검증]
        1. "⛔ 음성 채널에서 호출해주세요." 메시지가 전송됨
        """
        cog = MusicCog(MagicMock())
        mock_ctx.author.voice = None

        await cog.play.callback(cog, mock_ctx, arg="song")

        mock_ctx.send.assert_called_once_with("⛔ 음성 채널에서 호출해주세요.")

    @pytest.mark.asyncio
    async def test_song_not_found(self, mock_ctx):
        """[목적] get_info_async가 곡을 찾지 못하면 실패 메시지를 전송하는지 검증

        [검증]
        1. "❌ 노래 탐색에 실패했습니다." 메시지가 전송됨
        """
        cog = MusicCog(MagicMock())

        with patch("bot.music.get_info_async", new_callable=AsyncMock, return_value=None):
            await cog.play.callback(cog, mock_ctx, arg="song")

        mock_ctx.send.assert_called_once_with("❌ 노래 탐색에 실패했습니다.")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arg, expected_query, expected_is_url",
        [
            (None, "최신곡 모음", False),
            ("https://youtu.be/x", "https://youtu.be/x", True),
        ],
        ids=["default_query_when_no_arg", "detects_url_flag"],
    )
    async def test_builds_correct_search_query(self, mock_ctx, arg, expected_query, expected_is_url):
        """[목적] arg 값에 따라 검색어/URL 여부를 올바르게 판단해 조회하는지 검증

        [검증]
        1. arg가 없으면 기본 검색어("최신곡 모음")로 is_url=False 조회됨
        2. arg에 "https://"가 포함되면 원문 그대로 is_url=True 조회됨
        """
        bot = MagicMock()
        cog = MusicCog(bot)
        mock_ctx.guild.id = 1
        mock_ctx.bot = bot

        with patch("bot.music.guild_music_queues", {}), \
                patch("bot.music.get_info_async", new_callable=AsyncMock, return_value={"title": "T"}) as mock_get_info, \
                patch("discord.utils.get", return_value=None), \
                patch("bot.music.play_music", new_callable=AsyncMock):
            await cog.play.callback(cog, mock_ctx, arg=arg)

        mock_get_info.assert_called_once_with(mock_ctx, expected_query, is_url=expected_is_url)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arg, expect_queue_position, expected_message, expect_stop_called",
        [
            ("--add song", -1, "✅ 대기열 추가: **T**", False),
            ("song", 0, "▶️ 현재 곡을 중단하고 즉시 재생합니다.", True),
        ],
        ids=["add_flag_appends_to_queue", "no_add_flag_interrupts_current_song"],
    )
    async def test_play_while_already_playing_branches_on_add_flag(
        self, mock_ctx, arg, expect_queue_position, expected_message, expect_stop_called
    ):
        """[목적] 재생 중일 때 --add 플래그 유무로 대기열 추가/즉시 재생 전환이 분기되는지 검증

        [검증]
        1. --add 플래그가 있으면 조회한 곡이 큐 끝에 추가되고 "대기열 추가" 메시지가 전송되며 stop은 호출되지 않음
        2. --add 플래그가 없으면 조회한 곡이 큐 맨 앞에 추가되고 voice_client.stop이 호출되며 "즉시 재생" 전환 메시지가 전송됨
        3. 두 경우 모두 play_music은 직접 호출되지 않음(after_playing 콜백에 위임)
        """
        bot = MagicMock()
        cog = MusicCog(bot)
        mock_ctx.guild.id = 1

        voice_client = MagicMock()
        voice_client.is_playing.return_value = True

        with patch("bot.music.guild_music_queues", {}) as mock_queues, \
                patch("bot.music.get_info_async", new_callable=AsyncMock, return_value={"title": "T"}), \
                patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
            await cog.play.callback(cog, mock_ctx, arg=arg)

        assert mock_queues[1][expect_queue_position]["title"] == "T"
        mock_ctx.send.assert_called_once_with(expected_message)
        if expect_stop_called:
            voice_client.stop.assert_called_once()
        else:
            voice_client.stop.assert_not_called()
        mock_play_music.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_current_playback_plays_immediately(self, mock_ctx):
        """[목적] 재생 중인 곡이 없을 때 즉시 play_music을 호출해 재생하는지 검증

        [검증]
        1. 조회한 곡이 큐 맨 앞에 추가됨
        2. "▶️ 즉시 재생합니다." 메시지가 전송됨
        3. play_music이 ctx 포함, is_refresh=False로 호출됨
        """
        bot = MagicMock()
        cog = MusicCog(bot)
        mock_ctx.guild.id = 1
        mock_ctx.bot = bot

        with patch("bot.music.guild_music_queues", {}) as mock_queues, \
                patch("bot.music.get_info_async", new_callable=AsyncMock, return_value={"title": "T"}), \
                patch("discord.utils.get", return_value=None), \
                patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
            await cog.play.callback(cog, mock_ctx, arg="song")

        assert mock_queues[1][0]["title"] == "T"
        mock_ctx.send.assert_called_once_with("▶️ 즉시 재생합니다.")
        mock_play_music.assert_called_once_with(bot, mock_ctx.guild, mock_ctx.author, ctx=mock_ctx, is_refresh=False)


class TestCogSkip:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "is_playing",
        [True, False],
        ids=["playing_stops_and_notifies", "not_playing_does_nothing"],
    )
    async def test_skip(self, mock_ctx, is_playing):
        """[목적] 재생 중 여부에 따라 skip 명령의 동작이 달라지는지 검증

        [검증]
        1. 재생 중이면 "⏭️ 다음 곡을 재생합니다." 메시지 전송 및 voice_client.stop 호출
        2. 재생 중이 아니면 아무 메시지도 전송되지 않음
        """
        cog = MusicCog(MagicMock())
        voice_client = MagicMock() if is_playing else None
        if voice_client:
            voice_client.is_playing.return_value = True

        with patch("discord.utils.get", return_value=voice_client):
            await cog.skip.callback(cog, mock_ctx)

        if is_playing:
            mock_ctx.send.assert_called_once_with("⏭️ 다음 곡을 재생합니다.")
            voice_client.stop.assert_called_once()
        else:
            mock_ctx.send.assert_not_called()


class TestCogStop:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "has_voice_client",
        [True, False],
        ids=["disconnects_when_connected", "no_voice_client_does_nothing"],
    )
    async def test_stop(self, mock_ctx, has_voice_client):
        """[목적] voice_client 존재 여부에 따라 stop 명령의 동작이 달라지는지 검증

        [검증]
        1. voice_client가 있으면 disconnect가 호출되고 "🛑 노래 재생을 중지합니다." 메시지가 전송됨
        2. voice_client가 없으면 아무 메시지도 전송되지 않음
        """
        cog = MusicCog(MagicMock())
        voice_client = MagicMock() if has_voice_client else None
        if voice_client:
            voice_client.disconnect = AsyncMock()

        with patch("discord.utils.get", return_value=voice_client):
            await cog.stop.callback(cog, mock_ctx)

        if has_voice_client:
            voice_client.disconnect.assert_called_once()
            mock_ctx.send.assert_called_once_with("🛑 노래 재생을 중지합니다.")
        else:
            mock_ctx.send.assert_not_called()


class TestCogResume:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "is_playing, queue, expected_message, expect_play_called",
        [
            (True, {}, "🎶 이미 노래를 재생 중입니다.", False),
            (False, {}, "❌ 빈 대기열입니다.", False),
            (False, {1: [{"title": "t"}]}, "✅ 다시 재생합니다.", True),
        ],
        ids=["already_playing", "empty_queue", "plays_from_queue"],
    )
    async def test_resume(self, mock_ctx, is_playing, queue, expected_message, expect_play_called):
        """[목적] 현재 재생 상태/대기열 상태에 따라 resume 명령의 분기를 검증

        [검증]
        1. 이미 재생 중이면 중복 재생 안내 메시지만 전송되고 play_music은 호출되지 않음
        2. 대기열이 비어있으면 실패 메시지만 전송되고 play_music은 호출되지 않음
        3. 대기열에 곡이 있으면 재생 안내 메시지 전송과 함께 play_music이 is_refresh=True로 호출됨
        """
        bot = MagicMock()
        cog = MusicCog(bot)
        mock_ctx.guild.id = 1
        mock_ctx.bot = bot

        voice_client = MagicMock()
        voice_client.is_playing.return_value = is_playing

        with patch("discord.utils.get", return_value=voice_client if is_playing else None), \
                patch("bot.music.guild_music_queues", queue), \
                patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
            await cog.resume.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_once_with(expected_message)
        if expect_play_called:
            mock_play_music.assert_called_once_with(bot, mock_ctx.guild, mock_ctx.author, ctx=mock_ctx, is_refresh=True)
        else:
            mock_play_music.assert_not_called()


class TestCogQueue:
    @pytest.mark.asyncio
    async def test_empty(self, mock_ctx):
        """[목적] 대기열이 비어있을 때 queue 명령이 빈 대기열 메시지를 전송하는지 검증

        [검증]
        1. "빈 대기열" 메시지가 전송됨
        """
        cog = MusicCog(MagicMock())

        with patch("bot.music.guild_music_queues", {}):
            await cog.queue.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_once_with("빈 대기열")

    @pytest.mark.asyncio
    async def test_lists_up_to_ten_songs_and_shows_remainder(self, mock_ctx):
        """[목적] 대기열이 10개를 초과할 때 상위 10개만 표시하고 나머지 개수를 안내하는지 검증

        [검증]
        1. 1~10번째 곡(song0~song9)이 메시지에 포함됨
        2. 11번째 곡(song10)은 메시지에 포함되지 않음
        3. "외 2곡 더 있음" 안내 문구가 포함됨
        """
        cog = MusicCog(MagicMock())
        songs = [{"title": f"song{i}"} for i in range(12)]

        with patch("bot.music.guild_music_queues", {1: songs}):
            await cog.queue.callback(cog, mock_ctx)

        sent_message = mock_ctx.send.call_args[0][0]
        assert "song0" in sent_message
        assert "song9" in sent_message
        assert "song10" not in sent_message
        assert "외 2곡 더 있음" in sent_message


class TestCogClear:
    @pytest.mark.asyncio
    async def test_empties_queue(self, mock_ctx):
        """[목적] clear 명령이 길드의 대기열을 완전히 비우는지 검증

        [검증]
        1. guild_music_queues에서 해당 길드 큐가 제거됨
        2. "▶️ 대기열 목록 초기화" 메시지가 전송됨
        """
        cog = MusicCog(MagicMock())

        with patch("bot.music.guild_music_queues", {1: [{"title": "t"}]}) as mock_queues:
            await cog.clear.callback(cog, mock_ctx)

        assert 1 not in mock_queues
        mock_ctx.send.assert_called_once_with("▶️ 대기열 목록 초기화")
