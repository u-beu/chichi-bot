import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from bot.music import VideoTooLongError, after_playing, handle_api_playback, play_music


def _make_guild(guild_id, voice_user_ids):
    """voice_states에 voice_user_ids가 접속해 있는 음성 채널 하나를 가진 길드 목."""
    channel = MagicMock()
    channel.voice_states = {uid: MagicMock() for uid in voice_user_ids}
    guild = MagicMock(id=guild_id)
    guild.voice_channels = [channel]
    return guild


class TestHandleApiPlayback:
    @pytest.mark.asyncio
    async def test_user_not_in_any_voice_returns_not_in_voice(self):
        """[목적] 사용자가 어느 길드의 음성 채널에도 없을 때 not_in_voice로 조기 종료되는지 검증

        [검증]
        1. "not_in_voice"를 반환함
        2. play_music이 호출되지 않음
        """
        bot = MagicMock()
        bot.guilds = [_make_guild(1, [3]), _make_guild(2, [])]

        with patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
            result = await handle_api_playback(bot, 2, "query")

        assert result == "not_in_voice"
        mock_play_music.assert_not_called()

    @pytest.mark.asyncio
    async def test_picks_guild_where_user_is_in_voice(self, mock_bot):
        """[목적] 여러 길드 중 사용자가 음성 채널에 접속한 길드로 재생하는지 검증

        [검증]
        1. None(성공)을 반환함
        2. 접속한 길드의 큐에만 song이 추가됨
        3. play_music이 접속한 길드와 discord_id로 호출됨
        """
        other_guild = _make_guild(1, [])
        target_guild = _make_guild(5, [2])
        mock_bot.guilds = [other_guild, target_guild]

        with patch("bot.music.guild_music_queues", {}) as mock_queues, \
                patch("bot.music.get_song_info", return_value={"title": "t", "video_id": "v"}), \
                patch("discord.utils.get", return_value=None), \
                patch("bot.music.play_music", new_callable=AsyncMock, return_value=None) as mock_play_music:
            result = await handle_api_playback(mock_bot, 2, "query")

        assert result is None
        assert list(mock_queues) == [5]
        mock_play_music.assert_called_once_with(mock_bot, target_guild, 2, is_refresh=False)

    @pytest.mark.asyncio
    async def test_member_cache_miss_does_not_fetch_member(self, mock_bot):
        """[목적] 멤버 캐시에 없어도 voice_states의 discord_id만으로 재생이 진행되는지 검증

        [검증]
        1. get_member가 None을 반환해도 guild.fetch_member가 호출되지 않음
        2. play_music이 discord_id로 호출됨
        """
        guild = _make_guild(1, [2])
        guild.get_member.return_value = None
        guild.fetch_member = AsyncMock()
        mock_bot.guilds = [guild]

        with patch("bot.music.guild_music_queues", {}), \
                patch("bot.music.get_song_info", return_value={"title": "t", "video_id": "v"}), \
                patch("discord.utils.get", return_value=None), \
                patch("bot.music.play_music", new_callable=AsyncMock, return_value=None) as mock_play_music:
            await handle_api_playback(mock_bot, 2, "query")

        guild.fetch_member.assert_not_called()
        mock_play_music.assert_called_once_with(mock_bot, guild, 2, is_refresh=False)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "voice_client_state, expect_play_called, expect_stop_called",
        [("none", True, False), ("playing", False, True), ("idle", True, False)],
        ids=["no_voice_client_starts_playback", "playing_interrupts_with_stop", "idle_voice_client_starts_playback"],
    )
    async def test_voice_client_state_controls_playback(
        self, mock_bot, voice_client_state, expect_play_called, expect_stop_called
    ):
        """[목적] 길드 voice_client 상태에 따라 즉시 재생 방식이 달라지는지 검증

        [검증]
        1. 어떤 경우든 조회한 song이 큐 맨 앞에 추가됨
        2. voice_client가 없거나 재생 중이 아니면 play_music이 is_refresh=False로 호출됨
        3. 재생 중이면 voice_client.stop만 호출되고 play_music은 호출되지 않음
        """
        guild = _make_guild(1, [2])
        mock_bot.guilds = [guild]

        voice_client = None
        if voice_client_state != "none":
            voice_client = MagicMock()
            voice_client.is_playing.return_value = voice_client_state == "playing"

        with patch("bot.music.guild_music_queues", {}) as mock_queues, \
                patch("bot.music.get_song_info", return_value={"title": "t", "video_id": "v"}), \
                patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.play_music", new_callable=AsyncMock, return_value=None) as mock_play_music:
            result = await handle_api_playback(mock_bot, 2, "query")

        assert result is None
        assert mock_queues[1][0]["title"] == "t"
        if expect_play_called:
            mock_play_music.assert_called_once_with(mock_bot, guild, 2, is_refresh=False)
        else:
            mock_play_music.assert_not_called()
        if expect_stop_called:
            voice_client.stop.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error, expected_status",
        [
            (VideoTooLongError(7500, 7200), "video_too_long"),
            (Exception("boom"), "search_failed"),
        ],
        ids=["video_too_long", "search_failed"],
    )
    async def test_song_info_failure_returns_status_without_queueing(self, mock_bot, error, expected_status):
        """[목적] 곡 정보 조회 실패 시 원인별 status를 반환하고 큐에 곡을 넣지 않는지 검증

        [검증]
        1. VideoTooLongError는 "video_too_long", 그 외 예외는 "search_failed"를 반환함
        2. 큐에 song이 추가되지 않음
        3. play_music이 호출되지 않음
        """
        mock_bot.guilds = [_make_guild(1, [2])]

        with patch("bot.music.guild_music_queues", {}) as mock_queues, \
                patch("bot.music.get_song_info", side_effect=error), \
                patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
            result = await handle_api_playback(mock_bot, 2, "query")

        assert result == expected_status
        assert mock_queues == {}
        mock_play_music.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_left_during_search_returns_not_in_voice(self, mock_bot):
        """[목적] 검색 중 사용자가 음성 채널을 나가면 not_in_voice를 반환하고 큐에 곡을 넣지 않는지 검증

        [검증]
        1. "not_in_voice"를 반환함
        2. 큐에 song이 추가되지 않음
        3. play_music이 호출되지 않음
        """
        guild = _make_guild(1, [2])
        mock_bot.guilds = [guild]

        def search_then_user_leaves(query, *, from_url):
            guild.voice_channels[0].voice_states = {}
            return {"title": "t", "video_id": "v"}

        with patch("bot.music.guild_music_queues", {}) as mock_queues, \
                patch("bot.music.get_song_info", side_effect=search_then_user_leaves), \
                patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
            result = await handle_api_playback(mock_bot, 2, "query")

        assert result == "not_in_voice"
        assert mock_queues == {}
        mock_play_music.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "play_music_kwargs, expected_status",
        [
            ({"return_value": "no_permission"}, "no_permission"),
            ({"return_value": "connect_failed"}, "connect_failed"),
            ({"side_effect": Exception("boom")}, "playback_failed"),
        ],
        ids=["no_permission", "connect_failed", "play_music_exception"],
    )
    async def test_play_music_failure_status_is_returned(self, mock_bot, play_music_kwargs, expected_status):
        """[목적] play_music의 실패 status와 예외가 호출자에게 status로 전달되는지 검증

        [검증]
        1. play_music이 status를 반환하면 그대로 반환됨
        2. play_music이 예외를 던지면 "playback_failed"를 반환함
        """
        mock_bot.guilds = [_make_guild(1, [2])]

        with patch("bot.music.guild_music_queues", {}), \
                patch("bot.music.get_song_info", return_value={"title": "t", "video_id": "v"}), \
                patch("discord.utils.get", return_value=None), \
                patch("bot.music.play_music", new_callable=AsyncMock, **play_music_kwargs):
            result = await handle_api_playback(mock_bot, 2, "query")

        assert result == expected_status


class TestAfterPlaying:
    @pytest.mark.asyncio
    async def test_no_voice_client_does_nothing(self, mock_bot):
        """[목적] voice_client가 없을 때 아무 동작도 하지 않는지 검증

        [검증]
        1. play_music이 호출되지 않음
        """
        guild = MagicMock(id=1)

        with patch("discord.utils.get", return_value=None), \
                patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
            after_playing(mock_bot, guild, 1)
            await asyncio.sleep(0.01)

        mock_play_music.assert_not_called()

    @pytest.mark.asyncio
    async def test_member_left_voice_clears_queue_and_disconnects(self, mock_bot, voice_client_factory):
        """[목적] 재생 중 요청자가 음성 채널을 나가면 대기열을 비우고 연결을 종료하는지 검증

        [검증]
        1. guild_music_queues에서 해당 길드 큐가 제거됨
        2. voice_client.disconnect가 호출됨
        3. play_music이 호출되지 않음
        """
        guild = _make_guild(1, [])

        voice_client = voice_client_factory(is_connected=True)

        with patch("bot.music.guild_music_queues", {1: [{"title": "t"}]}) as mock_queues, \
                patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
            after_playing(mock_bot, guild, 1)
            await asyncio.sleep(0.01)

        assert 1 not in mock_queues
        voice_client.disconnect.assert_called_once()
        mock_play_music.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_queue_sends_message_and_disconnects(self, mock_bot, member_in_voice_channel, voice_client_factory):
        """[목적] 재생 후 대기열이 비어있으면 안내 메시지 전송 후 연결을 종료하는지 검증

        [검증]
        1. 음성 채널에 빈 대기열 안내 메시지가 전송됨
        2. voice_client.disconnect가 호출됨
        3. guild_music_queues에서 해당 길드 큐가 제거됨
        """
        guild, _member, channel = member_in_voice_channel()

        voice_client = voice_client_factory(is_connected=True)

        with patch("bot.music.guild_music_queues", {1: []}) as mock_queues, \
                patch("discord.utils.get", return_value=voice_client):
            after_playing(mock_bot, guild, 1)
            await asyncio.sleep(0.01)

        channel.send.assert_called_once_with("❌ 빈 대기열입니다. 재생을 종료합니다.")
        voice_client.disconnect.assert_called_once()
        assert 1 not in mock_queues

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [None, Exception("ffmpeg crashed")],
        ids=["no_error", "with_error_still_schedules_next"],
    )
    async def test_queue_has_songs_plays_next_regardless_of_error(
        self, mock_bot, member_in_voice_channel, voice_client_factory, error
    ):
        """[목적] 재생 후 대기열에 곡이 남아있으면 error 발생 여부와 무관하게 다음 곡을 재생하는지 검증

        [검증]
        1. error가 없을 때 play_music이 ctx 유지, is_refresh=True로 호출됨
        2. error가 전달되어도(로깅만 되고) play_music 호출은 동일하게 발생함
        """
        guild, _member, _channel = member_in_voice_channel()
        ctx = MagicMock()

        voice_client = voice_client_factory(is_connected=True)

        with patch("bot.music.guild_music_queues", {1: [{"title": "t"}]}), \
                patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.send_playback_failure", new_callable=AsyncMock), \
                patch("bot.music.play_music", new_callable=AsyncMock, return_value=None) as mock_play_music:
            after_playing(mock_bot, guild, 1, ctx=ctx, error=error)
            await asyncio.sleep(0.01)

        mock_play_music.assert_called_once_with(mock_bot, guild, 1, ctx=ctx, is_refresh=True)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error, expect_failure_sent",
        [(Exception("ffmpeg crashed"), True), (None, False)],
        ids=["with_error_sends_playback_failed", "no_error_sends_nothing"],
    )
    async def test_playback_error_publishes_playback_failed(
        self, mock_bot, member_in_voice_channel, voice_client_factory, error, expect_failure_sent
    ):
        """[목적] 재생 중 error가 전달되면 playback_failed가 발행되는지 검증

        [검증]
        1. error가 있으면 discord_id, bot.redis_client, "playback_failed"로 send_playback_failure가 호출됨
        2. error가 없으면 send_playback_failure가 호출되지 않음
        """
        guild, _member, _channel = member_in_voice_channel()
        voice_client = voice_client_factory(is_connected=True)

        with patch("bot.music.guild_music_queues", {1: [{"title": "t"}]}), \
                patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.send_playback_failure", new_callable=AsyncMock) as mock_failure, \
                patch("bot.music.play_music", new_callable=AsyncMock, return_value=None):
            after_playing(mock_bot, guild, 1, error=error)
            await asyncio.sleep(0.01)

        if expect_failure_sent:
            mock_failure.assert_called_once_with(1, mock_bot.redis_client, "playback_failed")
        else:
            mock_failure.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "play_music_kwargs, expected_status",
        [
            ({"return_value": "no_permission"}, "no_permission"),
            ({"side_effect": Exception("boom")}, "playback_failed"),
        ],
        ids=["status_returned", "exception_raised"],
    )
    async def test_next_song_failure_publishes_status(
        self, mock_bot, member_in_voice_channel, voice_client_factory, play_music_kwargs, expected_status
    ):
        """[목적] 다음 곡 재생이 실패하면 해당 status가 발행되는지 검증

        [검증]
        1. play_music이 status를 반환하면 그 status로 send_playback_failure가 호출됨
        2. play_music이 예외를 던지면 "playback_failed"로 send_playback_failure가 호출됨
        """
        guild, _member, _channel = member_in_voice_channel()
        voice_client = voice_client_factory(is_connected=True)

        with patch("bot.music.guild_music_queues", {1: [{"title": "t"}]}), \
                patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.send_playback_failure", new_callable=AsyncMock) as mock_failure, \
                patch("bot.music.play_music", new_callable=AsyncMock, **play_music_kwargs):
            after_playing(mock_bot, guild, 1)
            await asyncio.sleep(0.01)

        mock_failure.assert_called_once_with(1, mock_bot.redis_client, expected_status)


class TestPlayMusic:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "connect, speak, use_ctx",
        [
            (False, True, False),
            (True, False, True),
        ],
        ids=["no_connect_permission_sends_to_member_channel", "no_speak_permission_sends_to_ctx_channel"],
    )
    async def test_no_permission_sends_guidance_and_returns_early(
        self, member_in_voice_channel, connect, speak, use_ctx
    ):
        """[목적] 음성 채널 연결/발언 권한이 없으면 안내 메시지 전송 후 no_permission을 반환하며 조기 종료되는지 검증

        [검증]
        0. "no_permission"을 반환함
        1. connect 권한이 없고 ctx 미제공 시 멤버의 음성 채널로 권한 안내 메시지가 전송됨
        2. speak 권한이 없고 ctx 제공 시 ctx로 권한 안내 메시지가 전송됨
        3. 두 경우 모두 voice_client 조회(discord.utils.get)가 호출되지 않음(조기 return)
        """
        bot = MagicMock()
        guild, member, channel = member_in_voice_channel(connect=connect, speak=speak)
        ctx = MagicMock()
        ctx.send = AsyncMock()

        with patch("discord.utils.get") as mock_get:
            result = await play_music(bot, guild, member.id, ctx=ctx if use_ctx else None, is_refresh=False)

        assert result == "no_permission"
        target = ctx if use_ctx else channel
        target.send.assert_called_once_with("⛔ 해당 음성 채널에 연결 권한이 없습니다.")
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_queue_connects_but_returns_early(self, member_in_voice_channel):
        """[목적] 음성 채널 연결은 하되 대기열이 비어있으면 재생 없이 종료되는지 검증

        [검증]
        1. member_voice_channel.connect가 호출됨
        2. send_play_history가 호출되지 않음
        """
        bot = MagicMock()
        guild, member, channel = member_in_voice_channel()
        channel.connect = AsyncMock(return_value=MagicMock())

        with patch("bot.music.guild_music_queues", {}), \
                patch("discord.utils.get", return_value=None), \
                patch("bot.music.send_play_history", new_callable=AsyncMock) as mock_send_history:
            await play_music(bot, guild, member.id, is_refresh=False)

        channel.connect.assert_called_once()
        mock_send_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_connects_plays_and_sends_history(self, mock_bot, member_in_voice_channel):
        """[목적] 신규 연결 후 곡을 재생하고 재생 기록을 전송하는지 검증

        [검증]
        1. voice_channel.connect가 호출됨
        2. voice_client.play가 호출됨
        3. 재생중 안내 메시지가 전송됨
        4. send_play_history가 song/member.id/bot.redis_client로 호출됨
        """
        guild, member, channel = member_in_voice_channel(member_id=42)
        new_voice_client = MagicMock()
        channel.connect = AsyncMock(return_value=new_voice_client)

        song = {"title": "Song A", "source": "src", "video_id": "vid"}

        with patch("bot.music.guild_music_queues", {1: [song]}), \
                patch("discord.utils.get", return_value=None), \
                patch("discord.FFmpegPCMAudio", return_value=MagicMock()), \
                patch("discord.PCMVolumeTransformer", return_value=MagicMock()), \
                patch("bot.music.send_play_history", new_callable=AsyncMock) as mock_send_history:
            await play_music(mock_bot, guild, member.id, is_refresh=False)
            await asyncio.sleep(0)

        channel.connect.assert_called_once()
        new_voice_client.play.assert_called_once()
        channel.send.assert_called_once_with("🎶 재생중: **Song A**")
        mock_send_history.assert_called_once_with(song, 42, mock_bot.redis_client)

    @pytest.mark.asyncio
    async def test_moves_to_member_channel_when_different(self, mock_bot, member_in_voice_channel, voice_client_factory):
        """[목적] 기존 voice_client가 다른 채널에 있으면 멤버의 채널로 이동하는지 검증

        [검증]
        1. voice_client.move_to가 멤버의 음성 채널로 호출됨
        """
        guild, member, channel = member_in_voice_channel()
        other_channel = MagicMock()
        voice_client = voice_client_factory(is_connected=True, channel=other_channel)

        song = {"title": "t", "source": "s", "video_id": "v"}

        with patch("bot.music.guild_music_queues", {1: [song]}), \
                patch("discord.utils.get", return_value=voice_client), \
                patch("discord.FFmpegPCMAudio", return_value=MagicMock()), \
                patch("discord.PCMVolumeTransformer", return_value=MagicMock()), \
                patch("bot.music.send_play_history", new_callable=AsyncMock):
            await play_music(mock_bot, guild, member.id, is_refresh=False)
            await asyncio.sleep(0)

        voice_client.move_to.assert_called_once_with(channel)

    @pytest.mark.asyncio
    async def test_is_refresh_requeries_song_info(self, mock_bot, member_in_voice_channel, voice_client_factory):
        """[목적] is_refresh=True일 때 video_id 기반 URL로 song 정보를 재조회하는지 검증

        [검증]
        1. get_song_info가 watch URL과 from_url=True로 호출됨
        2. 재생중 메시지가 갱신된 title로 전송됨
        3. send_play_history가 갱신된 song으로 호출됨
        """
        guild, member, channel = member_in_voice_channel()
        voice_client = voice_client_factory(is_connected=True, channel=channel)

        old_song = {"title": "old", "source": "old-src", "video_id": "vid123"}
        refreshed_song = {"title": "fresh", "source": "fresh-src", "video_id": "vid123"}

        with patch("bot.music.guild_music_queues", {1: [old_song]}), \
                patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.get_song_info", return_value=refreshed_song) as mock_get_song_info, \
                patch("discord.FFmpegPCMAudio", return_value=MagicMock()), \
                patch("discord.PCMVolumeTransformer", return_value=MagicMock()), \
                patch("bot.music.send_play_history", new_callable=AsyncMock) as mock_send_history:
            await play_music(mock_bot, guild, member.id, is_refresh=True)
            await asyncio.sleep(0)

        mock_get_song_info.assert_called_once_with(
            "https://www.youtube.com/watch?v=vid123", from_url=True
        )
        channel.send.assert_called_once_with("🎶 재생중: **fresh**")
        mock_send_history.assert_called_once_with(refreshed_song, 1, mock_bot.redis_client)

    @pytest.mark.asyncio
    async def test_is_refresh_failure_keeps_old_song(self, mock_bot, member_in_voice_channel, voice_client_factory):
        """[목적] is_refresh 재조회가 실패하면 기존 song 정보를 그대로 사용하는지 검증

        [검증]
        1. 재생중 메시지가 기존 title로 전송됨
        2. send_play_history가 기존 song으로 호출됨
        """
        guild, member, channel = member_in_voice_channel()
        voice_client = voice_client_factory(is_connected=True, channel=channel)

        old_song = {"title": "old", "source": "old-src", "video_id": "vid123"}

        with patch("bot.music.guild_music_queues", {1: [old_song]}), \
                patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.get_song_info", side_effect=Exception("boom")), \
                patch("discord.FFmpegPCMAudio", return_value=MagicMock()), \
                patch("discord.PCMVolumeTransformer", return_value=MagicMock()), \
                patch("bot.music.send_play_history", new_callable=AsyncMock) as mock_send_history:
            await play_music(mock_bot, guild, member.id, is_refresh=True)
            await asyncio.sleep(0)

        channel.send.assert_called_once_with("🎶 재생중: **old**")
        mock_send_history.assert_called_once_with(old_song, 1, mock_bot.redis_client)

    @pytest.mark.asyncio
    async def test_user_not_in_voice_returns_without_action(self, mock_bot):
        """[목적] 요청자가 길드의 음성 채널에 없으면 아무 동작 없이 종료되는지 검증

        [검증]
        1. None을 반환함
        2. voice_client 조회(discord.utils.get)가 호출되지 않음
        """
        guild = _make_guild(1, [])

        with patch("discord.utils.get") as mock_get:
            result = await play_music(mock_bot, guild, 1, is_refresh=False)

        assert result is None
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "use_ctx",
        [False, True],
        ids=["sends_to_member_channel", "sends_to_ctx_channel"],
    )
    async def test_connect_failure_sends_guidance_and_returns_connect_failed(
        self, mock_bot, member_in_voice_channel, use_ctx
    ):
        """[목적] 음성 채널 연결에 실패하면 안내 메시지 전송 후 connect_failed를 반환하는지 검증

        [검증]
        1. "connect_failed"를 반환함
        2. 안내 메시지가 전송됨
        3. 재생 기록이 전송되지 않음
        """
        guild, member, channel = member_in_voice_channel()
        channel.connect = AsyncMock(side_effect=Exception("timeout"))
        ctx = MagicMock()
        ctx.send = AsyncMock()

        with patch("bot.music.guild_music_queues", {1: [{"title": "t", "source": "s", "video_id": "v"}]}), \
                patch("discord.utils.get", return_value=None), \
                patch("bot.music.send_play_history", new_callable=AsyncMock) as mock_send_history:
            result = await play_music(mock_bot, guild, member.id, ctx=ctx if use_ctx else None, is_refresh=False)

        assert result == "connect_failed"
        target = ctx if use_ctx else channel
        target.send.assert_called_once_with("⚠️ 음성 채널 연결에 실패했습니다.")
        mock_send_history.assert_not_called()
