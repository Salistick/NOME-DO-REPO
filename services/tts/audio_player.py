import math
import os
import queue
import threading
import time
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path

if os.name == "nt":
    os.environ.setdefault("SDL_AUDIODRIVER", "directsound")

import pygame

MAX_PENDING_AUDIO = 100

AUDIO_PLAYER_RECOVERABLE_ERRORS = (
    RuntimeError,
    OSError,
    ValueError,
    TypeError,
    ImportError,
    pygame.error,
)


@dataclass
class _AudioTask:
    path: Path
    generation: int
    bypass_state: bool = False


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

        self.queue: queue.Queue[_AudioTask] = queue.Queue()
        self.priority_queue: queue.Queue[_AudioTask] = queue.Queue()
        self._generation = 0

        self.paused = False
        self.stopped = False

        self._thread = None
        self._running = False
        self._closed = False
        self._queue_lock = threading.Lock()
        self._mixer_lock = threading.RLock()
        self._output_devices = self.list_output_devices()

        self._init_mixer(self.output_device_name)

        self._cleanup_audio_dir()

    @staticmethod
    def list_output_devices() -> list[str]:
        try:
            import pygame._sdl2.audio as sdl_audio
            from pygame._sdl2 import INIT_AUDIO, init_subsystem

            init_subsystem(INIT_AUDIO)
            names = sdl_audio.get_audio_device_names(False)
        except AUDIO_PLAYER_RECOVERABLE_ERRORS as exc:
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
            except AUDIO_PLAYER_RECOVERABLE_ERRORS as exc:
                print(f"[TTS] falha ao parar mixer durante atualizacao: {exc}")

            try:
                pygame.mixer.music.unload()
            except AUDIO_PLAYER_RECOVERABLE_ERRORS as exc:
                print(f"[TTS] falha ao descarregar mixer durante atualizacao: {exc}")

            try:
                pygame.mixer.quit()
            except AUDIO_PLAYER_RECOVERABLE_ERRORS as exc:
                print(f"[TTS] falha ao reiniciar mixer durante atualizacao: {exc}")

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
            except AUDIO_PLAYER_RECOVERABLE_ERRORS as exc:
                print(f"[TTS] falha ao parar mixer: {exc}")

            try:
                pygame.mixer.music.unload()
            except AUDIO_PLAYER_RECOVERABLE_ERRORS as exc:
                print(f"[TTS] falha ao descarregar mixer: {exc}")

            try:
                pygame.mixer.quit()
            except AUDIO_PLAYER_RECOVERABLE_ERRORS as exc:
                print(f"[TTS] falha ao finalizar mixer: {exc}")

            try:
                if output_device_name:
                    pygame.mixer.init(devicename=output_device_name)
                else:
                    pygame.mixer.init()
                self.output_device_name = output_device_name
                return
            except AUDIO_PLAYER_RECOVERABLE_ERRORS as exc:
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

    def enqueue(self, audio_file: Path, priority: bool = False, bypass_state: bool = False) -> bool:
        audio_file = Path(audio_file)
        with self._queue_lock:
            if self._closed or (self.stopped and not bypass_state):
                self._safe_delete(audio_file)
                return False
            queue_limit = MAX_PENDING_AUDIO if priority else MAX_PENDING_AUDIO - 1
            if self.queue_length() >= queue_limit:
                print("[TTS] fila de reproducao cheia; audio descartado.")
                self._safe_delete(audio_file)
                return False
            target = self.priority_queue if priority else self.queue
            target.put_nowait(_AudioTask(audio_file, self._generation, bypass_state))
        return True

    def queue_length(self):
        return self.priority_queue.qsize() + self.queue.qsize()

    def clear_queue(self):
        with self._queue_lock:
            self._generation += 1
            self._drain_queue(self.priority_queue)
            self._drain_queue(self.queue)

    # ==========================
    # Controle de estado
    # ==========================

    def set_rate(self, seconds: float):
        self.rate_seconds = seconds

    def pause(self):
        with self._mixer_lock:
            self.paused = True

    def resume(self):
        with self._mixer_lock:
            self.paused = False
            self.stopped = False

    def stop(self):
        self.stopped = True
        self.paused = False
        self.clear_queue()

        try:
            with self._mixer_lock:
                pygame.mixer.music.stop()
        except AUDIO_PLAYER_RECOVERABLE_ERRORS as exc:
            print(f"[TTS] falha ao parar audio: {exc}")

    # ==========================
    # Loop principal
    # ==========================

    def start(self):

        if self._running or self._closed:
            return

        self._running = True

        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
        )

        self._thread.start()

    def shutdown(self):

        self._running = False
        self._closed = True
        self.clear_queue()

        try:
            with self._mixer_lock:
                pygame.mixer.music.stop()
        except AUDIO_PLAYER_RECOVERABLE_ERRORS as exc:
            print(f"[TTS] falha ao finalizar player: {exc}")
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        try:
            with self._mixer_lock:
                pygame.mixer.quit()
        except AUDIO_PLAYER_RECOVERABLE_ERRORS as exc:
            print(f"[TTS] falha ao finalizar mixer: {exc}")

    def _run(self):

        deferred_normal = None
        while self._running:

            if deferred_normal is not None and deferred_normal.generation != self._generation:
                self._safe_delete(deferred_normal.path)
                self.queue.task_done()
                deferred_normal = None

            if (self.paused or self.stopped) and self.priority_queue.empty():
                time.sleep(0.1)
                continue

            try:
                task = self.priority_queue.get_nowait()
                source_queue = self.priority_queue
            except queue.Empty:
                if deferred_normal is not None:
                    task = deferred_normal
                    deferred_normal = None
                    source_queue = self.queue
                else:
                    try:
                        task = self.queue.get(timeout=0.2)
                        source_queue = self.queue
                    except queue.Empty:
                        continue

            audio_file = task.path
            deferred = False
            try:
                with self._mixer_lock:
                    if (
                        not self._running
                        or task.generation != self._generation
                        or (self.stopped and not task.bypass_state)
                    ):
                        continue
                    if self.paused and source_queue is self.queue:
                        # Preserve this item's FIFO position while allowing
                        # priority audio to pass during the pause.
                        deferred_normal = task
                        deferred = True
                        continue
                    pygame.mixer.music.load(str(audio_file))
                    pygame.mixer.music.play()

                while self._is_music_busy():
                    time.sleep(0.05)

            except AUDIO_PLAYER_RECOVERABLE_ERRORS as exc:
                print(f"[TTS] erro ao tocar audio: {exc}")

            finally:
                if not deferred:
                    try:
                        with self._mixer_lock:
                            pygame.mixer.music.unload()
                    except AUDIO_PLAYER_RECOVERABLE_ERRORS as exc:
                        print(f"[TTS] falha ao descarregar audio: {exc}")
                    self._safe_delete(audio_file)
                    source_queue.task_done()

            self._sleep_between_items()

        if deferred_normal is not None:
            self._safe_delete(deferred_normal.path)
            self.queue.task_done()

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
            except OSError as exc:
                print(f"[TTS] nao foi possivel remover audio {path}: {exc}")
                return

    def _drain_queue(self, q: queue.Queue[_AudioTask]):
        while not q.empty():
            try:
                task = q.get_nowait()
            except queue.Empty:
                break
            self._safe_delete(task.path)
            q.task_done()

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
        except AUDIO_PLAYER_RECOVERABLE_ERRORS:
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
            except OSError as exc:
                print(f"[TTS] nao foi possivel remover audio antigo {file}: {exc}")
