"""Exercise a packaged installation without connecting accounts or playing audio."""

import json
import os
from pathlib import Path


class _IdleBot:
    def get_status(self):
        return "desconectado"

    def is_running(self):
        return False

    def has_saved_auth(self):
        return False

    def list_account_choices(self):
        return []

    def stop(self):
        pass


class _SilentAudio:
    def list_audio_output_devices(self):
        return []

    def get_audio_output_device(self):
        return ""


def run_smoke_test(output_path: Path) -> int:
    output_path = Path(output_path).resolve()
    result = {"ok": False, "checks": {}}
    gui = None
    try:
        if not os.environ.get("TTSLIVE_DATA_DIR"):
            raise RuntimeError("Smoke test requires an isolated TTSLIVE_DATA_DIR.")
        from app_version import CURRENT_APP_VERSION
        from config import DATA_DIR
        from launcher_gui import LauncherGUI
        from persistence import atomic_write_json
        from secure_storage import protect_secret_bytes, unprotect_secret_bytes
        from single_instance import AlreadyRunningError, SingleInstanceLock

        expected_data_dir = Path(os.environ["TTSLIVE_DATA_DIR"]).expanduser().resolve()
        if DATA_DIR.resolve() != expected_data_dir:
            raise RuntimeError("Smoke test data directory is not isolated.")
        result["version"] = CURRENT_APP_VERSION
        result["data_dir"] = str(DATA_DIR)
        with SingleInstanceLock(DATA_DIR):
            second = SingleInstanceLock(DATA_DIR)
            try:
                second.acquire()
            except AlreadyRunningError:
                result["checks"]["single_instance"] = True
            else:
                second.release()
                raise RuntimeError("Second instance was not blocked.")

            fixture = b"TTSLive smoke-test fixture"
            encrypted = protect_secret_bytes(fixture)
            if fixture in encrypted or unprotect_secret_bytes(encrypted) != fixture:
                raise RuntimeError("Credential protection round-trip failed.")
            result["checks"]["credential_protection"] = True

            def no_action(*_args, **_kwargs):
                return None

            gui = LauncherGUI(
                _IdleBot(), _IdleBot(), _IdleBot(), _SilentAudio(),
                no_action, no_action, no_action, no_action,
                lambda: {"window": {}, "platforms": {}}, no_action,
            )
            gui.root.withdraw()
            gui.root.update_idletasks()
            if gui.twitch_status_var.get() != "desconectado":
                raise RuntimeError("GUI status did not initialize.")
            result["checks"]["gui"] = True
            result["ok"] = True
        atomic_write_json(output_path, result)
        return 0
    except Exception as exc:
        # No exception text: errors in credential code must not expose secrets.
        result["error_type"] = type(exc).__name__
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 1
    finally:
        if gui is not None:
            gui.root.destroy()
