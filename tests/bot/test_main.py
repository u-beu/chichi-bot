import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_dotenv_loaded_before_bot_modules_read_env(tmp_path):
    """[목적] main import 시 .env 값이 bot 모듈의 모듈 레벨 os.getenv에 반영되는지 검증

    [검증]
    1. .env에만 지정한 BOT_QUEUE_KEY가 bot.subscriber.BOT_QUEUE_KEY에 반영됨
    """
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_QUEUE_KEY=from-dotenv\n")
    # load_dotenv()는 main.py 위치 기준으로 .env를 찾으므로, 테스트용 .env를 읽도록 대체
    code = (
        f"import sys; sys.path.insert(0, {str(ROOT)!r}); "
        "import dotenv; _orig = dotenv.load_dotenv; "
        f"dotenv.load_dotenv = lambda *a, **k: _orig({str(env_file)!r}); "
        "import main; import bot.subscriber as s; print(s.BOT_QUEUE_KEY)"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )

    assert result.stdout.strip().splitlines()[-1] == "from-dotenv"
