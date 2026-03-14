import uuid
from pathlib import Path

import boto3

from config import (
    AWS_REGION,
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    POLLY_VOICE_ID,
    POLLY_ENGINE,
    POLLY_OUTPUT_FORMAT,
    POLLY_SAMPLE_RATE,
)


class PollyClient:

    def __init__(self, audio_dir: Path):
        self.audio_dir = Path(audio_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)

        self.client = boto3.client(
            "polly",
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )

    def synthesize(self, text: str) -> Path:
        """
        Gera um arquivo de áudio usando Polly e retorna o caminho.
        """

        filename = f"{uuid.uuid4()}.{POLLY_OUTPUT_FORMAT}"
        output_path = self.audio_dir / filename

        response = self.client.synthesize_speech(
            Text=text,
            VoiceId=POLLY_VOICE_ID,
            Engine=POLLY_ENGINE,
            OutputFormat=POLLY_OUTPUT_FORMAT,
            SampleRate=POLLY_SAMPLE_RATE,
        )

        audio_stream = response.get("AudioStream")

        if not audio_stream:
            raise RuntimeError("Polly não retornou áudio.")

        with open(output_path, "wb") as f:
            f.write(audio_stream.read())

        return output_path