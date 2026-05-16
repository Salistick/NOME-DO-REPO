import os
import math
import threading
import time
import uuid
import wave
from pathlib import Path
import queue

if os.name == "nt":
    os.environ.setdefault("SDL_AUDIODRIVER", "directsound")

import pygame


class AudioPlayer:

    def __init__(
        self,
        audio_dir: Path,
        rate_seconds: float = 2.5,
        output_device_name: str = "",
    ):
        self.audio_dir = Path(audio_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.rate_seconds = rate_seconds
        self.output_device_name = (output_device_name or "").strip()

        self.queue: queue.Queue[Path] = queue.Queue()
        self.priority_queue: queue.Queue[Path] = queue.Queue()

        self.paused = False
        self.stopped = False

        self._thread = None
        self._running = False
        self._mixer_lock = threading.RLock()
        self._output_devices = self.list_output_devices()

        self._init_mixer(self.output_device_name)

        self._cleanup_audio_dir()

    @staticmethod
    def list_output_devices() -> list[str]:
        try:
            from pygame._sdl2 import INIT_AUDIO, init_subsystem
            import pygame._sdl2.audio as sdl_audio

            init_subsystem(INIT_AUDIO)
            names = sdl_audio.get_audio_device_names(False)
        except Exception as exc:
            print(f"[TTS] nao foi possivel listar saidas de audio: {exc}")
            return []

        devices = []
        seen = set()

        for name in names or []:
            clean = str(name or "").strip()
            if not clean or clean in seen:
                continue
            devices.append(clean)
            seen.add(clean)

        return devices

    def get_output_device_name(self) -> str:
        return self.output_device_name

    def get_output_devices(self) -> list[str]:
        return list(self._output_devices)

    def refresh_output_devices(self) -> list[str]:
        current_device = self.output_device_name
        self.clear_queue()

        with self._mixer_lock:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

            try:
                pygame.mixer.music.unload()
            except Exception:
                pass

            try:
                pygame.mixer.quit()
            except Exception:
                pass

            self._output_devices = self.list_output_devices()

            if current_device and current_device not in self._output_devices:
                current_device = ""

            self._init_mixer(current_device)

        return self.get_output_devices()

    def set_output_device(self, output_device_name: str) -> str:
        self.clear_queue()
        self._init_mixer((output_device_name or "").strip())
        return self.output_device_name

    def play_test_tone(self) -> Path:
        audio_file = self.audio_dir / f"audio_test_{uuid.uuid4()}.wav"
        self._write_test_tone(audio_file)
        self.enqueue(audio_file, priority=True, bypass_state=True)
        return audio_file

    def _init_mixer(self, output_device_name: str = ""):
        output_device_name = (output_device_name or "").strip()

        with self._mixer_lock:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

            try:
                pygame.mixer.music.unload()
            except Exception:
                pass

            try:
                pygame.mixer.quit()
            except Exception:
                pass

            try:
                if output_device_name:
                    pygame.mixer.init(devicename=output_device_name)
                else:
                    pygame.mixer.init()
                self.output_device_name = output_device_name
                return
            except Exception as exc:
                if not output_device_name:
                    raise

                print(
                    "[TTS] falha ao iniciar saida de audio "
                    f"{output_device_name!r}: {exc}. Usando padrao do sistema."
                )
                pygame.mixer.init()
                self.output_device_name = ""

    # ==========================
    # Controle da fila
    # ==========================

    def enqueue(self, audio_file: Path, priority: bool = False, bypass_state: bool = False):
        if self.stopped and not bypass_state:
            return

        if priority:
            self.priority_queue.put(audio_file)
            return

        self.queue.put(audio_file)

    def queue_length(self):
        return self.priority_queue.qsize() + self.queue.qsize()

    def clear_queue(self):
        self._drain_queue(self.priority_queue)
        self._drain_queue(self.queue)

    # ==========================
    # Controle de estado
    # ==========================

    def set_rate(self, seconds: float):
        self.rate_seconds = seconds

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False
        self.stopped = False

    def stop(self):
        self.stopped = True
        self.paused = False
        self.clear_queue()

        try:
            with self._mixer_lock:
                pygame.mixer.music.stop()
        except Exception:
            pass

    # ==========================
    # Loop principal
    # ==========================

    def start(self):

        if self._running:
            return

        self._running = True

        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
        )

        self._thread.start()

    def shutdown(self):

        self._running = False

        try:
            with self._mixer_lock:
                pygame.mixer.music.stop()
        except Exception:
            pass

    def _run(self):

        while self._running:

            if (self.paused or self.stopped) and self.priority_queue.empty():
                time.sleep(0.1)
                continue

            try:
                audio_file = self.priority_queue.get_nowait()
            except queue.Empty:
                try:
                    audio_file = self.queue.get(timeout=0.2)
                except queue.Empty:
                    continue

            try:
                with self._mixer_lock:
                    pygame.mixer.music.load(str(audio_file))
                    pygame.mixer.music.play()

                while self._is_music_busy():
                    time.sleep(0.05)

            except Exception as exc:
                print(f"[TTS] erro ao tocar audio: {exc}")

            finally:
                try:
                    with self._mixer_lock:
                        pygame.mixer.music.unload()
                except Exception:
                    pass
                self._safe_delete(audio_file)

            self._sleep_between_items()

    # ==========================
    # Limpeza segura
    # ==========================

    def _safe_delete(self, path: Path):

        for _ in range(5):
            try:
                if path.exists():
                    path.unlink()
                return
            except PermissionError:
                time.sleep(0.2)

    def _drain_queue(self, q: queue.Queue[Path]):
        while not q.empty():
            try:
                audio_file = q.get_nowait()
            except queue.Empty:
                break
            self._safe_delete(audio_file)

    def _sleep_between_items(self):
        slept = 0.0

        while slept < self.rate_seconds and self._running:
            if not self.priority_queue.empty():
                return

            step = min(0.1, self.rate_seconds - slept)
            time.sleep(step)
            slept += step

    def _is_music_busy(self) -> bool:
        try:
            with self._mixer_lock:
                return bool(pygame.mixer.music.get_busy())
        except Exception:
            return False

    def _write_test_tone(self, path: Path):
        sample_rate = 44100
        duration_seconds = 0.45
        frequency = 880
        amplitude = 0.22
        total_samples = int(sample_rate * duration_seconds)
        fade_samples = max(1, int(sample_rate * 0.03))

        frames = bytearray()

        for i in range(total_samples):
            envelope = 1.0
            if i < fade_samples:
                envelope = i / fade_samples
            elif i > total_samples - fade_samples:
                envelope = max(0.0, (total_samples - i) / fade_samples)

            sample = int(
                32767
                * amplitude
                * envelope
                * math.sin(2 * math.pi * frequency * i / sample_rate)
            )
            frames += sample.to_bytes(2, "little", signed=True)

        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(frames)

    def _cleanup_audio_dir(self):

        for file in self.audio_dir.glob("*"):
            try:
                file.unlink()
            except Exception:
                pass
