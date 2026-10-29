import builtins
import contextlib
import io
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from secure_storage import SecureStorageError
from single_instance import AlreadyRunningError, SingleInstanceLock


class StartupSecurityTests(unittest.TestCase):
    def test_unreadable_configuration_has_safe_dialog_before_application_startup(self):
        original_import = builtins.__import__
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        data_dir = Path(directory.name)

        def guarded_import(name, *args, **kwargs):
            if name == "config":
                # No credential migration can start before the lifetime lock.
                with self.assertRaises(AlreadyRunningError):
                    SingleInstanceLock(data_dir).acquire()
                raise SecureStorageError("fictional-secret-must-not-be-displayed")
            return original_import(name, *args, **kwargs)

        output = io.StringIO()
        with patch("builtins.__import__", side_effect=guarded_import), \
                patch.dict("os.environ", {"TTSLIVE_DATA_DIR": str(data_dir)}), \
                patch("sys.argv", ["app.py"]), \
                patch("tkinter.Tk") as create_window, \
                patch("tkinter.messagebox.showerror") as show_error, \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(Path(__file__).resolve().parents[1] / "app.py"), run_name="__main__")
        self.assertEqual(raised.exception.code, 1)
        show_error.assert_called_once()
        create_window.return_value.destroy.assert_called_once()
        self.assertNotIn("fictional-secret", output.getvalue() + str(show_error.call_args))
        # A configuration failure releases the bootstrap lock immediately.
        with SingleInstanceLock(data_dir):
            pass
