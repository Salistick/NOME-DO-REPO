import contextlib
import io
import queue
import threading
import unittest
from unittest.mock import Mock, patch

import app
from launcher_gui import LauncherGUI


class AppLifecycleTests(unittest.TestCase):
    def test_critical_exception_omits_exception_payload_from_logs_and_dialog(self):
        output = io.StringIO()
        private_detail = "private-diagnostic-payload"
        with contextlib.redirect_stdout(output), patch("app.show_critical_error") as dialog:
            try:
                raise ValueError(private_detail)
            except ValueError as error:
                app.report_critical_exception(error)

        self.assertIn("[APP] erro fatal: ValueError", output.getvalue())
        self.assertNotIn(private_detail, output.getvalue())
        self.assertNotIn(private_detail, dialog.call_args.args[0])

    def test_critical_dialog_failure_does_not_log_dialog_text(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch("app.tk.Tk", side_effect=app.tk.TclError):
            app.show_critical_error("private-dialog-text")

        self.assertIn("exibir o aviso critico", output.getvalue())
        self.assertNotIn("private-dialog-text", output.getvalue())

    def test_worker_error_is_shown_only_when_main_thread_drains_queue(self):
        errors = queue.Queue(maxsize=20)
        root = Mock()
        with patch("app._pending_critical_errors", errors), \
                patch("app.tk.Tk") as create_root, \
                patch("app.messagebox.showerror") as show:
            worker = threading.Thread(target=app.show_critical_error, args=("test failure",))
            worker.start()
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            create_root.assert_not_called()
            show.assert_not_called()
            app._show_pending_critical_errors(root)
            show.assert_called_once_with("TTS Live - Erro critico", "test failure", parent=root)
            root.after.assert_called_once()

    def test_partial_startup_shuts_down_initialized_services(self):
        manager = Mock()
        with patch("app.StartupStatusWindow") as window, \
                patch("app.validate_runtime_environment"), \
                patch("app.configure_logging"), \
                patch("app.try_start_auto_update", return_value=False), \
                patch("app.validate_local_config"), \
                patch("app.validate_required_env_values"), \
                patch("app.ensure_polly_credentials_configured", return_value=True), \
                patch("app.AppStateStore") as store, \
                patch("app.TTSManager", return_value=manager), \
                patch("app.TwitchBot", side_effect=RuntimeError("startup failed")):
            store.return_value.load.return_value = {"platforms": {}}
            with self.assertRaisesRegex(RuntimeError, "startup failed"):
                app.main()
            manager.shutdown.assert_called_once()
            window.return_value.close.assert_called_once()

    def test_close_stops_pending_services_even_when_geometry_cannot_save(self):
        gui = LauncherGUI.__new__(LauncherGUI)
        gui.root = Mock()
        gui.on_shutdown = Mock()
        gui.twitch_bot = Mock()
        gui.youtube_bot = Mock()
        gui.kick_bot = Mock()
        gui._save_main_window_geometry = Mock(side_effect=OSError("disk full"))
        for bot in (gui.twitch_bot, gui.youtube_bot, gui.kick_bot):
            bot.is_running.return_value = False
        gui._on_close()
        gui.on_shutdown.assert_called_once()
        for bot in (gui.twitch_bot, gui.youtube_bot, gui.kick_bot):
            bot.stop.assert_called_once()
        gui.root.after.assert_called_once_with(100, gui.root.destroy)


if __name__ == "__main__":
    unittest.main()
