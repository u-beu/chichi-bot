import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from bot.music import after_playing, handle_api_playback, play_music


class TestHandleApiPlayback:
    @pytest.mark.asyncio
    async def test_no_guild_returns_early(self):
        """[목적] guild_id에 해당하는 길드가 없을 때 조기 종료되는지 검증

        [검증]
        1. bot.get_guild가 guild_id로 호출됨
        """
        bot = MagicMock()
        bot.get_guild.return_value = None

        await handle_api_playback(bot, 1, 2, "query")

        bot.get_guild.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_no_member_returns_early(self):
        """[목적] 멤버를 캐시에서 찾지 못하면 fetch_member로 재조회하는지 검증

        [검증]
        1. guild.fetch_member가 user_id로 호출됨
        """
        bot = MagicMock()
        guild = MagicMock()
        guild.get_member.return_value = None
        guild.fetch_member = AsyncMock(return_value=None)
        bot.get_guild.return_value = guild

        await handle_api_playback(bot, 1, 2, "query")

        guild.fetch_member.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_member_not_in_voice_returns_early(self):
        """[목적] 멤버가 음성 채널에 접속해 있지 않으면 조기 종료되는지 검증

        [검증]
        1. play_music이 호출되지 않음
        """
        bot = MagicMock()
        guild = MagicMock()
        member = MagicMock()
        member.voice = None
        guild.get_member.return_value = member
        bot.get_guild.return_value = guild

        with patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
            await handle_api_playback(bot, 1, 2, "query")

        mock_play_music.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "existing_voice_client, expect_play_called",
        [(False, True), (True, False)],
        ids=["no_voice_client_starts_playback", "existing_voice_client_skips_play"],
    )
    async def test_voice_client_presence_controls_play_music_call(
        self, mock_bot, member_in_voice_channel, existing_voice_client, expect_play_called
    ):
        """[목적] 길드에 연결된 voice_client 유무에 따라 play_music 호출 여부가 달라지는지 검증

        [검증]
        1. voice_client가 없으면 play_music이 is_refresh=False로 호출되고 조회한 song이 큐 맨 앞에 추가됨
        2. voice_client가 이미 있으면 play_music이 호출되지 않음
        """
        guild, member, _channel = member_in_voice_channel()
        mock_bot.get_guild.return_value = guild
        guild.get_member.return_value = member

        voice_client = MagicMock() if existing_voice_client else None

        with patch("bot.music.guild_music_queues", {}) as mock_queues, \
                patch("bot.music.get_song_info", return_value={"title": "t", "video_id": "v"}), \
                patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
            await handle_api_playback(mock_bot, 1, 2, "query")

        if expect_play_called:
            mock_play_music.assert_called_once_with(mock_bot, guild, member, is_refresh=False)
            assert mock_queues[1][0]["title"] == "t"
        else:
            mock_play_music.assert_not_called()


class TestAfterPlaying:
    @pytest.mark.asyncio
    async def test_no_voice_client_does_nothing(self, mock_bot):
        """[목적] voice_client가 없을 때 아무 동작도 하지 않는지 검증

        [검증]
        1. play_music이 호출되지 않음
        """
        guild = MagicMock(id=1)
        member = MagicMock()

        with patch("discord.utils.get", return_value=None), \
                patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
            after_playing(mock_bot, guild, member)
            await asyncio.sleep(0.01)

        mock_play_music.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_queue_sends_message_and_disconnects(self, mock_bot, voice_client_factory):
        """[목적] 재생 후 대기열이 비어있으면 안내 메시지 전송 후 연결을 종료하는지 검증

        [검증]
        1. 음성 채널에 빈 대기열 안내 메시지가 전송됨
        2. voice_client.disconnect가 호출됨
        3. guild_music_queues에서 해당 길드 큐가 제거됨
        """
        guild = MagicMock(id=1)
        member = MagicMock()
        member.voice.channel.send = AsyncMock()

        voice_client = voice_client_factory(is_connected=True)

        with patch("bot.music.guild_music_queues", {1: []}) as mock_queues, \
                patch("discord.utils.get", return_value=voice_client):
            after_playing(mock_bot, guild, member)
            await asyncio.sleep(0.01)

        member.voice.channel.send.assert_called_once_with("❌ 빈 대기열입니다. 재생을 종료합니다.")
        voice_client.disconnect.assert_called_once()
        assert 1 not in mock_queues

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [None, Exception("ffmpeg crashed")],
        ids=["no_error", "with_error_still_schedules_next"],
    )
    async def test_queue_has_songs_plays_next_regardless_of_error(self, mock_bot, voice_client_factory, error):
        """[목적] 재생 후 대기열에 곡이 남아있으면 error 발생 여부와 무관하게 다음 곡을 재생하는지 검증

        [검증]
        1. error가 없을 때 play_music이 ctx 유지, is_refresh=True로 호출됨
        2. error가 전달되어도(로깅만 되고) play_music 호출은 동일하게 발생함
        """
        guild = MagicMock(id=1)
        member = MagicMock()
        ctx = MagicMock()

        voice_client = voice_client_factory(is_connected=True)

        with patch("bot.music.guild_music_queues", {1: [{"title": "t"}]}), \
                patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
            after_playing(mock_bot, guild, member, ctx=ctx, error=error)
            await asyncio.sleep(0.01)

        mock_play_music.assert_called_once_with(mock_bot, guild, member, ctx=ctx, is_refresh=True)


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
        """[목적] 음성 채널 연결/발언 권한이 없으면 안내 메시지 전송 후 조기 종료되는지 검증

        [검증]
        1. connect 권한이 없고 ctx 미제공 시 멤버의 음성 채널로 권한 안내 메시지가 전송됨
        2. speak 권한이 없고 ctx 제공 시 ctx로 권한 안내 메시지가 전송됨
        3. 두 경우 모두 voice_client 조회(discord.utils.get)가 호출되지 않음(조기 return)
        """
        bot = MagicMock()
        guild, member, channel = member_in_voice_channel(connect=connect, speak=speak)
        ctx = MagicMock()
        ctx.send = AsyncMock()

        with patch("discord.utils.get") as mock_get:
            await play_music(bot, guild, member, ctx=ctx if use_ctx else None, is_refresh=False)

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
            await play_music(bot, guild, member, is_refresh=False)

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
            await play_music(mock_bot, guild, member, is_refresh=False)
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
            await play_music(mock_bot, guild, member, is_refresh=False)
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
            await play_music(mock_bot, guild, member, is_refresh=True)
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
            await play_music(mock_bot, guild, member, is_refresh=True)
            await asyncio.sleep(0)

        channel.send.assert_called_once_with("🎶 재생중: **old**")
        mock_send_history.assert_called_once_with(old_song, 1, mock_bot.redis_client)
