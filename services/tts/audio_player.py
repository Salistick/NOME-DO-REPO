import threading
import time
from pathlib import Path
import queue
import pygame


class AudioPlayer:

    def __init__(self, audio_dir: Path, rate_seconds: float = 2.5):
        self.audio_dir = Path(audio_dir)
        self.rate_seconds = rate_seconds

        self.queue: queue.Queue[Path] = queue.Queue()
        self.priority_queue: queue.Queue[Path] = queue.Queue()

        self.paused = False
        self.stopped = False

        self._thread = None
        self._running = False

        pygame.mixer.init()

        self._cleanup_audio_dir()

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
                pygame.mixer.music.load(str(audio_file))
                pygame.mixer.music.play()

                while pygame.mixer.music.get_busy():
                    time.sleep(0.05)

            except Exception as exc:
                print(f"[TTS] erro ao tocar áudio: {exc}")

            finally:
                try:
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
                q.get_nowait()
            except queue.Empty:
                break

    def _sleep_between_items(self):
        slept = 0.0

        while slept < self.rate_seconds and self._running:
            if not self.priority_queue.empty():
                return

            step = min(0.1, self.rate_seconds - slept)
            time.sleep(step)
            slept += step

    def _cleanup_audio_dir(self):

        for file in self.audio_dir.glob("*"):
            try:
                file.unlink()
            except Exception:
                pass
