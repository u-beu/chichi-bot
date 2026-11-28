import pytest
from discord.ext import commands
from unittest.mock import AsyncMock, MagicMock, patch

from bot.music import MusicCog, PAUSE_TIMEOUT_SEC, _pause_timeout


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
        voice_client.is_paused.return_value = False

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
        mock_play_music.assert_called_once_with(bot, mock_ctx.guild, mock_ctx.author.id, ctx=mock_ctx, is_refresh=False)


class TestCogPlayPaused:
    @pytest.mark.asyncio
    async def test_play_while_paused_interrupts_like_playing(self, mock_ctx):
        """[목적] 일시정지 중에도 play가 재생 중과 동일하게 stop 경로로 처리되는지 검증

        [검증]
        1. 조회한 곡이 큐 맨 앞에 추가되고 voice_client.stop이 호출됨
        2. "▶️ 현재 곡을 중단하고 즉시 재생합니다." 메시지가 전송됨
        3. play_music은 호출되지 않음
        """
        cog = MusicCog(MagicMock())
        voice_client = MagicMock()
        voice_client.is_playing.return_value = False
        voice_client.is_paused.return_value = True

        with patch("bot.music.guild_music_queues", {}) as mock_queues, \
                patch("bot.music.get_info_async", new_callable=AsyncMock, return_value={"title": "T"}), \
                patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.play_music", new_callable=AsyncMock) as mock_play_music:
            await cog.play.callback(cog, mock_ctx, arg="song")

        assert mock_queues[1][0]["title"] == "T"
        voice_client.stop.assert_called_once()
        mock_ctx.send.assert_called_once_with("▶️ 현재 곡을 중단하고 즉시 재생합니다.")
        mock_play_music.assert_not_called()


class TestCogCheck:
    @pytest.mark.asyncio
    async def test_dm_raises_no_private_message(self):
        """[목적] DM(길드 없음)에서 호출 시 NoPrivateMessage가 발생하는지 검증

        [검증]
        1. ctx.guild가 None이면 commands.NoPrivateMessage가 raise됨
        """
        cog = MusicCog(MagicMock())
        ctx = MagicMock(guild=None)

        with pytest.raises(commands.NoPrivateMessage):
            await cog.cog_check(ctx)

    @pytest.mark.asyncio
    async def test_guild_returns_true(self, mock_ctx):
        """[목적] 길드에서 호출 시 cog_check가 통과하는지 검증

        [검증]
        1. True를 반환함
        """
        cog = MusicCog(MagicMock())

        assert await cog.cog_check(mock_ctx) is True


class TestRequireVoice:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "command_name",
        ["skip", "stop", "clear", "resume", "pause"],
    )
    @pytest.mark.parametrize(
        "voice_state",
        ["no_voice", "no_channel"],
        ids=["voice_none", "channel_none"],
    )
    async def test_outside_voice_only_sends_guidance(self, mock_ctx, command_name, voice_state):
        """[목적] 음성 채널 밖에서 호출한 명령이 안내 메시지만 전송하고 동작하지 않는지 검증

        [검증]
        1. "⛔ 음성 채널에서 호출해주세요." 메시지만 전송됨
        2. voice_client 조회/조작 및 대기열 삭제가 일어나지 않음
        """
        cog = MusicCog(MagicMock())
        if voice_state == "no_voice":
            mock_ctx.author.voice = None
        else:
            mock_ctx.author.voice.channel = None
        voice_client = MagicMock()
        voice_client.is_playing.return_value = True
        voice_client.is_paused.return_value = True
        voice_client.disconnect = AsyncMock()

        with patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.guild_music_queues", {1: [{"title": "t"}]}) as mock_queues, \
                patch("bot.music.guild_pause_tasks", {}) as mock_tasks:
            await getattr(cog, command_name).callback(cog, mock_ctx)

        mock_ctx.send.assert_called_once_with("⛔ 음성 채널에서 호출해주세요.")
        voice_client.stop.assert_not_called()
        voice_client.pause.assert_not_called()
        voice_client.resume.assert_not_called()
        voice_client.disconnect.assert_not_called()
        assert mock_queues == {1: [{"title": "t"}]}
        assert mock_tasks == {}


class TestCogSkip:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state",
        ["playing", "paused", "idle", "none"],
    )
    async def test_skip(self, mock_ctx, voice_client_factory, state):
        """[목적] 재생/일시정지 여부에 따라 skip 명령의 동작이 달라지는지 검증

        [검증]
        1. 재생 중이거나 일시정지 중이면 "⏭️ 다음 곡을 재생합니다." 메시지 전송 및 voice_client.stop 호출
        2. 유휴 상태이거나 voice_client가 없으면 아무 메시지도 전송되지 않음
        """
        cog = MusicCog(MagicMock())
        voice_client = None
        if state != "none":
            voice_client = voice_client_factory(is_playing=state == "playing", is_paused=state == "paused")

        with patch("discord.utils.get", return_value=voice_client):
            await cog.skip.callback(cog, mock_ctx)

        if state in ("playing", "paused"):
            mock_ctx.send.assert_called_once_with("⏭️ 다음 곡을 재생합니다.")
            voice_client.stop.assert_called_once()
        else:
            mock_ctx.send.assert_not_called()
            if voice_client:
                voice_client.stop.assert_not_called()


class TestCogStop:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "has_voice_client",
        [True, False],
        ids=["clears_queue_and_disconnects", "no_voice_client_still_clears_queue"],
    )
    async def test_stop(self, mock_ctx, voice_client_factory, has_voice_client):
        """[목적] voice_client 존재 여부와 무관하게 stop이 대기열을 삭제하는지 검증

        [검증]
        1. 대기열이 항상 삭제됨
        2. voice_client가 있으면 disconnect가 호출되고 "🛑 노래 재생을 중지합니다." 메시지가 전송됨
        3. voice_client가 없으면 아무 메시지도 전송되지 않음
        """
        cog = MusicCog(MagicMock())
        voice_client = voice_client_factory() if has_voice_client else None

        with patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.guild_music_queues", {1: [{"title": "t"}]}) as mock_queues:
            await cog.stop.callback(cog, mock_ctx)

        assert 1 not in mock_queues
        if has_voice_client:
            voice_client.disconnect.assert_called_once()
            mock_ctx.send.assert_called_once_with("🛑 노래 재생을 중지합니다.")
        else:
            mock_ctx.send.assert_not_called()


class TestCogPause:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state",
        ["idle", "none"],
        ids=["not_playing", "no_voice_client"],
    )
    async def test_not_playing_only_sends_guidance(self, mock_ctx, voice_client_factory, state):
        """[목적] 재생 중이 아닐 때 pause가 안내 메시지만 전송하는지 검증

        [검증]
        1. "❌ 재생 중인 노래가 없습니다." 메시지가 전송됨
        2. voice_client.pause가 호출되지 않고 타임아웃 태스크도 등록되지 않음
        """
        cog = MusicCog(MagicMock())
        voice_client = voice_client_factory() if state == "idle" else None

        with patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.guild_pause_tasks", {}) as mock_tasks:
            await cog.pause.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_once_with("❌ 재생 중인 노래가 없습니다.")
        if voice_client:
            voice_client.pause.assert_not_called()
        assert mock_tasks == {}

    @pytest.mark.asyncio
    async def test_playing_pauses_and_registers_timeout_task(self, mock_ctx, voice_client_factory):
        """[목적] 재생 중 pause 시 일시정지와 타임아웃 태스크 등록이 이뤄지는지 검증

        [검증]
        1. voice_client.pause가 호출됨
        2. guild_pause_tasks에 길드 태스크가 등록되고 _pause_timeout이 올바른 인자로 생성됨
        3. 안내 메시지가 전송됨
        """
        cog = MusicCog(MagicMock())
        voice_client = voice_client_factory(is_playing=True)
        sentinel_task = MagicMock()

        def fake_create_task(coro):
            coro.close()
            return sentinel_task

        with patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.guild_pause_tasks", {}) as mock_tasks, \
                patch("bot.music._pause_timeout", new=MagicMock(return_value=AsyncMock()())) as mock_timeout, \
                patch("bot.music.asyncio.create_task", side_effect=fake_create_task):
            await cog.pause.callback(cog, mock_ctx)

        voice_client.pause.assert_called_once()
        mock_timeout.assert_called_once_with(mock_ctx, 1, voice_client)
        assert mock_tasks[1] is sentinel_task
        mock_ctx.send.assert_called_once_with("⏸️ 일시정지합니다. 20분 안에 !resume 하지 않으면 재생을 종료합니다.")

    @pytest.mark.asyncio
    async def test_repause_cancels_existing_task(self, mock_ctx, voice_client_factory):
        """[목적] 이미 대기 중인 타임아웃 태스크가 있을 때 재-pause 시 기존 태스크를 취소하고 교체하는지 검증

        [검증]
        1. 기존 태스크의 cancel이 호출됨
        2. guild_pause_tasks의 길드 태스크가 새 태스크로 교체됨
        """
        cog = MusicCog(MagicMock())
        voice_client = voice_client_factory(is_playing=True)
        old_task = MagicMock()
        new_task = MagicMock()

        def fake_create_task(coro):
            coro.close()
            return new_task

        with patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.guild_pause_tasks", {1: old_task}) as mock_tasks, \
                patch("bot.music.asyncio.create_task", side_effect=fake_create_task):
            await cog.pause.callback(cog, mock_ctx)

        old_task.cancel.assert_called_once()
        assert mock_tasks[1] is new_task


class TestCogResume:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state",
        ["playing", "none"],
        ids=["not_paused", "no_voice_client"],
    )
    async def test_not_paused_only_sends_guidance(self, mock_ctx, voice_client_factory, state):
        """[목적] 일시정지 상태가 아닐 때 resume이 안내 메시지만 전송하는지 검증

        [검증]
        1. "❌ 일시정지 상태가 아닙니다." 메시지가 전송됨
        2. voice_client.resume이 호출되지 않고 기존 태스크도 취소되지 않음
        """
        cog = MusicCog(MagicMock())
        voice_client = voice_client_factory(is_playing=True) if state == "playing" else None
        task = MagicMock()

        with patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.guild_pause_tasks", {1: task}):
            await cog.resume.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_once_with("❌ 일시정지 상태가 아닙니다.")
        if voice_client:
            voice_client.resume.assert_not_called()
        task.cancel.assert_not_called()

    @pytest.mark.asyncio
    async def test_paused_resumes_and_cancels_task(self, mock_ctx, voice_client_factory):
        """[목적] 일시정지 중 resume 시 재생 재개와 타임아웃 태스크 취소가 이뤄지는지 검증

        [검증]
        1. 타임아웃 태스크가 cancel되고 guild_pause_tasks에서 제거됨
        2. voice_client.resume이 호출됨
        3. "▶️ 다시 재생합니다." 메시지가 전송됨
        """
        cog = MusicCog(MagicMock())
        voice_client = voice_client_factory(is_paused=True)
        task = MagicMock()

        with patch("discord.utils.get", return_value=voice_client), \
                patch("bot.music.guild_pause_tasks", {1: task}) as mock_tasks:
            await cog.resume.callback(cog, mock_ctx)

        task.cancel.assert_called_once()
        assert 1 not in mock_tasks
        voice_client.resume.assert_called_once()
        mock_ctx.send.assert_called_once_with("▶️ 다시 재생합니다.")


class TestPauseTimeout:
    @pytest.mark.asyncio
    async def test_still_paused_clears_queue_and_disconnects(self, mock_ctx, voice_client_factory):
        """[목적] 타임아웃 시점에도 일시정지 상태면 재생이 종료되는지 검증

        [검증]
        1. PAUSE_TIMEOUT_SEC 만큼 sleep함
        2. guild_pause_tasks에서 제거되고 대기열이 삭제됨
        3. disconnect 호출 및 종료 안내 메시지 전송
        """
        voice_client = voice_client_factory(is_paused=True)

        with patch("bot.music.asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
                patch("bot.music.guild_pause_tasks", {1: MagicMock()}) as mock_tasks, \
                patch("bot.music.guild_music_queues", {1: [{"title": "t"}]}) as mock_queues:
            await _pause_timeout(mock_ctx, 1, voice_client)

        mock_sleep.assert_called_once_with(PAUSE_TIMEOUT_SEC)
        assert 1 not in mock_tasks
        assert 1 not in mock_queues
        voice_client.disconnect.assert_called_once()
        mock_ctx.send.assert_called_once_with("⏹️ 일시정지가 너무 길어 재생을 종료합니다.")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "is_connected, is_paused",
        [(True, False), (False, True)],
        ids=["already_resumed", "disconnected"],
    )
    async def test_no_action_when_not_paused_or_disconnected(self, mock_ctx, voice_client_factory, is_connected, is_paused):
        """[목적] 이미 resume되었거나 연결이 끊긴 경우 타임아웃이 아무 일도 하지 않는지 검증

        [검증]
        1. guild_pause_tasks에서는 제거됨
        2. 대기열이 유지되고 disconnect/메시지 전송이 일어나지 않음
        """
        voice_client = voice_client_factory(is_connected=is_connected, is_paused=is_paused)

        with patch("bot.music.asyncio.sleep", new_callable=AsyncMock), \
                patch("bot.music.guild_pause_tasks", {1: MagicMock()}) as mock_tasks, \
                patch("bot.music.guild_music_queues", {1: [{"title": "t"}]}) as mock_queues:
            await _pause_timeout(mock_ctx, 1, voice_client)

        assert 1 not in mock_tasks
        assert mock_queues == {1: [{"title": "t"}]}
        voice_client.disconnect.assert_not_called()
        mock_ctx.send.assert_not_called()


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
