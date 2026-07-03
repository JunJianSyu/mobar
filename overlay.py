import tkinter as tk
import ctypes
import sys

from config import Config
from collector import collect

COLOR_BG = "#1a1a2e"
COLOR_NORMAL = "#a0d8ef"
COLOR_WARN = "#ffd93d"
COLOR_CRIT = "#ff6b6b"
FONT = ("Consolas", 11)


class Overlay:
    def __init__(self, config: Config):
        self.config = config
        self.root = tk.Tk()
        self.root.title("MoBar")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", config.opacity)
        self.root.configure(bg=COLOR_BG)
        self._frame = tk.Frame(self.root, bg=COLOR_BG, padx=8, pady=1)
        self._frame.pack()

        self._labels: list[tk.Label] = []

        metrics = ["CPU --%", "GPU --%", "MEM --%", "CPU --°", "GPU --°"]
        for i, text in enumerate(metrics):
            if i > 0:
                sep = tk.Label(
                    self._frame, text="·", font=FONT,
                    fg=COLOR_NORMAL, bg=COLOR_BG,
                )
                sep.pack(side=tk.LEFT, padx=4)
            lbl = tk.Label(
                self._frame, text=text, font=FONT,
                fg=COLOR_NORMAL, bg=COLOR_BG,
            )
            lbl.pack(side=tk.LEFT)
            self._labels.append(lbl)

        self._prev: list[tuple[str, str]] = [("", "")] * 5
        self._hidden = False

        self.root.withdraw()
        self.root.after(100, self._on_ready)

    def _apply_position(self):
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        screen_w = self.root.winfo_screenwidth()
        margin = 8
        pos = self.config.position
        if pos == "top-center":
            x = (screen_w - w) // 2
        elif pos == "top-right":
            x = screen_w - w - margin
        else:
            x = margin
        self.root.geometry(f"+{x}+{margin}")

    def _on_ready(self):
        self._set_tool_window()
        self._apply_position()
        self.root.deiconify()
        self._schedule_update()

    def _set_tool_window(self):
        if sys.platform != "win32":
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x80)
        except Exception:
            pass

    def _color_for_value(self, value: float) -> str:
        if value >= self.config.temp_crit:
            return COLOR_CRIT
        if value >= self.config.temp_warn:
            return COLOR_WARN
        return COLOR_NORMAL

    def _fmt_pct(self, label: str, v: float) -> tuple[str, str]:
        if v < 0:
            return f"{label} --%", COLOR_NORMAL
        return f"{label} {v:.0f}%", self._color_for_value(v)

    def _fmt_temp(self, label: str, v: int) -> tuple[str, str]:
        if v < 0:
            return f"{label} --°", COLOR_NORMAL
        return f"{label} {v}°", self._color_for_value(v)

    def _update(self):
        s = collect()
        items = [
            self._fmt_pct("CPU", s.cpu_percent),
            self._fmt_pct("GPU", s.gpu_percent),
            self._fmt_pct("MEM", s.mem_percent),
            self._fmt_temp("CPU", s.cpu_temp),
            self._fmt_temp("GPU", s.gpu_temp),
        ]
        for i, (text, color) in enumerate(items):
            if self._prev[i] != (text, color):
                self._labels[i].configure(text=text, fg=color)
                self._prev[i] = (text, color)

        self._schedule_update()

    def _schedule_update(self):
        self.root.after(self.config.refresh_interval * 1000, self._update)

    def toggle_visibility(self):
        if self._hidden:
            self.root.deiconify()
        else:
            self.root.withdraw()
        self._hidden = not self._hidden

    def quit(self):
        self.root.quit()

    def run(self):
        self.root.mainloop()
