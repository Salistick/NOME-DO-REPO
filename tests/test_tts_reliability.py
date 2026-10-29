import io
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError, EndpointConnectionError

from services.tts.audio_player import MAX_PENDING_AUDIO, AudioPlayer
from services.tts.polly_client import PollyClient
from services.tts.polly_credentials import PollyCredentialStore
from services.tts.text_sanitizer import build_polly_ssml, replace_multiword_gamer_terms, sanitize_chat_text, sanitize_username_for_tts
from services.tts.tts_config_store import TTSConfigStore
from services.tts.tts_manager import TTSManager
from services.tts.tts_state import TTSState


def make_manager():
    manager = TTSManager.__new__(TTSManager)
    manager.state = TTSState()
    manager.lock = threading.RLock()
    manager._polly_lock = threading.Lock()
    manager._synth_queue = queue.PriorityQueue(maxsize=MAX_PENDING_AUDIO)
    manager._synth_sequence = 0
    manager._synth_generation = 0
    manager._synth_running = True
    manager.polly = Mock()
    manager.player = Mock()
    manager.player.queue_length.return_value = 0
    manager.player.paused = False
    manager.player.stopped = False
    return manager


class TTSSynthesisQueueTests(unittest.TestCase):
    def test_expected_aws_errors_do_not_kill_the_worker(self):
        errors = [
            ClientError({"Error": {"Code": "AccessDeniedException"}}, "SynthesizeSpeech"),
            EndpointConnectionError(endpoint_url="https://example.invalid"),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                manager = make_manager()
                audio = Path(directory) / "ok.mp3"
                manager.polly.synthesize.side_effect = [error, audio]
                manager.player.enqueue.side_effect = lambda *args, current=manager, **kwargs: setattr(current, "_synth_running", False)
                manager._queue_audio("fails")
                manager._queue_audio("succeeds")
                manager._run_synth_queue()
                self.assertEqual(manager.polly.synthesize.call_count, 2)
                manager.player.enqueue.assert_called_once_with(audio, priority=False, bypass_state=False)
                self.assertEqual(manager._synth_queue.unfinished_tasks, 0)

    def test_stop_then_resume_discards_synthesis_that_was_already_in_flight(self):
        manager = make_manager()
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "cancelled.mp3"
            audio.write_bytes(b"audio")

            def synthesize(_):
                manager._handle_stop({})
                manager._handle_resume({})
                return audio

            manager.polly.synthesize.side_effect = synthesize
            manager._queue_audio("old-message")
            original_get = manager._synth_queue.get

            def get_next(*args, **kwargs):
                if manager.polly.synthesize.call_count:
                    manager._synth_running = False
                    raise queue.Empty
                return original_get(*args, **kwargs)

            with patch.object(manager._synth_queue, "get", side_effect=get_next):
                manager._run_synth_queue()
            self.assertFalse(audio.exists())
            manager.player.enqueue.assert_not_called()
            self.assertEqual(manager._synth_queue.unfinished_tasks, 0)

    def test_synthesis_queue_has_a_nonblocking_limit(self):
        manager = make_manager()
        for _ in range(MAX_PENDING_AUDIO - 1):
            self.assertTrue(manager._queue_audio("message"))
        self.assertFalse(manager._queue_audio("overflow"))
        self.assertTrue(manager._queue_audio("admin", priority=True, bypass_state=True))
        self.assertFalse(manager._queue_audio("admin overflow", priority=True, bypass_state=True))
        self.assertEqual(manager._synth_queue.qsize(), MAX_PENDING_AUDIO)

    def test_playback_backpressure_delays_paid_synthesis(self):
        manager = make_manager()
        manager.player.queue_length.side_effect = [MAX_PENDING_AUDIO, 0]
        manager.player.enqueue.side_effect = lambda *args, **kwargs: setattr(manager, "_synth_running", False)
        manager._queue_audio("message")
        with patch("services.tts.tts_manager.time.sleep") as sleep:
            sleep.side_effect = lambda _: manager.polly.synthesize.assert_not_called()
            manager._run_synth_queue()
        sleep.assert_called_once_with(0.1)
        manager.polly.synthesize.assert_called_once_with("message")

    def test_admin_speech_passes_normal_synthesis_blocked_by_paused_playback(self):
        manager = make_manager()
        manager.player.paused = True
        manager.player.queue_length.return_value = MAX_PENDING_AUDIO - 1
        waiting = threading.Event()
        admin_played = threading.Event()
        original_sleep = time.sleep

        def wait_for_capacity(seconds):
            waiting.set()
            original_sleep(seconds)

        def enqueued(*args, **kwargs):
            admin_played.set()
            manager._synth_running = False

        manager.player.enqueue.side_effect = enqueued
        manager._queue_audio("normal")
        worker = threading.Thread(target=manager._run_synth_queue, daemon=True)
        with patch("services.tts.tts_manager.time.sleep", side_effect=wait_for_capacity):
            worker.start()
            try:
                self.assertTrue(waiting.wait(timeout=2))
                manager._queue_audio("admin", priority=True, bypass_state=True)
                self.assertTrue(admin_played.wait(timeout=2))
            finally:
                manager._synth_running = False
                worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        manager.polly.synthesize.assert_called_once_with("admin")
        self.assertEqual(manager._synth_queue.qsize(), 1)
        manager._clear_pending_audio_queue()
        self.assertEqual(manager._synth_queue.unfinished_tasks, 0)

    def test_concurrent_public_messages_share_one_cooldown(self):
        manager = make_manager()
        barrier = threading.Barrier(12)

        def submit():
            barrier.wait(timeout=2)
            manager._handle_ms({"username": "same-user", "platform": "twitch"}, "hello")

        with patch("services.tts.tts_manager.sanitize_chat_text", return_value=("hello", False)), patch(
            "services.tts.tts_manager.build_tts_text", return_value="user said hello"
        ):
            threads = [threading.Thread(target=submit) for _ in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)
        self.assertEqual(manager._synth_queue.qsize(), 1)

    def test_invalid_numeric_commands_are_rejected(self):
        manager = make_manager()
        for text in ("nan", "inf", "-inf", "-1", "0", "garbage"):
            self.assertIsNone(manager._parse_positive_float(text))
        self.assertEqual(manager._parse_positive_float("0", allow_zero=True), 0)


class AudioCleanupTests(unittest.TestCase):
    def make_player(self):
        player = AudioPlayer.__new__(AudioPlayer)
        player.stopped = False
        player.paused = False
        player._closed = False
        player._generation = 0
        player.rate_seconds = 0
        player.queue = queue.Queue()
        player.priority_queue = queue.Queue()
        player._queue_lock = threading.Lock()
        return player

    def test_pause_after_dequeue_preserves_audio_until_resume(self):
        player = self.make_player()
        player._running = True
        player._mixer_lock = threading.RLock()
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "paused.mp3"
            audio.write_bytes(b"audio")
            player.enqueue(audio)
            original_get = player.queue.get

            def get_then_pause(*args, **kwargs):
                task = original_get(*args, **kwargs)
                player.pause()
                return task

            with patch.object(player.queue, "get", side_effect=get_then_pause), patch(
                "services.tts.audio_player.pygame.mixer"
            ) as mixer, patch("services.tts.audio_player.time.sleep") as sleep:
                mixer.music.get_busy.return_value = False

                def resume_when_waiting(_):
                    mixer.music.play.assert_not_called()
                    self.assertTrue(audio.exists())
                    self.assertEqual(player.queue.unfinished_tasks, 1)
                    player.resume()

                sleep.side_effect = resume_when_waiting
                mixer.music.play.side_effect = lambda: setattr(player, "_running", False)
                player._run()
            sleep.assert_called_once_with(0.1)
            mixer.music.play.assert_called_once()
            self.assertFalse(audio.exists())
            self.assertEqual(player.queue.unfinished_tasks, 0)

    def test_shutdown_cleans_audio_deferred_by_pause(self):
        player = self.make_player()
        player._running = True
        player._mixer_lock = threading.RLock()
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "paused.mp3"
            audio.write_bytes(b"audio")
            player.enqueue(audio)
            original_get = player.queue.get

            def get_then_pause(*args, **kwargs):
                task = original_get(*args, **kwargs)
                player.pause()
                return task

            with patch.object(player.queue, "get", side_effect=get_then_pause), patch(
                "services.tts.audio_player.pygame.mixer"
            ) as mixer, patch("services.tts.audio_player.time.sleep") as sleep:
                sleep.side_effect = lambda _: setattr(player, "_running", False)
                player._run()
            mixer.music.play.assert_not_called()
            self.assertFalse(audio.exists())
            self.assertEqual(player.queue.unfinished_tasks, 0)

    def test_stop_resume_cannot_resurrect_audio_already_taken_from_queue(self):
        player = self.make_player()
        player._running = True
        player._mixer_lock = threading.RLock()
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "cancelled.mp3"
            audio.write_bytes(b"audio")
            player.enqueue(audio)
            original_get = player.queue.get
            delivered = False

            def get_next(*args, **kwargs):
                nonlocal delivered
                if delivered:
                    player._running = False
                    raise queue.Empty
                delivered = True
                task = original_get(*args, **kwargs)
                player.stop()
                player.resume()
                return task

            with patch.object(player.queue, "get", side_effect=get_next), patch("services.tts.audio_player.pygame.mixer") as mixer:
                player._run()
            mixer.music.play.assert_not_called()
            self.assertFalse(audio.exists())
            self.assertEqual(player.queue.unfinished_tasks, 0)

    def test_rejected_and_drained_audio_is_deleted(self):
        player = self.make_player()
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "stopped.mp3"
            audio.write_bytes(b"audio")
            player.stopped = True
            self.assertFalse(player.enqueue(audio))
            self.assertFalse(audio.exists())
            for index in range(MAX_PENDING_AUDIO):
                item = Path(directory) / f"{index}.mp3"
                item.write_bytes(b"audio")
                self.assertTrue(player.enqueue(item, priority=True, bypass_state=True))
            overflow = Path(directory) / "overflow.mp3"
            overflow.write_bytes(b"audio")
            self.assertFalse(player.enqueue(overflow, priority=True, bypass_state=True))
            self.assertFalse(overflow.exists())
            player.clear_queue()
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertEqual(player.priority_queue.unfinished_tasks, 0)

    def test_polly_closes_stream_and_cleans_partial_output_on_error(self):
        with tempfile.TemporaryDirectory() as directory:
            polly = PollyClient.__new__(PollyClient)
            polly.audio_dir = Path(directory)
            stream = Mock()
            stream.read.side_effect = [b"partial", OSError("read interrupted")]
            polly._synthesize_speech = Mock(return_value={"AudioStream": stream})
            with self.assertRaises(OSError):
                polly.synthesize("hello")
            stream.close.assert_called_once()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_polly_writes_complete_audio_and_closes_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            polly = PollyClient.__new__(PollyClient)
            polly.audio_dir = Path(directory)
            stream = io.BytesIO(b"complete audio")
            polly._synthesize_speech = Mock(return_value={"AudioStream": stream})
            output = polly.synthesize("hello")
            self.assertEqual(output.read_bytes(), b"complete audio")
            self.assertTrue(stream.closed)


class TTSConfigurationTests(unittest.TestCase):
    def test_malformed_types_and_nonfinite_numbers_fall_back_to_defaults(self):
        for malformed in ([], "text", None):
            self.assertEqual(TTSState.from_persisted_dict(malformed).rate_seconds, 2.5)
        state = TTSState.from_persisted_dict({
            "rate_seconds": float("inf"),
            "platforms": {
                "twitch": {"max_words": "invalid", "user_cooldown_seconds": float("nan"), "mode_sub_only": "false"},
                "kick": ["invalid"],
            },
        })
        self.assertEqual(state.rate_seconds, 2.5)
        twitch = state.get_platform_config("twitch")
        self.assertEqual(twitch.max_words, 20)
        self.assertEqual(twitch.user_cooldown_seconds, 5)
        self.assertFalse(twitch.mode_sub_only)

    def test_failed_save_preserves_previous_config_and_removes_temp_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tts.json"
            original = b'{"rate_seconds": 2.5}'
            target.write_bytes(original)
            store = TTSConfigStore(target)
            with patch("persistence.os.replace", side_effect=OSError("locked")), self.assertRaises(OSError):
                store.save({"rate_seconds": 3})
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [target])
            target.write_text("[]", encoding="utf-8")
            self.assertEqual(store.load(), {})

    def test_cancelled_sso_setup_preserves_existing_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "polly.json"
            secret = Path(directory) / "secret.bin"
            secret.write_bytes(b"existing protected credentials")
            store = PollyCredentialStore(config, secret)
            oidc = Mock()
            oidc.register_client.return_value = {"clientId": "id", "clientSecret": "secret"}
            oidc.start_device_authorization.return_value = {"verificationUri": "https://example.invalid"}
            access_data = {"sso_access_token": "new-token"}
            with patch("services.tts.polly_credentials.boto3.client", return_value=oidc), patch(
                "services.tts.polly_credentials.webbrowser.open"
            ), patch.object(store, "_poll_sso_device_authorization", return_value=access_data):
                self.assertEqual(store.start_sso_browser_login("https://example.invalid", "us-east-1"), "new-token")
            self.assertEqual(secret.read_bytes(), b"existing protected credentials")
            self.assertFalse(config.exists())
            with patch("services.tts.polly_credentials.protect_secret_bytes", side_effect=lambda value: b"protected:" + value), patch(
                "services.tts.polly_credentials.unprotect_secret_bytes", side_effect=lambda value: value.removeprefix(b"protected:")
            ):
                store.save_sso("us-east-1", "https://example.invalid", "us-east-1", "123", "Account", "Role")
                self.assertEqual(store.load_config().source, "sso")
            self.assertTrue(store.bundle_file.read_bytes().startswith(b"protected:"))
            self.assertEqual(secret.read_bytes(), b"existing protected credentials")
            self.assertFalse(config.exists())

    def test_large_numeric_input_is_bounded_before_normalization(self):
        for text in ("1234567890" * 600, "R$" + "1234567890" * 600):
            cleaned, _ = sanitize_chat_text(text)
            self.assertLessEqual(len(cleaned), 220)
        name = sanitize_username_for_tts("1234567890" * 600)
        self.assertLess(len(name), 1000)

    def test_ssml_escapes_user_markup(self):
        ssml = build_polly_ssml("hello <speak> & world")
        self.assertIn("&lt;speak&gt;", ssml)
        self.assertEqual(ssml.count("<speak>"), 1)

    def test_custom_pronunciation_is_literal_text(self):
        with patch("services.tts.text_sanitizer.load_pronunciation_rules", return_value={"phrases": {"custom term": r"say \q"}}):
            self.assertEqual(replace_multiword_gamer_terms("custom term"), r"say \q")


if __name__ == "__main__":
    unittest.main()
