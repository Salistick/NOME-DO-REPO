import threading
import time
import queue
from dataclasses import dataclass, field

from config import TTS_AUDIO_DIR, TTS_CONFIG_FILE

from services.tts.tts_state import PlatformTTSConfig, TTSState, normalize_tts_platform
from services.tts.tts_config_store import TTSConfigStore
from services.tts.polly_client import PollyClient
from services.tts.audio_player import AudioPlayer
from services.tts.text_sanitizer import sanitize_chat_text, build_tts_text
from services.tts.command_rules import (
    can_use_sub_only,
    is_admin,
    normalized_role,
    payload_bool,
    resolve_command_type,
)


@dataclass(order=True)
class _SynthTask:
    priority_rank: int
    sequence: int
    text: str = field(compare=False)
    player_priority: bool = field(compare=False, default=False)
    bypass_state: bool = field(compare=False, default=False)


class TTSManager:

    def __init__(self):

        self.config_store = TTSConfigStore(TTS_CONFIG_FILE)
        config_data = self.config_store.load()

        self.state = TTSState.from_persisted_dict(config_data)

        self.polly = PollyClient(TTS_AUDIO_DIR)
        self.player = AudioPlayer(
            TTS_AUDIO_DIR,
            rate_seconds=self.state.rate_seconds,
            output_device_name=self.state.audio_output_device,
        )

        active_audio_device = self.player.get_output_device_name()
        if active_audio_device != self.state.audio_output_device:
            self.state.audio_output_device = active_audio_device
            self._save_config()

        self.lock = threading.Lock()
        self._synth_queue: queue.PriorityQueue[_SynthTask] = queue.PriorityQueue()
        self._synth_sequence = 0
        self._synth_running = True
        self._synth_thread = threading.Thread(
            target=self._run_synth_queue,
            name="TTSSynthQueue",
            daemon=True,
        )

        # sera injetado pelo app.py
        self.youtube_bot = None

        self.player.start()
        self._synth_thread.start()

    # ==================================
    # Saida de audio
    # ==================================

    def list_audio_output_devices(self) -> list[str]:
        return self.player.get_output_devices()

    def refresh_audio_output_devices(self) -> list[str]:
        devices = self.player.refresh_output_devices()
        active_device = self.player.get_output_device_name()

        if active_device != self.state.audio_output_device:
            self.state.audio_output_device = active_device
            self._save_config()

        return devices

    def get_audio_output_device(self) -> str:
        return self.state.audio_output_device

    def set_audio_output_device(self, output_device_name: str) -> tuple[bool, str]:
        output_device_name = (output_device_name or "").strip()
        devices = self.list_audio_output_devices()

        if output_device_name and devices and output_device_name not in devices:
            return False, "Saida de audio nao encontrada no sistema."

        try:
            active_device = self.player.set_output_device(output_device_name)
        except Exception as exc:
            return False, str(exc)

        self.state.audio_output_device = active_device
        self._save_config()

        if output_device_name and active_device != output_device_name:
            return False, "Nao foi possivel iniciar essa saida. O bot voltou para o padrao do sistema."

        return True, ""

    def play_audio_test(self) -> tuple[bool, str]:
        try:
            self.player.play_test_tone()
            return True, ""
        except Exception as exc:
            return False, str(exc)

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

        command_type = self._resolve_command_type(command)
        if not command_type:
            return

        if command_type == "public_tts":
            self._handle_ms(payload, rest)
            return

        if not self._is_admin(payload):
            return

        print(
            f"[TTS ADMIN] plataforma={payload.get('platform', '')} "
            f"comando={command} usuario={payload.get('display_name', '')} "
            f"canal={payload.get('channel', '')}"
        )

        # ===============================
        # COMANDOS YOUTUBE
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

    def _resolve_command_type(self, command: str) -> str | None:
        return resolve_command_type(command)

    def _is_admin(self, payload):
        return is_admin(payload)

    def _can_use_sub_only(self, payload):
        return can_use_sub_only(payload)

    def _normalized_role(self, payload) -> str:
        return normalized_role(payload)

    def _payload_bool(self, payload, key: str) -> bool:
        return payload_bool(payload, key)

    def _platform_key(self, payload) -> str:
        return normalize_tts_platform((payload or {}).get("platform", ""))

    def _platform_config(self, payload) -> PlatformTTSConfig:
        return self.state.get_platform_config(self._platform_key(payload))

    def _platform_label(self, payload) -> str:
        platform = self._platform_key(payload)
        if platform in {"twitch", "youtube", "kick"}:
            return platform
        return platform or "desconhecida"

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
        platform = self._platform_key(payload)
        config = self._platform_config(payload)

        if self.state.stopped:
            return

        if config.mode_sub_only and not self._can_use_sub_only(payload):
            return

        username = payload.get("username")
        now = time.time()

        ok, _remaining = self.state.can_user_send_audio(username, platform, now)

        if not ok:
            return

        text, _ = sanitize_chat_text(
            message,
            max_words=config.max_words,
        )

        if not text:
            return

        tts_text = build_tts_text(payload.get("display_name", "usuario"), text)

        self._queue_audio(tts_text, priority=False)

        self.state.mark_user_audio_time(username, platform, now)

    # ==================================
    # !mm
    # ==================================

    def _handle_mm(self, payload, message):
        config = self._platform_config(payload)

        text, _ = sanitize_chat_text(
            message,
            max_words=config.max_words,
        )

        if not text:
            return

        tts_text = build_tts_text(payload.get("display_name", "usuario"), text)

        self._queue_audio(
            tts_text,
            priority=True,
            bypass_state=True,
        )

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
            self._reply(payload, "Uso: !rate 1.5")
            return

        self.state.rate_seconds = value
        self.player.set_rate(value)

        self._save_config()

        msg = f"Rate geral alterado para {value}s"

        print("[TTS]", msg)

        self._reply(payload, msg)

    def _handle_time(self, payload, arg):
        value = self._parse_positive_float(arg, allow_zero=True)
        if value is None:
            self._reply(payload, "Uso: !time 10")
            return

        config = self._platform_config(payload)
        config.user_cooldown_seconds = value

        self._save_config()

        msg = f"Cooldown {self._platform_label(payload)} alterado para {value}s"

        print("[TTS]", msg)

        self._reply(payload, msg)

    def _handle_len(self, payload, arg):
        value = self._parse_positive_int(arg)
        if value is None:
            self._reply(payload, "Uso: !len 20")
            return

        config = self._platform_config(payload)
        config.max_words = value

        self._save_config()

        msg = f"Limite de palavras {self._platform_label(payload)} alterado para {value}"

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

        self._clear_pending_audio_queue()
        self.player.stop()

        msg = "Fila limpa e player parado"

        print("[TTS]", msg)

        self._reply(payload, msg)

    def _handle_resume(self, payload):
        was_paused = self.state.paused or self.player.paused
        was_stopped = self.state.stopped or self.player.stopped

        if not was_paused and not was_stopped:
            msg = "Player nao esta pausado nem parado"

            print("[TTS]", msg)

            self._reply(payload, msg)
            return

        self.state.paused = False
        self.state.stopped = False

        self.player.resume()

        msg = "Player retomado"

        print("[TTS]", msg)

        self._reply(payload, msg)

    def _handle_modosub(self, payload):
        config = self._platform_config(payload)

        config.mode_sub_only = not config.mode_sub_only

        self._save_config()

        status = "ON" if config.mode_sub_only else "OFF"

        msg = f"Modo sub {self._platform_label(payload)} agora {status}"

        print("[TTS]", msg)

        self._reply(payload, msg)

    def _handle_config(self, payload):
        config = self._platform_config(payload)

        msg = (
            f"Config {self._platform_label(payload)}: "
            f"modosub={config.mode_sub_only} | "
            f"rate_geral={self.state.rate_seconds}s | "
            f"time={config.user_cooldown_seconds}s | "
            f"len={config.max_words}"
        )

        print("[TTS CONFIG]", msg)

        self._reply(payload, msg)

    # ==================================
    # Fila de audio
    # ==================================

    def _queue_audio(
        self,
        text,
        priority=False,
        bypass_state: bool = False,
    ):
        text = (text or "").strip()
        if not text:
            return

        with self.lock:
            self._synth_sequence += 1
            sequence = self._synth_sequence

        rank = 0 if priority else 1

        self._synth_queue.put(
            _SynthTask(
                priority_rank=rank,
                sequence=sequence,
                text=text,
                player_priority=priority,
                bypass_state=bypass_state,
            )
        )

    def _run_synth_queue(self):
        while self._synth_running:
            try:
                task = self._synth_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                audio_path = self.polly.synthesize(task.text)
                self.player.enqueue(
                    audio_path,
                    priority=task.player_priority,
                    bypass_state=task.bypass_state,
                )
            except Exception as e:
                print("[TTS] erro gerando audio:", e)
            finally:
                try:
                    self._synth_queue.task_done()
                except Exception:
                    pass

    def _clear_pending_audio_queue(self):
        while True:
            try:
                self._synth_queue.get_nowait()
                self._synth_queue.task_done()
            except queue.Empty:
                break
            except Exception:
                break

    # ==================================
    # Shutdown
    # ==================================

    def shutdown(self):

        self._synth_running = False
        self._clear_pending_audio_queue()

        self.player.shutdown()
