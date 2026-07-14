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
from platforms.kick.kick_bot import KickBot
from platforms.twitch.twitch_bot import TwitchBot
from platforms.youtube.youtube_bot import YouTubeBot
from services.tts.tts_manager import TTSManager


class StartupStatusWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("TTS Live")
        self.root.geometry("420x150")
        self.root.resizable(False, False)
        self.root.configure(bg="#111111")
        self.root.attributes("-topmost", True)

        frame = tk.Frame(self.root, bg="#111111")
        frame.pack(fill="both", expand=True, padx=24, pady=22)

        tk.Label(
            frame,
            text="TTS Live",
            font=("Segoe UI", 18, "bold"),
            fg="#FFFFFF",
            bg="#111111",
        ).pack(anchor="w")

        tk.Label(
            frame,
            text="Aguarde um instante",
            font=("Segoe UI", 10),
            fg="#8F8F8F",
            bg="#111111",
        ).pack(anchor="w", pady=(4, 14))

        self.message_var = tk.StringVar(value="Verificando atualizacoes...")

        tk.Label(
            frame,
            textvariable=self.message_var,
            font=("Segoe UI", 11),
            fg="#D8D8D8",
            bg="#111111",
            wraplength=360,
            justify="left",
        ).pack(anchor="w")

        self._center_window()
        self.refresh()

    def _center_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_width() or 420
        height = self.root.winfo_height() or 150
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        pos_x = max(0, (screen_width - width) // 2)
        pos_y = max(0, (screen_height - height) // 2)
        self.root.geometry(f"{width}x{height}+{pos_x}+{pos_y}")

    def set_message(self, message: str):
        self.message_var.set(message or "")
        self.refresh()

    def refresh(self):
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass


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
    startup_window = StartupStatusWindow()
    validate_runtime_environment()
    configure_logging(LOG_DIR)
    try:
        if try_start_auto_update(notify=startup_window.set_message):
            startup_window.refresh()
            time.sleep(1.0)
            return

        startup_window.set_message("Validando configuracao...")
        validate_local_config(require_twitch=False)
        validate_required_env_values()

        startup_window.set_message("Carregando dados do bot...")
        app_state_store = AppStateStore(APP_STATE_FILE)
        app_state = app_state_store.load()

        app_state.setdefault("platforms", {})
        app_state["platforms"].setdefault("twitch", {"enabled": False})
        app_state["platforms"].setdefault("youtube", {"enabled": False})
        app_state["platforms"].setdefault("kick", {"enabled": False})

        startup_window.set_message("Inicializando audio e servicos...")
        tts_manager = TTSManager()

        twitch_bot = TwitchBot(tts_manager)
        youtube_bot = YouTubeBot(
            tts_manager=tts_manager,
            token_cache_file=YOUTUBE_TOKEN_CACHE_FILE,
            config_file=YOUTUBE_CONFIG_FILE,
            message_store_file=YOUTUBE_MESSAGE_STORE_FILE,
        )
        kick_bot = KickBot(tts_manager=tts_manager)

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

        def set_kick_enabled(enabled: bool):
            new_state = get_app_state()
            new_state.setdefault("platforms", {})
            new_state["platforms"].setdefault("kick", {"enabled": False})
            new_state["platforms"]["kick"]["enabled"] = bool(enabled)
            save_app_state(new_state)

        def clear_platform_channel(platform_key: str):
            new_state = get_app_state()
            new_state.setdefault("platforms", {})
            new_state["platforms"].setdefault(platform_key, {"enabled": False})
            new_state["platforms"][platform_key]["channel_name"] = ""
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

        def on_toggle_twitch(action="login", channel_name: str | None = None):
            nonlocal gui, twitch_connecting, twitch_connect_attempt, twitch_connect_cancel_event

            if action == "stop" or twitch_bot.is_running():
                if gui and gui.confirm_twitch_disconnect():
                    with twitch_connecting_lock:
                        twitch_connect_attempt += 1
                        twitch_connect_cancel_event.set()
                        twitch_connect_cancel_event = threading.Event()
                        twitch_connecting = False

                    if twitch_bot.is_public_mode():
                        twitch_bot.stop()
                    else:
                        twitch_bot.disconnect_and_forget()
                return

            if action == "channel":
                with twitch_connecting_lock:
                    if twitch_connecting:
                        twitch_connect_attempt += 1
                        twitch_connect_cancel_event.set()
                        twitch_connect_cancel_event = threading.Event()
                        twitch_connecting = False
                    twitch_bot._status = "conectando Twitch sem login"

                try:
                    twitch_bot.start_public_channel(channel_name or "")
                except Exception as exc:
                    twitch_bot._status = "erro"
                    show_critical_error(f"Falha ao monitorar canal Twitch:\n\n{exc}")
                return

            if action == "login":
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

        def on_toggle_youtube(action="new", display_index: int | None = None):
            nonlocal gui, youtube_connecting, youtube_connect_attempt, youtube_connect_cancel_event
            if action == "forget_channel":
                with youtube_connecting_lock:
                    youtube_connect_attempt += 1
                    youtube_connect_cancel_event.set()
                    youtube_connect_cancel_event = threading.Event()
                    youtube_connecting = False

                if youtube_bot.is_public_mode():
                    youtube_bot.stop()
                clear_platform_channel("youtube")
                set_youtube_disabled(False)
                youtube_bot.refresh_idle_status()
                return

            if action == "forget_account":
                with youtube_connecting_lock:
                    youtube_connect_attempt += 1
                    youtube_connect_cancel_event.set()
                    youtube_connect_cancel_event = threading.Event()
                    youtube_connecting = False

                try:
                    account_index = int(display_index or 0)
                except (TypeError, ValueError):
                    account_index = 0

                if account_index <= 0 or not youtube_bot.remove_account_by_display_index(account_index):
                    show_critical_error("Nao foi possivel esquecer a conta selecionada do YouTube.")
                    return

                set_youtube_disabled(False)
                youtube_bot.refresh_idle_status()
                return

            if action == "disable":
                with youtube_connecting_lock:
                    youtube_connect_attempt += 1
                    youtube_connect_cancel_event.set()
                    youtube_connect_cancel_event = threading.Event()
                    youtube_connecting = False

                youtube_bot.disable_monitoring()
                set_youtube_disabled(True)
                return

            if action == "channel":
                channel_name = str(display_index or "").strip()
                with youtube_connecting_lock:
                    youtube_connect_attempt += 1
                    youtube_connect_cancel_event.set()
                    youtube_connect_cancel_event = threading.Event()
                    youtube_connecting = False

                try:
                    if youtube_bot.is_running():
                        youtube_bot.stop()
                    youtube_bot.start_public_channel(channel_name)
                    set_youtube_disabled(False)
                except Exception as exc:
                    youtube_bot._status = "erro"
                    show_critical_error(f"Falha ao monitorar canal YouTube:\n\n{exc}")
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

        def on_toggle_kick(action="login", channel_name: str | None = None):
            if action == "forget":
                kick_bot.disconnect_and_forget()
                clear_platform_channel("kick")
                set_kick_enabled(False)
                return

            if action == "stop" or kick_bot.is_running():
                kick_bot.stop()
                set_kick_enabled(False)
                return

            if action == "channel":
                try:
                    kick_bot.start_public_channel(channel_name or "")
                    set_kick_enabled(False)
                except Exception as exc:
                    kick_bot._status = "erro WebSocket Kick"
                    show_critical_error(f"Falha ao monitorar canal Kick:\n\n{exc}")
                return

            if not kick_bot.auth.is_configured():
                set_kick_enabled(False)
                show_critical_error(
                    "OAuth da Kick nao esta configurado.\n\n"
                    "Para entrar com conta Kick e permitir respostas no chat, preencha "
                    "KICK_CLIENT_ID e KICK_CLIENT_SECRET no arquivo .env.\n\n"
                    "Se quiser apenas testar a leitura do chat, use a opcao "
                    "\"Monitorar por nome do canal\"."
                )
                return

            kick_bot.start(force_auth=True)
            set_kick_enabled(True)

        startup_window.set_message("Abrindo interface...")
        startup_window.close()

        gui = LauncherGUI(
            twitch_bot=twitch_bot,
            youtube_bot=youtube_bot,
            kick_bot=kick_bot,
            tts_manager=tts_manager,
            on_toggle_twitch=on_toggle_twitch,
            on_toggle_youtube=on_toggle_youtube,
            on_toggle_kick=on_toggle_kick,
            get_app_state=get_app_state,
            save_app_state=save_app_state,
        )

        auto_connect_twitch_if_cached()

        if bool(app_state["platforms"].get("kick", {}).get("enabled", False)):
            set_kick_enabled(False)

        try:
            gui.run()
        finally:
            twitch_bot.shutdown()
            youtube_bot.shutdown()
            kick_bot.shutdown()
            tts_manager.shutdown()
    finally:
        startup_window.close()


if __name__ == "__main__":
    install_exception_hooks()
    try:
        main()
    except Exception as exc:
        report_critical_exception(exc)
