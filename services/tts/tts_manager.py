import threading
import time
from concurrent.futures import ThreadPoolExecutor

from config import TTS_AUDIO_DIR, TTS_CONFIG_FILE

from services.tts.tts_state import TTSState
from services.tts.tts_config_store import TTSConfigStore
from services.tts.polly_client import PollyClient
from services.tts.audio_player import AudioPlayer
from services.tts.text_sanitizer import sanitize_chat_text, build_tts_text


class TTSManager:

    def __init__(self):

        self.config_store = TTSConfigStore(TTS_CONFIG_FILE)
        config_data = self.config_store.load()

        self.state = TTSState.from_persisted_dict(config_data)

        self.polly = PollyClient(TTS_AUDIO_DIR)
        self.player = AudioPlayer(TTS_AUDIO_DIR, rate_seconds=self.state.rate_seconds)
        self._synth_executor = ThreadPoolExecutor(
            max_workers=3,
            thread_name_prefix="TTSSynth",
        )

        self.lock = threading.Lock()

        # sera injetado pelo app.py
        self.youtube_bot = None

        self.player.start()

    # ==================================
    # Entrada principal
    # ==================================

    def handle_message(self, payload: dict):

        text = payload.get("message", "")

        if not text.startswith("!"):
            return

        parts = text.split(" ", 1)
        command = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        platform = payload.get("platform")

        # ===============================
        # UNIVERSAL
        # ===============================

        if command == "!ms":
            self._handle_ms(payload, rest)
            return

        # ===============================
        # RESTANTE SOMENTE TWITCH
        # ===============================

        if platform != "twitch":
            return

        # ===============================
        # SOMENTE ADMIN
        # ===============================

        if not self._is_admin(payload):
            return

        # ===============================
        # COMANDOS YOUTUBE VIA TWITCH
        # ===============================

        if command == "!lives":
            self._handle_lives(payload)
            return

        if command == "!ytoff":
            self._handle_ytoff(payload)
            return

        if command.startswith("!live") and command != "!lives":
            self._handle_live_switch(payload, command)
            return

        if command.startswith("!clive"):
            self._handle_clive(payload, command)
            return

        # ===============================
        # COMANDOS TTS
        # ===============================

        if command == "!mm":
            self._handle_mm(payload, rest)

        elif command == "!rate":
            self._handle_rate(payload, rest)

        elif command == "!time":
            self._handle_time(payload, rest)

        elif command == "!pause":
            self._handle_pause(payload)

        elif command == "!stop":
            self._handle_stop(payload)

        elif command == "!resume":
            self._handle_resume(payload)

        elif command == "!len":
            self._handle_len(payload, rest)

        elif command == "!modosub":
            self._handle_modosub(payload)

        elif command == "!config":
            self._handle_config(payload)

    # ==================================
    # Helpers
    # ==================================

    def _is_admin(self, payload):

        return (
            payload.get("is_mod", False)
            or payload.get("is_broadcaster", False)
        )

    def _reply(self, payload, text):

        send = payload.get("send_chat")

        if send:
            try:
                send(text)
            except Exception as e:
                print("[TTS] erro enviando chat:", e)

    def _save_config(self):

        self.config_store.save(self.state.to_persisted_dict())

    def _parse_display_index_from_command(self, command: str, prefix: str) -> int | None:
        value = command[len(prefix):].strip()

        if not value.isdigit():
            return None

        index = int(value)

        if index <= 0:
            return None

        return index

    def _parse_positive_float(self, value: str, allow_zero: bool = False) -> float | None:
        try:
            parsed = round(float(value), 1)
        except (TypeError, ValueError) as exc:
            print(f"[TTS] valor numerico invalido: {value!r} ({exc})")
            return None

        if parsed < 0 or (parsed == 0 and not allow_zero):
            return None

        return parsed

    def _parse_positive_int(self, value: str) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            print(f"[TTS] valor inteiro invalido: {value!r} ({exc})")
            return None

        if parsed <= 0:
            return None

        return parsed

    # ==================================
    # !ms
    # ==================================

    def _handle_ms(self, payload, message):

        if self.state.stopped:
            return

        if self.state.mode_sub_only and not (
            payload.get("is_sub")
            or payload.get("is_mod")
            or payload.get("is_broadcaster")
        ):
            return

        username = payload.get("username")
        now = time.time()

        ok, _remaining = self.state.can_user_send_audio(username, now)

        if not ok:
            return

        text, _ = sanitize_chat_text(
            message,
            max_words=self.state.max_words,
        )

        if not text:
            return

        tts_text = build_tts_text(payload.get("display_name", "usuario"), text)

        self._queue_audio(tts_text, priority=False)

        self.state.mark_user_audio_time(username, now)

    # ==================================
    # !mm
    # ==================================

    def _handle_mm(self, payload, message):

        if self.state.stopped:
            return

        text, _ = sanitize_chat_text(
            message,
            max_words=self.state.max_words,
        )

        if not text:
            return

        tts_text = build_tts_text(payload.get("display_name", "usuario"), text)

        self._queue_audio(tts_text, priority=True)

    # ==================================
    # Comandos YouTube via Twitch
    # ==================================

    def _handle_lives(self, payload):
        youtube_bot = getattr(self, "youtube_bot", None)

        if not youtube_bot:
            self._reply(payload, "YouTube bot nao esta disponivel.")
            return

        lines = youtube_bot.list_accounts_summary_lines()

        if not lines:
            self._reply(payload, "Nenhuma conta do YouTube salva.")
            return

        message = " | ".join(lines)
        self._reply(payload, message[:450])

    def _handle_live_switch(self, payload, command):
        youtube_bot = getattr(self, "youtube_bot", None)

        if not youtube_bot:
            self._reply(payload, "YouTube bot nao esta disponivel.")
            return

        display_index = self._parse_display_index_from_command(command, "!live")
        if display_index is None:
            self._reply(payload, "Uso: !live1, !live2, !live3...")
            return

        ok = youtube_bot.activate_account_by_display_index(display_index)

        if not ok:
            self._reply(payload, f"Live {display_index} nao encontrada.")
            return

        self._reply(payload, f"Monitoramento alterado para live {display_index}.")

    def _handle_ytoff(self, payload):
        youtube_bot = getattr(self, "youtube_bot", None)

        if not youtube_bot:
            self._reply(payload, "YouTube bot nao esta disponivel.")
            return

        youtube_bot.disable_monitoring()
        self._reply(payload, "Monitoramento do YouTube desligado.")

    def _handle_clive(self, payload, command):
        youtube_bot = getattr(self, "youtube_bot", None)

        if not youtube_bot:
            self._reply(payload, "YouTube bot nao esta disponivel.")
            return

        display_index = self._parse_display_index_from_command(command, "!clive")
        if display_index is None:
            self._reply(payload, "Uso: !clive1, !clive2, !clive3...")
            return

        ok = youtube_bot.remove_account_by_display_index(display_index)

        if not ok:
            self._reply(payload, f"Live {display_index} nao encontrada para remover.")
            return

        remaining = youtube_bot.list_accounts_summary_lines()

        if not remaining:
            self._reply(payload, f"Live {display_index} removida. Nenhuma conta do YouTube restante.")
            return

        self._reply(payload, f"Live {display_index} removida com sucesso.")

    # ==================================
    # Comandos administrativos TTS
    # ==================================

    def _handle_rate(self, payload, arg):
        value = self._parse_positive_float(arg)
        if value is None:
            return

        self.state.rate_seconds = value
        self.player.set_rate(value)

        self._save_config()

        msg = f"Rate alterado para {value}s"

        print("[TTS]", msg)

        self._reply(payload, msg)

    def _handle_time(self, payload, arg):
        value = self._parse_positive_float(arg, allow_zero=True)
        if value is None:
            return

        self.state.user_cooldown_seconds = value

        self._save_config()

        msg = f"Cooldown entre usuarios alterado para {value}s"

        print("[TTS]", msg)

        self._reply(payload, msg)

    def _handle_len(self, payload, arg):
        value = self._parse_positive_int(arg)
        if value is None:
            return

        self.state.max_words = value

        self._save_config()

        msg = f"Limite de palavras alterado para {value}"

        print("[TTS]", msg)

        self._reply(payload, msg)

    def _handle_pause(self, payload):

        self.state.paused = True
        self.player.pause()

        msg = "Player pausado"

        print("[TTS]", msg)

        self._reply(payload, msg)

    def _handle_stop(self, payload):

        self.state.stopped = True
        self.state.paused = False

        self.player.stop()

        msg = "Fila limpa e player parado"

        print("[TTS]", msg)

        self._reply(payload, msg)

    def _handle_resume(self, payload):

        self.state.paused = False
        self.state.stopped = False

        self.player.resume()

        msg = "Player retomado"

        print("[TTS]", msg)

        self._reply(payload, msg)

    def _handle_modosub(self, payload):

        self.state.mode_sub_only = not self.state.mode_sub_only

        self._save_config()

        status = "ON" if self.state.mode_sub_only else "OFF"

        msg = f"Modo sub agora {status}"

        print("[TTS]", msg)

        self._reply(payload, msg)

    def _handle_config(self, payload):

        msg = (
            f"Config: modosub={self.state.mode_sub_only} | "
            f"rate={self.state.rate_seconds}s | "
            f"time={self.state.user_cooldown_seconds}s | "
            f"len={self.state.max_words}"
        )

        print("[TTS CONFIG]", msg)

        self._reply(payload, msg)

    # ==================================
    # Fila de audio
    # ==================================

    def _queue_audio(self, text, priority=False):

        def worker():

            try:

                audio_path = self.polly.synthesize(text)
                self.player.enqueue(audio_path, priority=priority)

            except Exception as e:

                print("[TTS] erro gerando audio:", e)

        try:
            self._synth_executor.submit(worker)
        except RuntimeError:
            pass

    # ==================================
    # Shutdown
    # ==================================

    def shutdown(self):

        try:
            self._synth_executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self._synth_executor.shutdown(wait=False)

        self.player.shutdown()
