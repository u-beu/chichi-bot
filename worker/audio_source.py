import logging

import yt_dlp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'noplaylist': True,
    'extract_audio': True,
    # 'web' 클라이언트 단독으로는 YouTube가 SABR 스트리밍을 강제해 직접 URL이 아예 안 나오거나,
    # 나온 URL도 ffmpeg 등 외부 클라이언트로 요청 시 403이 발생. android 클라이언트를 우선 시도해야
    # ffmpeg/librosa가 바로 읽을 수 있는 URL을 받는다.
    'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
}


class AudioSourceError(Exception):
    """yt-dlp로 스트리밍 소스 URL 추출에 실패했을 때 발생."""


def get_audio_source_url(video_id: str) -> str:
    """videoId로 유튜브 워치 URL을 구성해 yt-dlp로 분석용 스트리밍 오디오 URL만 추출."""
    webpage_url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(webpage_url, download=False)
            if 'entries' in info:
                info = info['entries'][0]
            return info['url']
    except Exception as e:
        raise AudioSourceError(f"오디오 소스 추출 실패: videoId={video_id}") from e
