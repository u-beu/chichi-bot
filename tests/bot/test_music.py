import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from bot.music import (
    MAX_DURATION,
    MusicCog,
    SPRING_QUEUE_KEY,
    VideoTooLongError,
    after_playing,
    get_info_async,
    get_song_info,
    handle_api_playback,
    play_music,
    send_play_history,
)


def _make_permissions(connect=True, speak=True):
    perms = MagicMock()
    perms.connect = connect
    perms.speak = speak
    return perms


# ---------------------------------------------------------------------------
# get_song_info
# ---------------------------------------------------------------------------

@patch("yt_dlp.YoutubeDL")
def test_get_song_info_success(mock_ydl_class):
    """[목적] 검색어로 정상 조회 시 song dict 변환 결과를 검증

    [검증]
    1. extract_info가 "ytsearch1:{query}"와 download=False로 호출됨
    2. 반환값이 source/title/uploader/image/video_id로 매핑됨
    """
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {
        "duration": 120,
        "url": "stream-url",
        "title": "title",
        "uploader": "uploader",
        "thumbnail": "thumb",
        "display_id": "vid123",
    }
    mock_ydl_class.return_value.__enter__.return_value = mock_ydl

    result = get_song_info("query", from_url=False)

    mock_ydl.extract_info.assert_called_once_with("ytsearch1:query", download=False)
    assert result == {
        "source": "stream-url",
        "title": "title",
        "uploader": "uploader",
        "image": "thumb",
        "video_id": "vid123",
    }


@patch("yt_dlp.YoutubeDL")
def test_get_song_info_from_url_uses_raw_query(mock_ydl_class):
    """[목적] from_url=True일 때 쿼리를 가공하지 않고 그대로 전달하는지 검증

    [검증]
    1. extract_info가 원본 url 문자열과 download=False로 호출됨
    """
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {
        "duration": 60,
        "url": "u",
        "title": "t",
        "uploader": "up",
        "thumbnail": "th",
        "display_id": "id1",
    }
    mock_ydl_class.return_value.__enter__.return_value = mock_ydl

    get_song_info("https://youtu.be/x", from_url=True)

    mock_ydl.extract_info.assert_called_once_with("https://youtu.be/x", download=False)


@patch("yt_dlp.YoutubeDL")
def test_get_song_info_entries_takes_first(mock_ydl_class):
    """[목적] extract_info 결과에 entries 리스트가 있을 때 첫 항목을 사용하는지 검증

    [검증]
    1. 반환된 video_id가 entries[0]의 display_id와 일치함
    """
    mock_ydl = MagicMock()
    entry = {
        "duration": 60,
        "url": "u",
        "title": "t",
        "uploader": "up",
        "thumbnail": "th",
        "display_id": "id1",
    }
    mock_ydl.extract_info.return_value = {"entries": [entry]}
    mock_ydl_class.return_value.__enter__.return_value = mock_ydl

    result = get_song_info("query")

    assert result["video_id"] == "id1"


@patch("yt_dlp.YoutubeDL")
def test_get_song_info_too_long_raises(mock_ydl_class):
    """[목적] 영상 길이가 MAX_DURATION을 초과하면 예외가 발생하는지 검증

    [검증]
    1. VideoTooLongError가 발생함
    """
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {
        "duration": MAX_DURATION + 1,
        "url": "u",
        "title": "t",
        "uploader": "up",
        "thumbnail": "th",
        "display_id": "id1",
    }
    mock_ydl_class.return_value.__enter__.return_value = mock_ydl

    with pytest.raises(VideoTooLongError):
        get_song_info("query")


@pytest.mark.asyncio
async def test_get_info_async_delegates_to_executor():
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


# ---------------------------------------------------------------------------
# send_play_history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_play_history_success():
    """[목적] song 정보가 Redis LPUSH payload(camelCase)로 정상 변환되는지 검증

    [검증]
    1. lpush가 SPRING_QUEUE_KEY를 키로 호출됨
    2. payload JSON이 title/uploader/image/videoId/discordId로 매핑됨
    """
    redis_client = AsyncMock()
    song = {"title": "T", "uploader": "U", "image": "I", "video_id": "V"}

    await send_play_history(song, 123, redis_client)

    redis_client.lpush.assert_called_once()
    key, payload_json = redis_client.lpush.call_args[0]
    assert key == SPRING_QUEUE_KEY
    assert json.loads(payload_json) == {
        "title": "T",
        "uploader": "U",
        "image": "I",
        "videoId": "V",
        "discordId": 123,
    }


@pytest.mark.asyncio
async def test_send_play_history_defaults_missing_fields():
    """[목적] song dict에 필드가 없을 때 기본값이 채워지는지 검증

    [검증]
    1. title 기본값이 "Unknown Title"
    2. uploader 기본값이 "Unknown Uploader"
    3. image 기본값이 "null"
    4. videoId 기본값이 None
    """
    redis_client = AsyncMock()

    await send_play_history({}, 1, redis_client)

    payload = json.loads(redis_client.lpush.call_args[0][1])
    assert payload["title"] == "Unknown Title"
    assert payload["uploader"] == "Unknown Uploader"
    assert payload["image"] == "null"
    assert payload["videoId"] is None


@pytest.mark.asyncio
async def test_send_play_history_exception_is_swallowed():
    """[목적] redis_client.lpush에서 예외가 발생해도 호출자에게 전파되지 않는지 검증

    [검증]
    1. 예외 발생 시에도 함수가 정상적으로 반환됨(로깅만 수행)
    """
    redis_client = AsyncMock()
    redis_client.lpush.side_effect = Exception("redis down")

    # 예외가 전파되지 않고 로깅만 되어야 함
    await send_play_history({"title": "T"}, 1, redis_client)


# ---------------------------------------------------------------------------
# handle_api_playback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_api_playback_no_guild_returns_early():
    """[목적] guild_id에 해당하는 길드가 없을 때 조기 종료되는지 검증

    [검증]
    1. bot.get_guild가 guild_id로 호출됨
    """
    bot = MagicMock()
    bot.get_guild.return_value = None

    await handle_api_playback(bot, 1, 2, "query")

    bot.get_guild.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_handle_api_playback_no_member_returns_early():
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
async def test_handle_api_playback_member_not_in_voice_returns_early():
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
async def test_handle_api_playback_no_voice_client_starts_playback():
    """[목적] 길드에 연결된 voice_client가 없을 때 재생을 시작하는지 검증

    [검증]
    1. play_music이 is_refresh=False로 호출됨
    2. 조회한 song이 큐 맨 앞에 추가됨
    """
    bot = MagicMock()
    bot.loop = asyncio.get_event_loop()
    guild = MagicMock()
    member = MagicMock()
    member.voice.channel = MagicMock()
    guild.get_member.return_value = member
    bot.get_guild.return_value = guild

    with patch("bot.music.guild_music_queues", {}) as mock_queues, \
            patch("bot.music.get_song_info", return_value={"title": "t", "video_id": "v"}), \
            patch("discord.utils.get", return_value=None), \
            patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
        await handle_api_playback(bot, 1, 2, "query")

    mock_play_music.assert_called_once_with(bot, guild, member, is_refresh=False)
    assert mock_queues[1][0]["title"] == "t"


@pytest.mark.asyncio
async def test_handle_api_playback_existing_voice_client_skips_play():
    """[목적] 이미 연결된 voice_client가 있으면 play_music을 호출하지 않는지 검증

    [검증]
    1. play_music이 호출되지 않음
    """
    bot = MagicMock()
    bot.loop = asyncio.get_event_loop()
    guild = MagicMock()
    member = MagicMock()
    member.voice.channel = MagicMock()
    guild.get_member.return_value = member
    bot.get_guild.return_value = guild

    with patch("bot.music.guild_music_queues", {}), \
            patch("bot.music.get_song_info", return_value={"title": "t", "video_id": "v"}), \
            patch("discord.utils.get", return_value=MagicMock()), \
            patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
        await handle_api_playback(bot, 1, 2, "query")

    mock_play_music.assert_not_called()


# ---------------------------------------------------------------------------
# after_playing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_after_playing_no_voice_client_does_nothing():
    """[목적] voice_client가 없을 때 아무 동작도 하지 않는지 검증

    [검증]
    1. play_music이 호출되지 않음
    """
    bot = MagicMock()
    bot.loop = asyncio.get_event_loop()
    guild = MagicMock(id=1)
    member = MagicMock()

    with patch("discord.utils.get", return_value=None), \
            patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
        after_playing(bot, guild, member)
        await asyncio.sleep(0.01)

    mock_play_music.assert_not_called()


@pytest.mark.asyncio
async def test_after_playing_empty_queue_sends_message_and_disconnects():
    """[목적] 재생 후 대기열이 비어있으면 안내 메시지 전송 후 연결을 종료하는지 검증

    [검증]
    1. 음성 채널에 빈 대기열 안내 메시지가 전송됨
    2. voice_client.disconnect가 호출됨
    3. guild_music_queues에서 해당 길드 큐가 제거됨
    """
    bot = MagicMock()
    bot.loop = asyncio.get_event_loop()
    guild = MagicMock(id=1)
    member = MagicMock()
    member.voice.channel.send = AsyncMock()

    voice_client = MagicMock()
    voice_client.is_connected.return_value = True
    voice_client.disconnect = AsyncMock()

    with patch("bot.music.guild_music_queues", {1: []}) as mock_queues, \
            patch("discord.utils.get", return_value=voice_client):
        after_playing(bot, guild, member)
        await asyncio.sleep(0.01)

    member.voice.channel.send.assert_called_once_with("❌ 빈 대기열입니다. 재생을 종료합니다.")
    voice_client.disconnect.assert_called_once()
    assert 1 not in mock_queues


@pytest.mark.asyncio
async def test_after_playing_queue_has_songs_plays_next():
    """[목적] 재생 후 대기열에 곡이 남아있으면 다음 곡을 재생하는지 검증

    [검증]
    1. play_music이 ctx 유지, is_refresh=True로 호출됨
    """
    bot = MagicMock()
    bot.loop = asyncio.get_event_loop()
    guild = MagicMock(id=1)
    member = MagicMock()
    ctx = MagicMock()

    voice_client = MagicMock()
    voice_client.is_connected.return_value = True

    with patch("bot.music.guild_music_queues", {1: [{"title": "t"}]}), \
            patch("discord.utils.get", return_value=voice_client), \
            patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
        after_playing(bot, guild, member, ctx=ctx)
        await asyncio.sleep(0.01)

    mock_play_music.assert_called_once_with(bot, guild, member, ctx=ctx, is_refresh=True)


@pytest.mark.asyncio
async def test_after_playing_logs_error_but_still_schedules_next():
    """[목적] 이전 재생에서 에러가 발생해도 다음 곡 재생 스케줄링은 계속되는지 검증

    [검증]
    1. error 전달 여부와 무관하게 play_music이 호출됨
    """
    bot = MagicMock()
    bot.loop = asyncio.get_event_loop()
    guild = MagicMock(id=1)
    member = MagicMock()

    voice_client = MagicMock()
    voice_client.is_connected.return_value = True

    with patch("bot.music.guild_music_queues", {1: [{"title": "t"}]}), \
            patch("discord.utils.get", return_value=voice_client), \
            patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
        after_playing(bot, guild, member, error=Exception("ffmpeg crashed"))
        await asyncio.sleep(0.01)

    mock_play_music.assert_called_once()


# ---------------------------------------------------------------------------
# play_music
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_play_music_no_connect_permission_sends_message_and_returns():
    """[목적] 음성 채널 연결 권한이 없으면 안내 메시지 전송 후 조기 종료되는지 검증

    [검증]
    1. 채널에 권한 안내 메시지가 전송됨
    2. voice_client 조회(discord.utils.get)가 호출되지 않음(조기 return)
    """
    bot = MagicMock()
    guild = MagicMock()
    member = MagicMock()
    channel = MagicMock()
    channel.permissions_for.return_value = _make_permissions(connect=False)
    channel.send = AsyncMock()
    member.voice.channel = channel

    with patch("discord.utils.get") as mock_get:
        await play_music(bot, guild, member, is_refresh=False)

    channel.send.assert_called_once_with("⛔ 해당 음성 채널에 연결 권한이 없습니다.")
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_play_music_no_speak_permission_uses_ctx_channel():
    """[목적] 발언 권한이 없고 ctx가 있을 때 ctx로 안내 메시지를 보내는지 검증

    [검증]
    1. ctx.send로 권한 안내 메시지가 전송됨
    """
    bot = MagicMock()
    guild = MagicMock()
    member = MagicMock()
    channel = MagicMock()
    channel.permissions_for.return_value = _make_permissions(speak=False)
    member.voice.channel = channel
    ctx = MagicMock()
    ctx.send = AsyncMock()

    await play_music(bot, guild, member, ctx=ctx, is_refresh=False)

    ctx.send.assert_called_once_with("⛔ 해당 음성 채널에 연결 권한이 없습니다.")


@pytest.mark.asyncio
async def test_play_music_empty_queue_connects_but_returns_early():
    """[목적] 음성 채널 연결은 하되 대기열이 비어있으면 재생 없이 종료되는지 검증

    [검증]
    1. member_voice_channel.connect가 호출됨
    2. send_play_history가 호출되지 않음
    """
    bot = MagicMock()
    guild = MagicMock(id=1)
    member = MagicMock()
    channel = MagicMock()
    channel.permissions_for.return_value = _make_permissions()
    channel.connect = AsyncMock(return_value=MagicMock())
    member.voice.channel = channel

    with patch("bot.music.guild_music_queues", {}), \
            patch("discord.utils.get", return_value=None), \
            patch("bot.music.send_play_history", new_callable=AsyncMock) as mock_send_history:
        await play_music(bot, guild, member, is_refresh=False)

    channel.connect.assert_called_once()
    mock_send_history.assert_not_called()


@pytest.mark.asyncio
async def test_play_music_connects_plays_and_sends_history():
    """[목적] 신규 연결 후 곡을 재생하고 재생 기록을 전송하는지 검증

    [검증]
    1. voice_channel.connect가 호출됨
    2. voice_client.play가 호출됨
    3. 재생중 안내 메시지가 전송됨
    4. send_play_history가 song/member.id/bot.redis_client로 호출됨
    """
    bot = MagicMock()
    bot.redis_client = MagicMock()
    guild = MagicMock(id=1)
    member = MagicMock(id=42)
    channel = MagicMock()
    channel.permissions_for.return_value = _make_permissions()
    channel.send = AsyncMock()
    new_voice_client = MagicMock()
    channel.connect = AsyncMock(return_value=new_voice_client)
    member.voice.channel = channel

    song = {"title": "Song A", "source": "src", "video_id": "vid"}

    with patch("bot.music.guild_music_queues", {1: [song]}), \
            patch("discord.utils.get", return_value=None), \
            patch("discord.FFmpegPCMAudio", return_value=MagicMock()), \
            patch("discord.PCMVolumeTransformer", return_value=MagicMock()), \
            patch("bot.music.send_play_history", new_callable=AsyncMock) as mock_send_history:
        await play_music(bot, guild, member, is_refresh=False)
        await asyncio.sleep(0)

    channel.connect.assert_called_once()
    new_voice_client.play.assert_called_once()
    channel.send.assert_called_once_with("🎶 재생중: **Song A**")
    mock_send_history.assert_called_once_with(song, 42, bot.redis_client)


@pytest.mark.asyncio
async def test_play_music_moves_to_member_channel_when_different():
    """[목적] 기존 voice_client가 다른 채널에 있으면 멤버의 채널로 이동하는지 검증

    [검증]
    1. voice_client.move_to가 멤버의 음성 채널로 호출됨
    """
    bot = MagicMock()
    bot.redis_client = MagicMock()
    guild = MagicMock(id=1)
    member = MagicMock(id=1)
    channel = MagicMock()
    channel.permissions_for.return_value = _make_permissions()
    channel.send = AsyncMock()
    member.voice.channel = channel

    other_channel = MagicMock()
    voice_client = MagicMock()
    voice_client.is_connected.return_value = True
    voice_client.channel = other_channel
    voice_client.move_to = AsyncMock()

    song = {"title": "t", "source": "s", "video_id": "v"}

    with patch("bot.music.guild_music_queues", {1: [song]}), \
            patch("discord.utils.get", return_value=voice_client), \
            patch("discord.FFmpegPCMAudio", return_value=MagicMock()), \
            patch("discord.PCMVolumeTransformer", return_value=MagicMock()), \
            patch("bot.music.send_play_history", new_callable=AsyncMock):
        await play_music(bot, guild, member, is_refresh=False)
        await asyncio.sleep(0)

    voice_client.move_to.assert_called_once_with(channel)


@pytest.mark.asyncio
async def test_play_music_is_refresh_requeries_song_info():
    """[목적] is_refresh=True일 때 video_id 기반 URL로 song 정보를 재조회하는지 검증

    [검증]
    1. get_song_info가 watch URL과 from_url=True로 호출됨
    2. 재생중 메시지가 갱신된 title로 전송됨
    3. send_play_history가 갱신된 song으로 호출됨
    """
    bot = MagicMock()
    bot.loop = asyncio.get_event_loop()
    bot.redis_client = MagicMock()
    guild = MagicMock(id=1)
    member = MagicMock(id=1)
    channel = MagicMock()
    channel.permissions_for.return_value = _make_permissions()
    channel.send = AsyncMock()
    member.voice.channel = channel

    voice_client = MagicMock()
    voice_client.is_connected.return_value = True
    voice_client.channel = channel

    old_song = {"title": "old", "source": "old-src", "video_id": "vid123"}
    refreshed_song = {"title": "fresh", "source": "fresh-src", "video_id": "vid123"}

    with patch("bot.music.guild_music_queues", {1: [old_song]}), \
            patch("discord.utils.get", return_value=voice_client), \
            patch("bot.music.get_song_info", return_value=refreshed_song) as mock_get_song_info, \
            patch("discord.FFmpegPCMAudio", return_value=MagicMock()), \
            patch("discord.PCMVolumeTransformer", return_value=MagicMock()), \
            patch("bot.music.send_play_history", new_callable=AsyncMock) as mock_send_history:
        await play_music(bot, guild, member, is_refresh=True)
        await asyncio.sleep(0)

    mock_get_song_info.assert_called_once_with(
        "https://www.youtube.com/watch?v=vid123", from_url=True
    )
    channel.send.assert_called_once_with("🎶 재생중: **fresh**")
    mock_send_history.assert_called_once_with(refreshed_song, 1, bot.redis_client)


@pytest.mark.asyncio
async def test_play_music_is_refresh_failure_keeps_old_song():
    """[목적] is_refresh 재조회가 실패하면 기존 song 정보를 그대로 사용하는지 검증

    [검증]
    1. 재생중 메시지가 기존 title로 전송됨
    2. send_play_history가 기존 song으로 호출됨
    """
    bot = MagicMock()
    bot.loop = asyncio.get_event_loop()
    bot.redis_client = MagicMock()
    guild = MagicMock(id=1)
    member = MagicMock(id=1)
    channel = MagicMock()
    channel.permissions_for.return_value = _make_permissions()
    channel.send = AsyncMock()
    member.voice.channel = channel

    voice_client = MagicMock()
    voice_client.is_connected.return_value = True
    voice_client.channel = channel

    old_song = {"title": "old", "source": "old-src", "video_id": "vid123"}

    with patch("bot.music.guild_music_queues", {1: [old_song]}), \
            patch("discord.utils.get", return_value=voice_client), \
            patch("bot.music.get_song_info", side_effect=Exception("boom")), \
            patch("discord.FFmpegPCMAudio", return_value=MagicMock()), \
            patch("discord.PCMVolumeTransformer", return_value=MagicMock()), \
            patch("bot.music.send_play_history", new_callable=AsyncMock) as mock_send_history:
        await play_music(bot, guild, member, is_refresh=True)
        await asyncio.sleep(0)

    channel.send.assert_called_once_with("🎶 재생중: **old**")
    mock_send_history.assert_called_once_with(old_song, 1, bot.redis_client)


# ---------------------------------------------------------------------------
# MusicCog
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cog_play_user_not_in_voice():
    """[목적] 호출자가 음성 채널에 없으면 안내 메시지만 전송하는지 검증

    [검증]
    1. "⛔ 음성 채널에서 호출해주세요." 메시지가 전송됨
    """
    cog = MusicCog(MagicMock())
    ctx = MagicMock()
    ctx.author.voice = None
    ctx.send = AsyncMock()

    await cog.play.callback(cog, ctx, arg="song")

    ctx.send.assert_called_once_with("⛔ 음성 채널에서 호출해주세요.")


@pytest.mark.asyncio
async def test_cog_play_song_not_found():
    """[목적] get_info_async가 곡을 찾지 못하면 실패 메시지를 전송하는지 검증

    [검증]
    1. "❌ 노래 탐색에 실패했습니다." 메시지가 전송됨
    """
    cog = MusicCog(MagicMock())
    ctx = MagicMock()
    ctx.author.voice.channel = MagicMock()
    ctx.send = AsyncMock()

    with patch("bot.music.get_info_async", new_callable=AsyncMock, return_value=None):
        await cog.play.callback(cog, ctx, arg="song")

    ctx.send.assert_called_once_with("❌ 노래 탐색에 실패했습니다.")


@pytest.mark.asyncio
async def test_cog_play_default_query_when_no_arg():
    """[목적] arg가 없을 때 기본 검색어("최신곡 모음")로 조회하는지 검증

    [검증]
    1. get_info_async가 "최신곡 모음", is_url=False로 호출됨
    """
    bot = MagicMock()
    cog = MusicCog(bot)
    ctx = MagicMock()
    ctx.author.voice.channel = MagicMock()
    ctx.send = AsyncMock()
    ctx.guild.id = 1
    ctx.bot = bot

    with patch("bot.music.guild_music_queues", {}), \
            patch("bot.music.get_info_async", new_callable=AsyncMock, return_value={"title": "T"}) as mock_get_info, \
            patch("discord.utils.get", return_value=None), \
            patch("bot.music.play_music", new_callable=AsyncMock):
        await cog.play.callback(cog, ctx, arg=None)

    mock_get_info.assert_called_once_with(ctx, "최신곡 모음", is_url=False)


@pytest.mark.asyncio
async def test_cog_play_detects_url():
    """[목적] arg에 "https://"가 포함되면 is_url=True로 조회하는지 검증

    [검증]
    1. get_info_async가 is_url=True로 호출됨
    """
    bot = MagicMock()
    cog = MusicCog(bot)
    ctx = MagicMock()
    ctx.author.voice.channel = MagicMock()
    ctx.send = AsyncMock()
    ctx.guild.id = 1
    ctx.bot = bot

    with patch("bot.music.guild_music_queues", {}), \
            patch("bot.music.get_info_async", new_callable=AsyncMock, return_value={"title": "T"}) as mock_get_info, \
            patch("discord.utils.get", return_value=None), \
            patch("bot.music.play_music", new_callable=AsyncMock):
        await cog.play.callback(cog, ctx, arg="https://youtu.be/x")

    mock_get_info.assert_called_once_with(ctx, "https://youtu.be/x", is_url=True)


@pytest.mark.asyncio
async def test_cog_play_add_to_queue_while_playing():
    """[목적] 재생 중 --add 플래그로 호출 시 대기열에 추가만 되는지 검증

    [검증]
    1. 조회한 곡이 큐 끝에 추가됨
    2. "✅ 대기열 추가: **T**" 메시지가 전송됨
    3. play_music이 호출되지 않음
    """
    bot = MagicMock()
    cog = MusicCog(bot)
    ctx = MagicMock()
    ctx.author.voice.channel = MagicMock()
    ctx.send = AsyncMock()
    ctx.guild.id = 1

    voice_client = MagicMock()
    voice_client.is_playing.return_value = True

    with patch("bot.music.guild_music_queues", {}) as mock_queues, \
            patch("bot.music.get_info_async", new_callable=AsyncMock, return_value={"title": "T"}), \
            patch("discord.utils.get", return_value=voice_client), \
            patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
        await cog.play.callback(cog, ctx, arg="--add song")

    assert mock_queues[1][-1]["title"] == "T"
    ctx.send.assert_called_once_with("✅ 대기열 추가: **T**")
    mock_play_music.assert_not_called()


@pytest.mark.asyncio
async def test_cog_play_immediate_interrupts_current_song():
    """[목적] 재생 중 --add 없이 호출 시 현재 곡을 중단하고 즉시 재생으로 전환하는지 검증

    [검증]
    1. 조회한 곡이 큐 맨 앞에 추가됨
    2. voice_client.stop이 호출됨
    3. "▶️ 현재 곡을 중단하고 즉시 재생합니다." 메시지가 전송됨
    4. play_music이 직접 호출되지 않음(after_playing 콜백에 위임)
    """
    bot = MagicMock()
    cog = MusicCog(bot)
    ctx = MagicMock()
    ctx.author.voice.channel = MagicMock()
    ctx.send = AsyncMock()
    ctx.guild.id = 1

    voice_client = MagicMock()
    voice_client.is_playing.return_value = True

    with patch("bot.music.guild_music_queues", {}) as mock_queues, \
            patch("bot.music.get_info_async", new_callable=AsyncMock, return_value={"title": "T"}), \
            patch("discord.utils.get", return_value=voice_client), \
            patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
        await cog.play.callback(cog, ctx, arg="song")

    assert mock_queues[1][0]["title"] == "T"
    voice_client.stop.assert_called_once()
    ctx.send.assert_called_once_with("▶️ 현재 곡을 중단하고 즉시 재생합니다.")
    mock_play_music.assert_not_called()


@pytest.mark.asyncio
async def test_cog_play_no_current_playback_plays_immediately():
    """[목적] 재생 중인 곡이 없을 때 즉시 play_music을 호출해 재생하는지 검증

    [검증]
    1. 조회한 곡이 큐 맨 앞에 추가됨
    2. "▶️ 즉시 재생합니다." 메시지가 전송됨
    3. play_music이 ctx 포함, is_refresh=False로 호출됨
    """
    bot = MagicMock()
    cog = MusicCog(bot)
    ctx = MagicMock()
    ctx.author.voice.channel = MagicMock()
    ctx.send = AsyncMock()
    ctx.guild.id = 1
    ctx.bot = bot

    with patch("bot.music.guild_music_queues", {}) as mock_queues, \
            patch("bot.music.get_info_async", new_callable=AsyncMock, return_value={"title": "T"}), \
            patch("discord.utils.get", return_value=None), \
            patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
        await cog.play.callback(cog, ctx, arg="song")

    assert mock_queues[1][0]["title"] == "T"
    ctx.send.assert_called_once_with("▶️ 즉시 재생합니다.")
    mock_play_music.assert_called_once_with(bot, ctx.guild, ctx.author, ctx=ctx, is_refresh=False)


@pytest.mark.asyncio
async def test_cog_skip_playing_stops_and_notifies():
    """[목적] 재생 중일 때 skip 명령이 다음 곡으로 넘기는지 검증

    [검증]
    1. "⏭️ 다음 곡을 재생합니다." 메시지가 전송됨
    2. voice_client.stop이 호출됨
    """
    cog = MusicCog(MagicMock())
    ctx = MagicMock()
    ctx.send = AsyncMock()
    voice_client = MagicMock()
    voice_client.is_playing.return_value = True

    with patch("discord.utils.get", return_value=voice_client):
        await cog.skip.callback(cog, ctx)

    ctx.send.assert_called_once_with("⏭️ 다음 곡을 재생합니다.")
    voice_client.stop.assert_called_once()


@pytest.mark.asyncio
async def test_cog_skip_not_playing_does_nothing():
    """[목적] 재생 중이 아닐 때 skip 명령이 아무 동작도 하지 않는지 검증

    [검증]
    1. ctx.send가 호출되지 않음
    """
    cog = MusicCog(MagicMock())
    ctx = MagicMock()
    ctx.send = AsyncMock()

    with patch("discord.utils.get", return_value=None):
        await cog.skip.callback(cog, ctx)

    ctx.send.assert_not_called()


@pytest.mark.asyncio
async def test_cog_stop_disconnects_when_connected():
    """[목적] voice_client가 연결되어 있을 때 stop 명령이 연결을 종료하는지 검증

    [검증]
    1. voice_client.disconnect가 호출됨
    2. "🛑 노래 재생을 중지합니다." 메시지가 전송됨
    """
    cog = MusicCog(MagicMock())
    ctx = MagicMock()
    ctx.send = AsyncMock()
    voice_client = MagicMock()
    voice_client.disconnect = AsyncMock()

    with patch("discord.utils.get", return_value=voice_client):
        await cog.stop.callback(cog, ctx)

    voice_client.disconnect.assert_called_once()
    ctx.send.assert_called_once_with("🛑 노래 재생을 중지합니다.")


@pytest.mark.asyncio
async def test_cog_stop_no_voice_client_does_nothing():
    """[목적] voice_client가 없을 때 stop 명령이 아무 동작도 하지 않는지 검증

    [검증]
    1. ctx.send가 호출되지 않음
    """
    cog = MusicCog(MagicMock())
    ctx = MagicMock()
    ctx.send = AsyncMock()

    with patch("discord.utils.get", return_value=None):
        await cog.stop.callback(cog, ctx)

    ctx.send.assert_not_called()


@pytest.mark.asyncio
async def test_cog_resume_already_playing():
    """[목적] 이미 재생 중일 때 resume 명령이 중복 재생을 막는지 검증

    [검증]
    1. "🎶 이미 노래를 재생 중입니다." 메시지가 전송됨
    2. play_music이 호출되지 않음
    """
    cog = MusicCog(MagicMock())
    ctx = MagicMock()
    ctx.send = AsyncMock()
    voice_client = MagicMock()
    voice_client.is_playing.return_value = True

    with patch("discord.utils.get", return_value=voice_client), \
            patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
        await cog.resume.callback(cog, ctx)

    ctx.send.assert_called_once_with("🎶 이미 노래를 재생 중입니다.")
    mock_play_music.assert_not_called()


@pytest.mark.asyncio
async def test_cog_resume_empty_queue():
    """[목적] 대기열이 비어있을 때 resume 명령이 실패 메시지를 전송하는지 검증

    [검증]
    1. "❌ 빈 대기열입니다." 메시지가 전송됨
    2. play_music이 호출되지 않음
    """
    cog = MusicCog(MagicMock())
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.guild.id = 1

    with patch("discord.utils.get", return_value=None), \
            patch("bot.music.guild_music_queues", {}), \
            patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
        await cog.resume.callback(cog, ctx)

    ctx.send.assert_called_once_with("❌ 빈 대기열입니다.")
    mock_play_music.assert_not_called()


@pytest.mark.asyncio
async def test_cog_resume_plays_from_queue():
    """[목적] 대기열에 곡이 있을 때 resume 명령이 재생을 재시작하는지 검증

    [검증]
    1. "✅ 다시 재생합니다." 메시지가 전송됨
    2. play_music이 is_refresh=True로 호출됨
    """
    bot = MagicMock()
    cog = MusicCog(bot)
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.guild.id = 1
    ctx.bot = bot

    with patch("discord.utils.get", return_value=None), \
            patch("bot.music.guild_music_queues", {1: [{"title": "t"}]}), \
            patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
        await cog.resume.callback(cog, ctx)

    ctx.send.assert_called_once_with("✅ 다시 재생합니다.")
    mock_play_music.assert_called_once_with(bot, ctx.guild, ctx.author, ctx=ctx, is_refresh=True)


@pytest.mark.asyncio
async def test_cog_queue_empty():
    """[목적] 대기열이 비어있을 때 queue 명령이 빈 대기열 메시지를 전송하는지 검증

    [검증]
    1. "빈 대기열" 메시지가 전송됨
    """
    cog = MusicCog(MagicMock())
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.guild.id = 1

    with patch("bot.music.guild_music_queues", {}):
        await cog.queue.callback(cog, ctx)

    ctx.send.assert_called_once_with("빈 대기열")


@pytest.mark.asyncio
async def test_cog_queue_lists_up_to_ten_songs_and_shows_remainder():
    """[목적] 대기열이 10개를 초과할 때 상위 10개만 표시하고 나머지 개수를 안내하는지 검증

    [검증]
    1. 1~10번째 곡(song0~song9)이 메시지에 포함됨
    2. 11번째 곡(song10)은 메시지에 포함되지 않음
    3. "외 2곡 더 있음" 안내 문구가 포함됨
    """
    cog = MusicCog(MagicMock())
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.guild.id = 1
    songs = [{"title": f"song{i}"} for i in range(12)]

    with patch("bot.music.guild_music_queues", {1: songs}):
        await cog.queue.callback(cog, ctx)

    sent_message = ctx.send.call_args[0][0]
    assert "song0" in sent_message
    assert "song9" in sent_message
    assert "song10" not in sent_message
    assert "외 2곡 더 있음" in sent_message


@pytest.mark.asyncio
async def test_cog_clear_empties_queue():
    """[목적] clear 명령이 길드의 대기열을 완전히 비우는지 검증

    [검증]
    1. guild_music_queues에서 해당 길드 큐가 제거됨
    2. "▶️ 대기열 목록 초기화" 메시지가 전송됨
    """
    cog = MusicCog(MagicMock())
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.guild.id = 1

    with patch("bot.music.guild_music_queues", {1: [{"title": "t"}]}) as mock_queues:
        await cog.clear.callback(cog, ctx)

    assert 1 not in mock_queues
    ctx.send.assert_called_once_with("▶️ 대기열 목록 초기화")
