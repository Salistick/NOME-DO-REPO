import uuid
from contextlib import closing
from pathlib import Path

from botocore.exceptions import ClientError

from config import (
    AWS_POLLY_CONFIG_FILE,
    AWS_POLLY_SECRET_FILE,
    POLLY_ENGINE,
    POLLY_OUTPUT_FORMAT,
    POLLY_SAMPLE_RATE,
    POLLY_VOICE_ID,
)
from services.tts.polly_credentials import PollyCredentialStore
from services.tts.text_sanitizer import build_polly_ssml


class PollyClient:

    def __init__(self, audio_dir: Path):
        self.audio_dir = Path(audio_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)

        self.credential_store = PollyCredentialStore(AWS_POLLY_CONFIG_FILE, AWS_POLLY_SECRET_FILE)
        self.client = self._create_client()

    def _create_client(self):
        return self.credential_store.create_client()

    def synthesize(self, text: str) -> Path:
        """
        Gera um arquivo de áudio usando Polly e retorna o caminho.
        """

        ssml_text = build_polly_ssml(text)
        if not ssml_text:
            raise RuntimeError("Texto vazio para sintetizar.")

        filename = f"{uuid.uuid4()}.{POLLY_OUTPUT_FORMAT}"
        output_path = self.audio_dir / filename

        try:
            response = self._synthesize_speech(ssml_text)
        except ClientError as exc:
            if not self._is_retriable_credential_error(exc):
                raise
            self.client = self._create_client()
            response = self._synthesize_speech(ssml_text)

        audio_stream = response.get("AudioStream")

        if not audio_stream:
            raise RuntimeError("Polly não retornou áudio.")

        try:
            with closing(audio_stream), open(output_path, "wb") as f:
                f.writelines(iter(lambda: audio_stream.read(64 * 1024), b""))
        except Exception:
            output_path.unlink(missing_ok=True)
            raise

        return output_path

    def _synthesize_speech(self, ssml_text: str):
        return self.client.synthesize_speech(
            Text=ssml_text,
            TextType="ssml",
            VoiceId=POLLY_VOICE_ID,
            Engine=POLLY_ENGINE,
            OutputFormat=POLLY_OUTPUT_FORMAT,
            SampleRate=POLLY_SAMPLE_RATE,
        )

    @staticmethod
    def _is_retriable_credential_error(exc: ClientError) -> bool:
        code = exc.response.get("Error", {}).get("Code", "")
        return code in {
            "ExpiredToken",
            "ExpiredTokenException",
            "InvalidToken",
            "UnrecognizedClientException",
        }
