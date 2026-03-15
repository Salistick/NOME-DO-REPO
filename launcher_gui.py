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
            label = f"✔ {self.base_text}"
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

        self._build()
        self._schedule_refresh()

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

        twitch_status_title = tk.Label(
            twitch_status_frame,
            text="Status Twitch:",
            font=("Segoe UI", 10, "bold"),
            fg="#FFFFFF",
            bg="#111111"
        )
        twitch_status_title.pack(side="left")

        twitch_status_value = tk.Label(
            twitch_status_frame,
            textvariable=self.twitch_status_var,
            font=("Segoe UI", 10),
            fg="#BBBBBB",
            bg="#111111"
        )
        twitch_status_value.pack(side="left", padx=(6, 0))

        self.youtube_button = RoundedToggleButton(
            container,
            text="YouTube",
            width=300,
            height=58,
            radius=18,
            bg_off="#FF3B30",
            bg_on="#B3261E",
            command=self.on_toggle_youtube
        )
        self.youtube_button.pack(pady=(22, 12))

        youtube_status_frame = tk.Frame(container, bg="#111111")
        youtube_status_frame.pack()

        youtube_status_title = tk.Label(
            youtube_status_frame,
            text="Status YouTube:",
            font=("Segoe UI", 10, "bold"),
            fg="#FFFFFF",
            bg="#111111"
        )
        youtube_status_title.pack(side="left")

        youtube_status_value = tk.Label(
            youtube_status_frame,
            textvariable=self.youtube_status_var,
            font=("Segoe UI", 10),
            fg="#BBBBBB",
            bg="#111111"
        )
        youtube_status_value.pack(side="left", padx=(6, 0))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def confirm_twitch_disconnect(self) -> bool:
        return messagebox.askyesno(
            "Desconectar Twitch",
            "Deseja realmente desconectar a Twitch e esquecer a autenticação salva?\n\nNa próxima conexão, o login no navegador será solicitado novamente."
        )

    def confirm_youtube_disconnect(self) -> bool:
        return messagebox.askyesno(
            "Desconectar YouTube",
            "Deseja realmente desconectar o YouTube?\n\nA autenticação salva continuará disponível para reconexão futura."
        )

    def _schedule_refresh(self):
        twitch_status = self.twitch_bot.get_status()
        youtube_status = self.youtube_bot.get_status()

        self.twitch_status_var.set(twitch_status)
        self.youtube_status_var.set(youtube_status)

        self.twitch_button.set_state(twitch_status == "conectado")
        self.youtube_button.set_state(youtube_status == "conectado")

        self.root.after(500, self._schedule_refresh)

    def _on_close(self):
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
