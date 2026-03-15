import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()


def get_expected_env_path() -> Path:
    return BASE_DIR / ".env"


def load_app_env() -> Path | None:
    env_path = get_expected_env_path()

    if not env_path.exists():
        return None

    load_dotenv(env_path, override=True)
    return env_path


ENV_FILE_PATH = load_app_env()


DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

APP_STATE_FILE = DATA_DIR / "app_state.json"

TTS_AUDIO_DIR = DATA_DIR / "tts_audio"
TTS_AUDIO_DIR.mkdir(exist_ok=True)

TTS_CONFIG_FILE = DATA_DIR / "tts_config.json"


TOKEN_CACHE_FILE = DATA_DIR / "twitch_token.json"

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "").strip()
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "").strip()
TWITCH_REDIRECT_URI = os.getenv("TWITCH_REDIRECT_URI", "").strip()

TWITCH_CHANNEL = os.getenv("TWITCH_CHANNEL", "").strip().lower()

TWITCH_BOT_CLIENT_ID = os.getenv("TWITCH_BOT_CLIENT_ID", "").strip() or TWITCH_CLIENT_ID
TWITCH_BOT_CLIENT_SECRET = os.getenv("TWITCH_BOT_CLIENT_SECRET", "").strip() or TWITCH_CLIENT_SECRET
TWITCH_BOT_REDIRECT_URI = os.getenv("TWITCH_BOT_REDIRECT_URI", "").strip() or TWITCH_REDIRECT_URI
TWITCH_BOT_LOGIN = os.getenv("TWITCH_BOT_LOGIN", "").strip().lower()
TWITCH_BOT_ACCESS_TOKEN = os.getenv("TWITCH_BOT_ACCESS_TOKEN", "").strip()
TWITCH_BOT_REFRESH_TOKEN = os.getenv("TWITCH_BOT_REFRESH_TOKEN", "").strip()

TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/authorize"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"

TWITCH_SCOPES = [
    "chat:read",
    "chat:edit",
]

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6697


YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
YOUTUBE_REDIRECT_URI = os.getenv("YOUTUBE_REDIRECT_URI", "").strip()

YOUTUBE_TOKEN_CACHE_FILE = DATA_DIR / "youtube_token.json"
YOUTUBE_CONFIG_FILE = DATA_DIR / "youtube_config.json"
YOUTUBE_MESSAGE_STORE_FILE = DATA_DIR / "youtube_messages.json"


AWS_REGION = os.getenv("AWS_REGION", "").strip()
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()

POLLY_VOICE_ID = os.getenv("POLLY_VOICE_ID", "Camila").strip()
POLLY_ENGINE = os.getenv("POLLY_ENGINE", "neural").strip()
POLLY_OUTPUT_FORMAT = os.getenv("POLLY_OUTPUT_FORMAT", "mp3").strip()
POLLY_SAMPLE_RATE = os.getenv("POLLY_SAMPLE_RATE", "24000").strip()


def validate_local_config(require_twitch: bool = False):
    if not require_twitch:
        return

    if not TWITCH_CLIENT_ID:
        raise RuntimeError("Defina TWITCH_CLIENT_ID no arquivo .env")

    if not TWITCH_CLIENT_SECRET:
        raise RuntimeError("Defina TWITCH_CLIENT_SECRET no arquivo .env")

    if not TWITCH_REDIRECT_URI:
        raise RuntimeError("Defina TWITCH_REDIRECT_URI no arquivo .env")


def has_twitch_bot_sender_config() -> bool:
    return bool(
        TWITCH_BOT_LOGIN
        and TWITCH_BOT_ACCESS_TOKEN
        and TWITCH_BOT_CLIENT_ID
        and TWITCH_BOT_CLIENT_SECRET
    )


def validate_required_env_values() -> None:
    if ENV_FILE_PATH is None:
        raise RuntimeError(
            "Arquivo .env nao encontrado. Coloque o .env na mesma pasta do TTSLive.exe."
        )

    missing = []

    if not AWS_REGION:
        missing.append("AWS_REGION")
    if not AWS_ACCESS_KEY_ID:
        missing.append("AWS_ACCESS_KEY_ID")
    if not AWS_SECRET_ACCESS_KEY:
        missing.append("AWS_SECRET_ACCESS_KEY")

    if missing:
        raise RuntimeError(
            "Variaveis ausentes no .env: "
            + ", ".join(missing)
            + ". Coloque o arquivo .env na mesma pasta do TTSLive.exe."
        )


def build_env_help_message() -> str:
    loaded = str(ENV_FILE_PATH) if ENV_FILE_PATH else "nenhum .env encontrado"
    env_path = get_expected_env_path()

    return (
        "Nao foi possivel carregar corretamente o arquivo .env.\n\n"
        f".env carregado: {loaded}\n\n"
        "Local esperado:\n"
        f"- {env_path}\n\n"
        "Coloque o arquivo .env na mesma pasta do TTSLive.exe."
    )
