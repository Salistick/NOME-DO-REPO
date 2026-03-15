from config import (
    APP_STATE_FILE,
    YOUTUBE_TOKEN_CACHE_FILE,
    YOUTUBE_CONFIG_FILE,
    YOUTUBE_MESSAGE_STORE_FILE,
    build_env_help_message,
    validate_local_config,
    validate_required_env_values,
)
from app_state import AppStateStore
from launcher_gui import LauncherGUI

from platforms.twitch.twitch_bot import TwitchBot
from platforms.youtube.youtube_bot import YouTubeBot

from services.tts.tts_manager import TTSManager

import threading
import time
import traceback
import tkinter as tk
from tkinter import messagebox


def show_startup_error(message: str):
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("TTS Live - Erro de configuracao", message)
        root.destroy()
    except Exception:
        print(message)


def main():

    validate_local_config(require_twitch=False)
    validate_required_env_values()

    # ============================
    # Estado do app
    # ============================

    app_state_store = AppStateStore(APP_STATE_FILE)
    app_state = app_state_store.load()

    app_state.setdefault("platforms", {})
    app_state["platforms"].setdefault("twitch", {"enabled": False})
    app_state["platforms"].setdefault("youtube", {"enabled": False})

    # ============================
    # Criar TTS único
    # ============================

    tts_manager = TTSManager()

    # ============================
    # Criar bots
    # ============================

    twitch_bot = TwitchBot(tts_manager)

    youtube_bot = YouTubeBot(
        tts_manager=tts_manager,
        token_cache_file=YOUTUBE_TOKEN_CACHE_FILE,
        config_file=YOUTUBE_CONFIG_FILE,
        message_store_file=YOUTUBE_MESSAGE_STORE_FILE,
    )

    # deixa o TTS com acesso ao YouTubeBot para comandos futuros
    tts_manager.youtube_bot = youtube_bot

    gui = None

    # evita múltiplas tentativas simultâneas
    twitch_connecting_lock = threading.Lock()
    twitch_connecting = False

    youtube_connecting_lock = threading.Lock()
    youtube_connecting = False

    # ============================
    # helpers de estado
    # ============================

    def get_app_state():
        return app_state

    def save_app_state(new_state):
        nonlocal app_state
        app_state = new_state
        app_state_store.save(app_state)

    # ============================
    # conexão twitch
    # ============================

    def connect_twitch_thread(force_auth: bool):
        nonlocal twitch_connecting

        try:
            cached = twitch_bot.cache.load()

            if (
                cached
                and cached.get("access_token")
                and cached.get("login")
            ):
                twitch_bot._status = "conectando"
                twitch_bot.start(cached)
                return

            if not force_auth:
                twitch_bot._status = "desconectado"
                return

            validate_local_config(require_twitch=True)

            twitch_bot._status = "autenticando"

            token_data = twitch_bot.auth.get_valid_token()

            if not token_data:
                twitch_bot._status = "desconectado"
                return

            if token_data.get("access_token") and token_data.get("login"):
                twitch_bot._status = "conectando"
                twitch_bot.start(token_data)
                return

            for _ in range(20):
                cached = twitch_bot.cache.load()
                if (
                    cached
                    and cached.get("access_token")
                    and cached.get("login")
                ):
                    twitch_bot._status = "conectando"
                    twitch_bot.start(cached)
                    return
                time.sleep(0.1)

            twitch_bot._status = "erro"
            print("[APP] token Twitch obtido, mas ainda sem login suficiente para conectar ao chat.")

        except Exception as e:
            print("[APP] erro conectando twitch:", e)
            twitch_bot._status = "erro"

        finally:
            with twitch_connecting_lock:
                twitch_connecting = False

    def auto_connect_twitch_if_cached():
        nonlocal twitch_connecting

        cached = twitch_bot.cache.load()

        if not (
            cached
            and cached.get("access_token")
            and cached.get("login")
        ):
            return

        with twitch_connecting_lock:
            if twitch_connecting or twitch_bot.is_running():
                return
            twitch_connecting = True

        threading.Thread(
            target=connect_twitch_thread,
            args=(False,),
            daemon=True,
            name="TwitchAutoConnectThread",
        ).start()

    # ============================
    # conexão youtube
    # ============================

    def connect_youtube_thread(force_new_oauth: bool):
        nonlocal youtube_connecting

        try:
            accounts = youtube_bot.auth.list_cached_accounts()

            # startup automático: usa conta principal salva, sem abrir navegador
            if not force_new_oauth:
                if accounts:
                    youtube_bot._status = "conectando"
                    youtube_bot.start()
                else:
                    youtube_bot._status = "desconectado"
                return

            # clique manual: sempre força novo OAuth
            youtube_bot._status = "autenticando"

            account = youtube_bot.ensure_authenticated()

            if not account:
                youtube_bot._status = "desconectado"
                return

            youtube_bot._status = "conectando"
            youtube_bot.start()

        except Exception as e:
            print("[APP] erro conectando youtube:", e)
            youtube_bot._status = "erro"

        finally:
            with youtube_connecting_lock:
                youtube_connecting = False

    def auto_connect_youtube_if_cached():
        nonlocal youtube_connecting

        accounts = youtube_bot.auth.list_cached_accounts()

        if not accounts:
            return

        with youtube_connecting_lock:
            if youtube_connecting or youtube_bot.is_running():
                return
            youtube_connecting = True

        threading.Thread(
            target=connect_youtube_thread,
            args=(False,),
            daemon=True,
            name="YouTubeAutoConnectThread",
        ).start()

    # ============================
    # botão twitch
    # ============================

    def on_toggle_twitch():
        nonlocal gui, twitch_connecting

        if not twitch_bot.is_running():

            with twitch_connecting_lock:
                if twitch_connecting:
                    return
                twitch_connecting = True

            threading.Thread(
                target=connect_twitch_thread,
                args=(True,),
                daemon=True,
                name="TwitchConnectThread",
            ).start()

            return

        if gui and gui.confirm_twitch_disconnect():

            with twitch_connecting_lock:
                twitch_connecting = False

            twitch_bot.disconnect_and_forget()

    # ============================
    # botão youtube
    # ============================

    def on_toggle_youtube():
        nonlocal gui, youtube_connecting

        if not youtube_bot.is_running():

            with youtube_connecting_lock:
                if youtube_connecting:
                    return
                youtube_connecting = True

            threading.Thread(
                target=connect_youtube_thread,
                args=(True,),
                daemon=True,
                name="YouTubeConnectThread",
            ).start()

            return

        if gui and gui.confirm_youtube_disconnect():

            with youtube_connecting_lock:
                youtube_connecting = False

            youtube_bot.disconnect_and_forget()

    # ============================
    # GUI
    # ============================

    gui = LauncherGUI(
        twitch_bot=twitch_bot,
        youtube_bot=youtube_bot,
        on_toggle_twitch=on_toggle_twitch,
        on_toggle_youtube=on_toggle_youtube,
        get_app_state=get_app_state,
        save_app_state=save_app_state,
    )

    # auto conexão somente quando já existe auth suficiente
    auto_connect_twitch_if_cached()
    auto_connect_youtube_if_cached()

    # ============================
    # rodar GUI
    # ============================

    try:
        gui.run()

    finally:
        twitch_bot.shutdown()
        youtube_bot.shutdown()
        tts_manager.shutdown()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("[APP] erro fatal:", exc)
        print(traceback.format_exc())
        show_startup_error(f"{exc}\n\n{build_env_help_message()}")
