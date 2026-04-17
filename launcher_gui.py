import tkinter as tk
from tkinter import messagebox


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
    def __init__(
        self,
        twitch_bot,
        youtube_bot,
        on_toggle_twitch,
        on_toggle_youtube,
        get_app_state,
        save_app_state,
    ):
        self.twitch_bot = twitch_bot
        self.youtube_bot = youtube_bot
        self.on_toggle_twitch = on_toggle_twitch
        self.on_toggle_youtube = on_toggle_youtube
        self.get_app_state = get_app_state
        self.save_app_state = save_app_state

        self.root = tk.Tk()
        self.root.title("TTS Live")
        self.root.geometry("440x400")
        self.root.resizable(False, False)
        self.root.configure(bg="#111111")

        self.twitch_status_var = tk.StringVar(value="desconectado")
        self.youtube_status_var = tk.StringVar(value="desconectado")
        self.youtube_menu_window = None

        self._build()
        self._restore_or_center_main_window()
        self._schedule_refresh()

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
                return
            except Exception:
                pass

        self._center_window(self.root, width=440, height=400)

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
            command=self.on_toggle_twitch
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

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def confirm_twitch_disconnect(self) -> bool:
        return messagebox.askyesno(
            "Desconectar Twitch",
            "Deseja realmente desconectar a Twitch e esquecer a autenticação salva?\n\nNa proxima conexão, o login no navegador sera solicitado novamente.",
            parent=self.root,
        )

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
        window.geometry("360x420")
        window.resizable(False, False)
        window.configure(bg="#111111")
        window.transient(self.root)
        window.grab_set()
        self.youtube_menu_window = window
        self._center_child_window(window, self.root, width=360, height=420)

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

        add_action_button("Conectar nova conta", lambda: self.on_toggle_youtube("new"))
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

                add_action_button(
                    label,
                    lambda display_index=choice["display_index"]: self.on_toggle_youtube("select", display_index),
                )
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

    def _schedule_refresh(self):
        twitch_status = self.twitch_bot.get_status()
        youtube_status = self.youtube_bot.get_status()

        self.twitch_status_var.set(self._format_status(twitch_status))
        self.youtube_status_var.set(self._format_status(youtube_status))

        self.twitch_button.set_state(twitch_status.startswith("monitorando") or twitch_status == "conectado")
        self.youtube_button.set_state(youtube_status.startswith("monitorando") or youtube_status == "conectado")

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

        self.root.after(100, self.root.destroy)

    def run(self):
        self.root.mainloop()
