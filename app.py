import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import messagebox

from app_state import AppStateStore
from auto_updater import try_start_auto_update
from config import (
    APP_STATE_FILE,
    DATA_DIR,
    LOG_DIR,
    TTS_AUDIO_DIR,
    YOUTUBE_CONFIG_FILE,
    YOUTUBE_MESSAGE_STORE_FILE,
    YOUTUBE_TOKEN_CACHE_FILE,
    build_env_help_message,
    validate_local_config,
    validate_required_env_values,
)
from launcher_gui import LauncherGUI
from logging_setup import configure_logging
from platforms.twitch.twitch_bot import TwitchBot
from platforms.youtube.youtube_bot import YouTubeBot
from services.tts.tts_manager import TTSManager


def show_critical_error(message: str):
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("TTS Live - Erro critico", message)
        root.destroy()
    except Exception:
        print(message)


def format_critical_error_message(exc: BaseException) -> str:
    details = str(exc).strip() or exc.__class__.__name__
    return f"{details}\n\n{build_env_help_message()}"


def report_critical_exception(exc: BaseException, include_traceback: bool = True) -> None:
    print("[APP] erro fatal:", exc)
    if include_traceback:
        print(traceback.format_exc())
    show_critical_error(format_critical_error_message(exc))


def install_exception_hooks() -> None:
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            return

        print("[APP] excecao nao tratada:")
        print("".join(traceback.format_exception(exc_type, exc_value, exc_traceback)))
        show_critical_error(format_critical_error_message(exc_value))

    def handle_thread_exception(args):
        print(f"[APP] excecao critica na thread {args.thread.name}:")
        print("".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
        show_critical_error(format_critical_error_message(args.exc_value))

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception


def validate_runtime_environment() -> None:
    required_dirs = [DATA_DIR, TTS_AUDIO_DIR, LOG_DIR]

    for directory in required_dirs:
        directory.mkdir(parents=True, exist_ok=True)
        probe_file = directory / ".write_test"
        try:
            probe_file.write_text("ok", encoding="utf-8")
            probe_file.unlink(missing_ok=True)
        except Exception as exc:
            raise RuntimeError(
                f"Sem permissao de escrita em {directory}. Verifique a pasta do bot."
            ) from exc


def main():
    validate_runtime_environment()
    configure_logging(LOG_DIR)
    if try_start_auto_update():
        return
    validate_local_config(require_twitch=False)
    validate_required_env_values()

    app_state_store = AppStateStore(APP_STATE_FILE)
    app_state = app_state_store.load()

    app_state.setdefault("platforms", {})
    app_state["platforms"].setdefault("twitch", {"enabled": False})
    app_state["platforms"].setdefault("youtube", {"enabled": False})

    tts_manager = TTSManager()

    twitch_bot = TwitchBot(tts_manager)
    youtube_bot = YouTubeBot(
        tts_manager=tts_manager,
        token_cache_file=YOUTUBE_TOKEN_CACHE_FILE,
        config_file=YOUTUBE_CONFIG_FILE,
        message_store_file=YOUTUBE_MESSAGE_STORE_FILE,
    )

    tts_manager.youtube_bot = youtube_bot

    youtube_disabled = bool(app_state["platforms"].get("youtube", {}).get("disabled", False))
    youtube_bot.set_monitoring_disabled(youtube_disabled)
    youtube_bot.refresh_idle_status()

    gui = None

    twitch_connecting_lock = threading.Lock()
    twitch_connecting = False
    twitch_connect_attempt = 0
    twitch_connect_cancel_event = threading.Event()

    youtube_connecting_lock = threading.Lock()
    youtube_connecting = False
    youtube_connect_attempt = 0
    youtube_connect_cancel_event = threading.Event()

    def get_app_state():
        return app_state

    def save_app_state(new_state):
        nonlocal app_state
        app_state = new_state
        app_state_store.save(app_state)

    def set_youtube_disabled(disabled: bool):
        new_state = get_app_state()
        new_state.setdefault("platforms", {})
        new_state["platforms"].setdefault("youtube", {"enabled": False})
        new_state["platforms"]["youtube"]["disabled"] = bool(disabled)
        save_app_state(new_state)

    def is_current_twitch_attempt(attempt_id: int, cancel_event: threading.Event) -> bool:
        return (not cancel_event.is_set()) and attempt_id == twitch_connect_attempt

    def is_current_youtube_attempt(attempt_id: int, cancel_event: threading.Event) -> bool:
        return (not cancel_event.is_set()) and attempt_id == youtube_connect_attempt

    def connect_twitch_thread(force_auth: bool, attempt_id: int, cancel_event: threading.Event):
        nonlocal twitch_connecting

        try:
            if not is_current_twitch_attempt(attempt_id, cancel_event):
                twitch_bot._status = "desconectado"
                return

            cached = twitch_bot.cache.load()

            if cached and cached.get("access_token") and cached.get("login"):
                if not is_current_twitch_attempt(attempt_id, cancel_event):
                    twitch_bot._status = "desconectado"
                    return

                twitch_bot._status = "conectando"
                twitch_bot.start(cached)
                return

            if not force_auth:
                twitch_bot._status = "desconectado"
                return

            validate_local_config(require_twitch=True)
            twitch_bot._status = "autenticando"

            token_data = twitch_bot.auth.get_valid_token(cancel_event=cancel_event)

            if not token_data:
                twitch_bot._status = "desconectado"
                return

            if not is_current_twitch_attempt(attempt_id, cancel_event):
                twitch_bot._status = "desconectado"
                return

            if token_data.get("access_token") and token_data.get("login"):
                twitch_bot._status = "conectando"
                twitch_bot.start(token_data)
                return

            for _ in range(20):
                if not is_current_twitch_attempt(attempt_id, cancel_event):
                    twitch_bot._status = "desconectado"
                    return

                cached = twitch_bot.cache.load()
                if cached and cached.get("access_token") and cached.get("login"):
                    twitch_bot._status = "conectando"
                    twitch_bot.start(cached)
                    return
                time.sleep(0.1)

            twitch_bot._status = "erro"
            print("[APP] token Twitch obtido, mas ainda sem login suficiente para conectar ao chat.")

        except Exception as e:
            if not is_current_twitch_attempt(attempt_id, cancel_event):
                twitch_bot._status = "desconectado"
            else:
                print("[APP] erro conectando twitch:", e)
                twitch_bot._status = "erro"
                show_critical_error(f"Falha critica ao conectar Twitch:\n\n{e}")

        finally:
            with twitch_connecting_lock:
                if attempt_id == twitch_connect_attempt:
                    twitch_connecting = False

    def auto_connect_twitch_if_cached():
        nonlocal twitch_connecting, twitch_connect_attempt, twitch_connect_cancel_event

        cached = twitch_bot.cache.load()

        if not (cached and cached.get("access_token") and cached.get("login")):
            return

        with twitch_connecting_lock:
            if twitch_connecting or twitch_bot.is_running():
                return
            twitch_connect_attempt += 1
            twitch_connect_cancel_event = threading.Event()
            attempt_id = twitch_connect_attempt
            twitch_connecting = True

        threading.Thread(
            target=connect_twitch_thread,
            args=(False, attempt_id, twitch_connect_cancel_event),
            daemon=True,
            name="TwitchAutoConnectThread",
        ).start()

    def connect_youtube_thread(force_new_oauth: bool, attempt_id: int, cancel_event: threading.Event):
        nonlocal youtube_connecting

        try:
            if not is_current_youtube_attempt(attempt_id, cancel_event):
                youtube_bot.refresh_idle_status()
                return

            accounts = youtube_bot.auth.list_cached_accounts()

            if not force_new_oauth:
                if accounts:
                    youtube_bot.refresh_idle_status()
                else:
                    youtube_bot._status = "desconectado"
                return

            youtube_bot._status = "aguardando retorno oauth"

            account = youtube_bot.auth.run_browser_login(cancel_event=cancel_event)

            if not account:
                youtube_bot.refresh_idle_status()
                return

            if not is_current_youtube_attempt(attempt_id, cancel_event):
                youtube_bot.refresh_idle_status()
                return

            youtube_bot.refresh_idle_status()

        except Exception as e:
            if not is_current_youtube_attempt(attempt_id, cancel_event):
                youtube_bot.refresh_idle_status()
            else:
                print("[APP] erro conectando youtube:", e)
                youtube_bot._status = "erro"
                show_critical_error(f"Falha critica ao conectar YouTube:\n\n{e}")

        finally:
            with youtube_connecting_lock:
                if attempt_id == youtube_connect_attempt:
                    youtube_connecting = False

    def on_toggle_twitch():
        nonlocal gui, twitch_connecting, twitch_connect_attempt, twitch_connect_cancel_event

        if not twitch_bot.is_running():
            with twitch_connecting_lock:
                if twitch_connecting:
                    twitch_connect_attempt += 1
                    twitch_connect_cancel_event.set()
                    twitch_connect_cancel_event = threading.Event()
                    twitch_connecting = False
                    twitch_bot._status = "desconectado"
                    return

                twitch_connect_attempt += 1
                attempt_id = twitch_connect_attempt
                twitch_connect_cancel_event = threading.Event()
                twitch_connecting = True

            threading.Thread(
                target=connect_twitch_thread,
                args=(True, attempt_id, twitch_connect_cancel_event),
                daemon=True,
                name="TwitchConnectThread",
            ).start()
            return

        if gui and gui.confirm_twitch_disconnect():
            with twitch_connecting_lock:
                twitch_connect_attempt += 1
                twitch_connect_cancel_event.set()
                twitch_connect_cancel_event = threading.Event()
                twitch_connecting = False

            twitch_bot.disconnect_and_forget()

    def on_toggle_youtube(action="new", display_index: int | None = None):
        nonlocal gui, youtube_connecting, youtube_connect_attempt, youtube_connect_cancel_event
        if action == "disable":
            with youtube_connecting_lock:
                youtube_connect_attempt += 1
                youtube_connect_cancel_event.set()
                youtube_connect_cancel_event = threading.Event()
                youtube_connecting = False

            youtube_bot.disable_monitoring()
            set_youtube_disabled(True)
            return

        if action == "select":
            with youtube_connecting_lock:
                if youtube_connecting:
                    youtube_connect_attempt += 1
                    youtube_connect_cancel_event.set()
                    youtube_connect_cancel_event = threading.Event()
                    youtube_connecting = False

            if display_index is not None:
                ok = youtube_bot.activate_account_by_display_index(display_index)
                if not ok:
                    show_critical_error("Nao foi possivel ativar a conta selecionada do YouTube.")
                else:
                    set_youtube_disabled(False)
            return

        with youtube_connecting_lock:
            if youtube_connecting:
                youtube_connect_attempt += 1
                youtube_connect_cancel_event.set()
                youtube_connect_cancel_event = threading.Event()
                youtube_connecting = False
                youtube_bot._status = "desconectado"
                return

            youtube_connect_attempt += 1
            attempt_id = youtube_connect_attempt
            youtube_connect_cancel_event = threading.Event()
            youtube_connecting = True

        threading.Thread(
            target=connect_youtube_thread,
            args=(True, attempt_id, youtube_connect_cancel_event),
            daemon=True,
            name="YouTubeConnectThread",
        ).start()

    gui = LauncherGUI(
        twitch_bot=twitch_bot,
        youtube_bot=youtube_bot,
        on_toggle_twitch=on_toggle_twitch,
        on_toggle_youtube=on_toggle_youtube,
        get_app_state=get_app_state,
        save_app_state=save_app_state,
    )

    auto_connect_twitch_if_cached()

    try:
        gui.run()
    finally:
        twitch_bot.shutdown()
        youtube_bot.shutdown()
        tts_manager.shutdown()


if __name__ == "__main__":
    install_exception_hooks()
    try:
        main()
    except Exception as exc:
        report_critical_exception(exc)
