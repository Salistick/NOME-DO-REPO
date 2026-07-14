import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from app_version import CURRENT_APP_VERSION


class RoundedToggleButton(tk.Canvas):
    def __init__(
        self,
        master,
        text,
        width=260,
        height=56,
        radius=18,
        bg_off="#9146FF",
        bg_on="#5E2CA5",
        text_color="#FFFFFF",
        command=None,
        **kwargs,
    ):
        super().__init__(
            master,
            width=width,
            height=height,
            bg=master["bg"],
            highlightthickness=0,
            bd=0,
            **kwargs
        )

        self.width = width
        self.height = height
        self.radius = radius
        self.bg_off = bg_off
        self.bg_on = bg_on
        self.text_color = text_color
        self.command = command

        self.base_text = text
        self.is_on = False
        self.is_hover = False

        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

        self._draw()

    def set_state(self, is_on: bool):
        self.is_on = is_on
        self._draw()

    def _on_click(self, event):
        if self.command:
            self.command()

    def _on_enter(self, event):
        self.is_hover = True
        self._draw()

    def _on_leave(self, event):
        self.is_hover = False
        self._draw()

    def _rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self.create_polygon(points, smooth=True, splinesteps=36, **kwargs)

    def _draw(self):
        self.delete("all")

        if self.is_on:
            fill = self.bg_on
            offset_y = 3
            label = f"Ativo: {self.base_text}"
        else:
            fill = self.bg_off
            offset_y = 0
            label = self.base_text

        if self.is_hover:
            outline = "#C9A7FF"
            outline_width = 2
        else:
            outline = fill
            outline_width = 1

        shadow_color = "#2D143F"

        if not self.is_on:
            self._rounded_rect(
                4, 6, self.width - 4, self.height - 2,
                self.radius,
                fill=shadow_color,
                outline=shadow_color
            )

        self._rounded_rect(
            4,
            4 + offset_y,
            self.width - 4,
            self.height - 4 + offset_y,
            self.radius,
            fill=fill,
            outline=outline,
            width=outline_width
        )

        self.create_text(
            self.width / 2,
            self.height / 2 + offset_y,
            text=label,
            fill=self.text_color,
            font=("Segoe UI", 12, "bold")
        )


class LauncherGUI:
    AUDIO_DEFAULT_LABEL = "Padrao do sistema"

    def __init__(
        self,
        twitch_bot,
        youtube_bot,
        kick_bot,
        tts_manager,
        on_toggle_twitch,
        on_toggle_youtube,
        on_toggle_kick,
        get_app_state,
        save_app_state,
    ):
        self.twitch_bot = twitch_bot
        self.youtube_bot = youtube_bot
        self.kick_bot = kick_bot
        self.tts_manager = tts_manager
        self.on_toggle_twitch = on_toggle_twitch
        self.on_toggle_youtube = on_toggle_youtube
        self.on_toggle_kick = on_toggle_kick
        self.get_app_state = get_app_state
        self.save_app_state = save_app_state

        self.root = tk.Tk()
        self.root.title("TTS Live")
        self.root.geometry(f"440x{self._main_window_height()}")
        self.root.resizable(False, False)
        self.root.configure(bg="#111111")

        self.twitch_status_var = tk.StringVar(value="desconectado")
        self.youtube_status_var = tk.StringVar(value="desconectado")
        self.kick_status_var = tk.StringVar(value="desconectado")
        self.audio_output_var = tk.StringVar(value="")
        self.audio_output_by_label = {}
        self.platform_menu_window = None
        self.youtube_menu_window = None

        self._build()
        self._restore_or_center_main_window()
        self._schedule_refresh()

    def _get_version_label_text(self) -> str:
        version = (CURRENT_APP_VERSION or "").strip() or "dev"
        if not version.lower().startswith("v"):
            version = f"v{version}"
        return version

    def _main_window_height(self) -> int:
        return 580

    def _configure_styles(self):
        style = ttk.Style(self.root)

        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(
            "TTS.TCombobox",
            fieldbackground="#202020",
            background="#202020",
            foreground="#FFFFFF",
            arrowcolor="#FFFFFF",
            bordercolor="#303030",
            lightcolor="#303030",
            darkcolor="#303030",
        )
        style.map(
            "TTS.TCombobox",
            fieldbackground=[("readonly", "#202020")],
            foreground=[("readonly", "#FFFFFF")],
        )

    def _center_window(self, window, width: int | None = None, height: int | None = None):
        window.update_idletasks()

        current_width = width or window.winfo_width() or window.winfo_reqwidth()
        current_height = height or window.winfo_height() or window.winfo_reqheight()

        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()

        pos_x = max(0, (screen_width - current_width) // 2)
        pos_y = max(0, (screen_height - current_height) // 2)

        window.geometry(f"{current_width}x{current_height}+{pos_x}+{pos_y}")

    def _center_child_window(self, child, parent, width: int | None = None, height: int | None = None):
        parent.update_idletasks()
        child.update_idletasks()

        current_width = width or child.winfo_width() or child.winfo_reqwidth()
        current_height = height or child.winfo_height() or child.winfo_reqheight()

        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()

        pos_x = max(0, parent_x + (parent_width - current_width) // 2)
        pos_y = max(0, parent_y + (parent_height - current_height) // 2)

        child.geometry(f"{current_width}x{current_height}+{pos_x}+{pos_y}")

    def _restore_or_center_main_window(self):
        state = self.get_app_state() or {}
        window_state = state.get("window") or {}
        geometry = window_state.get("main_geometry")

        if geometry:
            try:
                self.root.geometry(str(geometry))
                self.root.update_idletasks()
                current_width = max(self.root.winfo_width(), 440)
                expected_height = self._main_window_height()
                current_height = max(self.root.winfo_height(), expected_height)
                if current_height > expected_height:
                    current_height = expected_height
                if current_width != self.root.winfo_width() or current_height != self.root.winfo_height():
                    pos_x = max(0, self.root.winfo_x())
                    pos_y = max(0, self.root.winfo_y())
                    self.root.geometry(f"{current_width}x{current_height}+{pos_x}+{pos_y}")
                return
            except Exception:
                pass

        self._center_window(self.root, width=440, height=self._main_window_height())

    def _save_main_window_geometry(self):
        try:
            geometry = self.root.geometry()
        except Exception:
            return

        state = self.get_app_state() or {}
        state.setdefault("window", {})
        state["window"]["main_geometry"] = geometry
        self.save_app_state(state)

    def _build(self):
        self._configure_styles()

        container = tk.Frame(self.root, bg="#111111")
        container.pack(fill="both", expand=True, padx=24, pady=24)

        title = tk.Label(
            container,
            text="TTS Live",
            font=("Segoe UI", 18, "bold"),
            fg="#FFFFFF",
            bg="#111111"
        )
        title.pack(pady=(0, 18))

        subtitle = tk.Label(
            container,
            text="Selecione as plataformas que deseja iniciar",
            font=("Segoe UI", 10),
            fg="#BBBBBB",
            bg="#111111"
        )
        subtitle.pack(pady=(0, 18))

        self.twitch_button = RoundedToggleButton(
            container,
            text="Twitch",
            width=300,
            height=58,
            radius=18,
            bg_off="#9146FF",
            bg_on="#5E2CA5",
            command=self._open_twitch_menu
        )
        self.twitch_button.pack(pady=(0, 12))

        twitch_status_frame = tk.Frame(container, bg="#111111")
        twitch_status_frame.pack()

        tk.Label(
            twitch_status_frame,
            text="Status Twitch:",
            font=("Segoe UI", 10, "bold"),
            fg="#FFFFFF",
            bg="#111111"
        ).pack(side="left")

        tk.Label(
            twitch_status_frame,
            textvariable=self.twitch_status_var,
            font=("Segoe UI", 10),
            fg="#BBBBBB",
            bg="#111111"
        ).pack(side="left", padx=(6, 0))

        self.youtube_button = RoundedToggleButton(
            container,
            text="YouTube",
            width=300,
            height=58,
            radius=18,
            bg_off="#FF3B30",
            bg_on="#B3261E",
            command=self._open_youtube_menu
        )
        self.youtube_button.pack(pady=(22, 12))

        youtube_status_frame = tk.Frame(container, bg="#111111")
        youtube_status_frame.pack()

        tk.Label(
            youtube_status_frame,
            text="Status YouTube:",
            font=("Segoe UI", 10, "bold"),
            fg="#FFFFFF",
            bg="#111111"
        ).pack(side="left")

        tk.Label(
            youtube_status_frame,
            textvariable=self.youtube_status_var,
            font=("Segoe UI", 10),
            fg="#BBBBBB",
            bg="#111111"
        ).pack(side="left", padx=(6, 0))

        self.kick_button = RoundedToggleButton(
            container,
            text="Kick",
            width=300,
            height=58,
            radius=18,
            bg_off="#32D74B",
            bg_on="#148A2B",
            command=self._open_kick_menu
        )
        self.kick_button.pack(pady=(22, 12))

        kick_status_frame = tk.Frame(container, bg="#111111")
        kick_status_frame.pack()

        tk.Label(
            kick_status_frame,
            text="Status Kick:",
            font=("Segoe UI", 10, "bold"),
            fg="#FFFFFF",
            bg="#111111"
        ).pack(side="left")

        tk.Label(
            kick_status_frame,
            textvariable=self.kick_status_var,
            font=("Segoe UI", 10),
            fg="#BBBBBB",
            bg="#111111",
            wraplength=220,
            justify="left",
        ).pack(side="left", padx=(6, 0))

        audio_frame = tk.Frame(container, bg="#111111")
        audio_frame.pack(fill="x", pady=(20, 0))

        tk.Label(
            audio_frame,
            text="Saida de audio",
            font=("Segoe UI", 10, "bold"),
            fg="#FFFFFF",
            bg="#111111",
        ).pack(anchor="w")

        audio_controls_frame = tk.Frame(audio_frame, bg="#111111")
        audio_controls_frame.pack(fill="x", pady=(8, 0))

        self.audio_output_combo = ttk.Combobox(
            audio_controls_frame,
            textvariable=self.audio_output_var,
            state="readonly",
            values=[],
            width=32,
            style="TTS.TCombobox",
        )
        self.audio_output_combo.pack(side="left", fill="x", expand=True)
        self.audio_output_combo.bind("<<ComboboxSelected>>", self._on_audio_output_selected)

        tk.Button(
            audio_controls_frame,
            text="Atualizar",
            command=lambda: self._refresh_audio_outputs(rescan=True),
            font=("Segoe UI", 9, "bold"),
            bg="#202020",
            fg="#FFFFFF",
            activebackground="#303030",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=(8, 0))

        tk.Button(
            audio_controls_frame,
            text="Testar",
            command=self._test_audio_output,
            font=("Segoe UI", 9, "bold"),
            bg="#202020",
            fg="#FFFFFF",
            activebackground="#303030",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=(8, 0))

        footer_frame = tk.Frame(container, bg="#111111")
        footer_frame.pack(side="bottom", fill="x", pady=(18, 0))

        tk.Label(
            footer_frame,
            text=self._get_version_label_text(),
            font=("Segoe UI", 9),
            fg="#5C5C5C",
            bg="#111111",
            anchor="e",
        ).pack(side="right")

        self._refresh_audio_outputs(show_error=False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _refresh_audio_outputs(self, show_error: bool = True, rescan: bool = False):
        try:
            if rescan:
                devices = self.tts_manager.refresh_audio_output_devices()
            else:
                devices = self.tts_manager.list_audio_output_devices()
            selected_device = self.tts_manager.get_audio_output_device()
        except Exception as exc:
            devices = []
            selected_device = ""
            if show_error:
                messagebox.showerror(
                    "Saida de audio",
                    f"Nao foi possivel listar as saidas de audio:\n\n{exc}",
                    parent=self.root,
                )

        labels = [self.AUDIO_DEFAULT_LABEL]
        self.audio_output_by_label = {self.AUDIO_DEFAULT_LABEL: ""}

        for device in devices:
            labels.append(device)
            self.audio_output_by_label[device] = device

        selected_label = self.AUDIO_DEFAULT_LABEL

        if selected_device:
            if selected_device in self.audio_output_by_label:
                selected_label = selected_device
            else:
                unavailable_label = f"{selected_device} [indisponivel]"
                labels.append(unavailable_label)
                self.audio_output_by_label[unavailable_label] = selected_device
                selected_label = unavailable_label

        self.audio_output_combo["values"] = labels
        self.audio_output_var.set(selected_label)

    def _on_audio_output_selected(self, event=None):
        label = self.audio_output_var.get()
        output_device = self.audio_output_by_label.get(label, "")

        ok, error = self.tts_manager.set_audio_output_device(output_device)

        if not ok:
            messagebox.showerror(
                "Saida de audio",
                f"Nao foi possivel alterar a saida de audio:\n\n{error}",
                parent=self.root,
            )
            self._refresh_audio_outputs(show_error=False)
            return

        active_device = self.tts_manager.get_audio_output_device()
        if active_device != output_device:
            self._refresh_audio_outputs(show_error=False)

    def _test_audio_output(self):
        ok, error = self.tts_manager.play_audio_test()

        if not ok:
            messagebox.showerror(
                "Teste de audio",
                f"Nao foi possivel tocar o teste de audio:\n\n{error}",
                parent=self.root,
            )

    def confirm_twitch_disconnect(self) -> bool:
        return messagebox.askyesno(
            "Desconectar Twitch",
            "Deseja realmente desconectar a Twitch?",
            parent=self.root,
        )

    def _open_twitch_menu(self):
        if self.twitch_bot.is_running():
            self.on_toggle_twitch("stop")
            return

        self._open_platform_start_menu(
            title="Twitch",
            login_label="Entrar com conta Twitch",
            channel_label="Monitorar por nome do canal",
            channel_prompt="Digite o nome do canal da Twitch",
            platform_key="twitch",
            callback=self.on_toggle_twitch,
        )

    def _open_kick_menu(self):
        running = self.kick_bot and self.kick_bot.is_running()
        extra_actions = []

        if running:
            extra_actions.append(("Desligar monitoramento", lambda: self.on_toggle_kick("stop")))

        if self._has_kick_saved_configuration():
            extra_actions.append(("Esquecer conta/canal Kick", self._forget_kick_configuration))

        self._open_platform_start_menu(
            title="Kick",
            login_label="Entrar com conta Kick",
            channel_label="Monitorar por nome do canal",
            channel_prompt="Digite o nome do canal da Kick",
            platform_key="kick",
            callback=self.on_toggle_kick,
            include_start_options=not running,
            extra_actions=extra_actions,
        )

    def _open_platform_start_menu(
        self,
        title: str,
        login_label: str,
        channel_label: str,
        channel_prompt: str,
        platform_key: str,
        callback,
        include_start_options: bool = True,
        extra_actions: list[tuple[str, object]] | None = None,
    ):
        if self.platform_menu_window is not None:
            try:
                self.platform_menu_window.lift()
                self.platform_menu_window.focus_force()
                return
            except Exception:
                self.platform_menu_window = None

        extra_actions = extra_actions or []
        action_count = (2 if include_start_options else 0) + len(extra_actions)
        window_height = max(205, 150 + (action_count * 54))

        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry(f"340x{window_height}")
        window.resizable(False, False)
        window.configure(bg="#111111")
        window.transient(self.root)
        window.grab_set()
        self.platform_menu_window = window
        self._center_child_window(window, self.root, width=340, height=window_height)

        def close_window():
            try:
                window.grab_release()
            except Exception:
                pass
            self.platform_menu_window = None
            window.destroy()

        def choose_login():
            callback("login")

        def choose_channel():
            self._ask_channel_name(
                platform_key=platform_key,
                title=title,
                prompt=channel_prompt,
                callback=callback,
            )

        tk.Label(
            window,
            text=title,
            font=("Segoe UI", 14, "bold"),
            fg="#FFFFFF",
            bg="#111111",
        ).pack(pady=(20, 8))

        tk.Label(
            window,
            text=(
                "Escolha como deseja iniciar o monitoramento"
                if include_start_options
                else "Escolha uma acao"
            ),
            font=("Segoe UI", 10),
            fg="#BBBBBB",
            bg="#111111",
        ).pack(pady=(0, 18 if action_count else 8))

        actions = []
        if include_start_options:
            actions.extend(((login_label, choose_login), (channel_label, choose_channel)))
        actions.extend(extra_actions)

        for label, command in actions:
            tk.Button(
                window,
                text=label,
                command=lambda command=command: [close_window(), command()],
                font=("Segoe UI", 10, "bold"),
                bg="#202020",
                fg="#FFFFFF",
                activebackground="#303030",
                activeforeground="#FFFFFF",
                relief="flat",
                padx=12,
                pady=10,
                cursor="hand2",
            ).pack(fill="x", padx=24, pady=(0, 10))

        tk.Button(
            window,
            text="Fechar",
            command=close_window,
            font=("Segoe UI", 10),
            bg="#2A2A2A",
            fg="#FFFFFF",
            activebackground="#3A3A3A",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=12,
            pady=8,
            cursor="hand2",
        ).pack(pady=(2, 0))

        window.protocol("WM_DELETE_WINDOW", close_window)

    def _has_kick_saved_configuration(self) -> bool:
        saved_channel = bool(self._get_saved_platform_channel("kick"))
        saved_auth = False
        try:
            saved_auth = bool(self.kick_bot and self.kick_bot.has_saved_auth())
        except Exception:
            saved_auth = False
        return saved_channel or saved_auth

    def _forget_kick_configuration(self):
        if not messagebox.askyesno(
            "Esquecer Kick",
            "Deseja esquecer a conta Kick e o canal digitado salvo?",
            parent=self.root,
        ):
            return

        self.on_toggle_kick("forget")

    def _ask_channel_name(self, platform_key: str, title: str, prompt: str, callback):
        default = self._get_saved_platform_channel(platform_key)
        value = simpledialog.askstring(
            title,
            prompt,
            initialvalue=default,
            parent=self.root,
        )
        channel = (value or "").strip()
        if not channel:
            return

        self._save_platform_channel(platform_key, channel)
        callback("channel", channel)

    def _get_saved_platform_channel(self, platform_key: str) -> str:
        state = self.get_app_state() or {}
        platform_state = (state.get("platforms") or {}).get(platform_key) or {}
        return str(platform_state.get("channel_name") or "").strip()

    def _save_platform_channel(self, platform_key: str, channel: str):
        state = self.get_app_state() or {}
        state.setdefault("platforms", {})
        state["platforms"].setdefault(platform_key, {"enabled": False})
        state["platforms"][platform_key]["channel_name"] = channel
        self.save_app_state(state)

    def _open_youtube_menu(self):
        if self.youtube_menu_window is not None:
            try:
                self.youtube_menu_window.lift()
                self.youtube_menu_window.focus_force()
                return
            except Exception:
                self.youtube_menu_window = None

        window = tk.Toplevel(self.root)
        window.title("YouTube")
        window.geometry("420x540")
        window.resizable(False, False)
        window.configure(bg="#111111")
        window.transient(self.root)
        window.grab_set()
        self.youtube_menu_window = window
        self._center_child_window(window, self.root, width=420, height=540)

        def close_window():
            try:
                window.grab_release()
            except Exception:
                pass
            self.youtube_menu_window = None
            window.destroy()

        tk.Label(
            window,
            text="Monitoramento do YouTube",
            font=("Segoe UI", 14, "bold"),
            fg="#FFFFFF",
            bg="#111111",
        ).pack(pady=(18, 8))

        tk.Label(
            window,
            text="Escolha uma ação ou uma conta autenticada",
            font=("Segoe UI", 10),
            fg="#BBBBBB",
            bg="#111111",
        ).pack(pady=(0, 16))

        buttons_frame = tk.Frame(window, bg="#111111")
        buttons_frame.pack(fill="both", expand=True, padx=20)

        def add_action_button(label, callback, top_pad=0):
            button = tk.Button(
                buttons_frame,
                text=label,
                command=lambda: [close_window(), callback()],
                font=("Segoe UI", 10, "bold"),
                bg="#202020",
                fg="#FFFFFF",
                activebackground="#303030",
                activeforeground="#FFFFFF",
                relief="flat",
                padx=12,
                pady=10,
                cursor="hand2",
            )
            button.pack(fill="x", pady=(top_pad, 8))

        add_action_button("Entrar com conta YouTube", lambda: self.on_toggle_youtube("new"))
        add_action_button(
            "Monitorar por nome do canal",
            lambda: self._ask_channel_name(
                platform_key="youtube",
                title="YouTube",
                prompt="Digite o nome, @handle ou URL do canal do YouTube",
                callback=self.on_toggle_youtube,
            ),
        )

        if self._get_saved_platform_channel("youtube"):
            add_action_button("Esquecer canal digitado", self._forget_youtube_saved_channel)

        add_action_button("Desligar monitoramento", lambda: self.on_toggle_youtube("disable"))

        choices = self.youtube_bot.list_account_choices()

        if choices:
            tk.Label(
                buttons_frame,
                text="Contas salvas",
                font=("Segoe UI", 10, "bold"),
                fg="#DDDDDD",
                bg="#111111",
            ).pack(anchor="w", pady=(12, 8))

            for choice in choices:
                label = choice["label"]
                if choice.get("active"):
                    label = f"{label} [ativo]"

                row = tk.Frame(buttons_frame, bg="#111111")
                row.pack(fill="x", pady=(0, 8))

                tk.Button(
                    row,
                    text=f"Usar {label}",
                    command=lambda display_index=choice["display_index"]: [
                        close_window(),
                        self.on_toggle_youtube("select", display_index),
                    ],
                    font=("Segoe UI", 9, "bold"),
                    bg="#202020",
                    fg="#FFFFFF",
                    activebackground="#303030",
                    activeforeground="#FFFFFF",
                    relief="flat",
                    padx=10,
                    pady=9,
                    cursor="hand2",
                ).pack(side="left", fill="x", expand=True)

                tk.Button(
                    row,
                    text="Esquecer",
                    command=lambda display_index=choice["display_index"], label=choice["label"]: [
                        close_window(),
                        self._forget_youtube_account(display_index, label),
                    ],
                    font=("Segoe UI", 9, "bold"),
                    bg="#3A2020",
                    fg="#FFFFFF",
                    activebackground="#4A2828",
                    activeforeground="#FFFFFF",
                    relief="flat",
                    padx=10,
                    pady=9,
                    cursor="hand2",
                ).pack(side="left", padx=(8, 0))
        else:
            tk.Label(
                buttons_frame,
                text="Nenhuma conta autenticada ainda.",
                font=("Segoe UI", 10),
                fg="#BBBBBB",
                bg="#111111",
            ).pack(anchor="w", pady=(12, 8))

        tk.Button(
            window,
            text="Fechar",
            command=close_window,
            font=("Segoe UI", 10),
            bg="#2A2A2A",
            fg="#FFFFFF",
            activebackground="#3A3A3A",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=12,
            pady=8,
            cursor="hand2",
        ).pack(pady=(0, 18))

        window.protocol("WM_DELETE_WINDOW", close_window)

    def _forget_youtube_saved_channel(self):
        if not messagebox.askyesno(
            "Esquecer canal YouTube",
            "Deseja esquecer o canal digitado salvo do YouTube?",
            parent=self.root,
        ):
            return

        self.on_toggle_youtube("forget_channel")

    def _forget_youtube_account(self, display_index: int, label: str):
        if not messagebox.askyesno(
            "Esquecer conta YouTube",
            f"Deseja esquecer esta conta/canal do YouTube?\n\n{label}",
            parent=self.root,
        ):
            return

        self.on_toggle_youtube("forget_account", display_index)

    def _schedule_refresh(self):
        twitch_status = self.twitch_bot.get_status()
        youtube_status = self.youtube_bot.get_status()
        kick_status = self.kick_bot.get_status() if self.kick_bot else "desconectado"

        self.twitch_status_var.set(self._format_status(twitch_status))
        self.youtube_status_var.set(self._format_status(youtube_status))
        self.kick_status_var.set(self._format_status(kick_status))

        self.twitch_button.set_state(twitch_status.startswith("monitorando") or twitch_status == "conectado")
        self.youtube_button.set_state(youtube_status.startswith("monitorando") or youtube_status == "conectado")
        self.kick_button.set_state(self.kick_bot.is_running() if self.kick_bot else False)

        self.root.after(1000, self._schedule_refresh)

    def _format_status(self, status: str) -> str:
        return (status or "desconectado").replace("_", " ")

    def _on_close(self):
        self._save_main_window_geometry()

        try:
            if self.twitch_bot.is_running():
                self.twitch_bot.stop()
        except Exception:
            pass

        try:
            if self.youtube_bot.is_running():
                self.youtube_bot.stop()
        except Exception:
            pass

        try:
            if self.kick_bot and self.kick_bot.is_running():
                self.kick_bot.stop()
        except Exception:
            pass

        self.root.after(100, self.root.destroy)

    def run(self):
        self.root.mainloop()
