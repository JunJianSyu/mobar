from __future__ import annotations

import ctypes
import json
import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, asdict
from pathlib import Path

import psutil
from PIL import Image, ImageDraw
import pystray
import tkinter as tk


# ===========================================================================
# Config
# ===========================================================================
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", "."), "mobar")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "refresh_interval": 2,
    "temp_warn": 70,
    "temp_crit": 85,
    "position": "top-center",
    "opacity": 0.85,
}


@dataclass
class Config:
    refresh_interval: int = 2
    temp_warn: int = 70
    temp_crit: int = 85
    position: str = "top-center"
    opacity: float = 0.85

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)


def load_config() -> Config:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = {**DEFAULTS, **data}
            return Config(**{k: merged[k] for k in DEFAULTS})
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
    cfg = Config()
    cfg.save()
    return cfg


# ===========================================================================
# Logging
# ===========================================================================
def _setup_logging():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    log_path = os.path.join(CONFIG_DIR, "mobar.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )


logger = logging.getLogger("mobar")


# ===========================================================================
# Collector — hardware monitoring
# ===========================================================================
_nvml_available = False
_nvml_handle = None
_pynvml = None

_nvidia_smi_available = False
_nvidia_smi_path: str | None = None

_wmi_available = False
_wmi_conn = None
_wmi_thermal_instances: list = []


def _init_nvml():
    global _nvml_available, _nvml_handle, _pynvml
    try:
        import pynvml
        _pynvml = pynvml
        _pynvml.nvmlInit()
        _nvml_handle = _pynvml.nvmlDeviceGetHandleByIndex(0)
        _nvml_available = True
        logger.info("NVML initialized successfully")
    except Exception as e:
        _nvml_available = False
        logger.warning("NVML init failed: %s — will try nvidia-smi fallback", e)


def _init_nvidia_smi():
    """Locate nvidia-smi.exe and verify it works."""
    global _nvidia_smi_available, _nvidia_smi_path
    candidates = ["nvidia-smi"]
    sys32 = Path(r"C:\Windows\System32")
    if sys32.exists():
        candidates.append(str(sys32 / "nvidia-smi.exe"))
    prog_files = Path(r"C:\Program Files\NVIDIA Corporation\NVSMI")
    if prog_files.exists():
        candidates.append(str(prog_files / "nvidia-smi.exe"))

    for path in candidates:
        try:
            result = subprocess.run(
                [path, "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            if result.returncode == 0 and result.stdout.strip():
                _nvidia_smi_path = path
                _nvidia_smi_available = True
                logger.info("nvidia-smi fallback available at: %s", path)
                return
        except Exception as e:
            logger.debug("nvidia-smi probe failed for %s: %s", path, e)

    logger.warning("nvidia-smi not found — GPU monitoring unavailable")


def _nvidia_smi_query(query: str) -> str | None:
    """Run nvidia-smi with a specific query and return stripped stdout."""
    if not _nvidia_smi_available or not _nvidia_smi_path:
        return None
    try:
        result = subprocess.run(
            [_nvidia_smi_path, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        if result.returncode == 0:
            val = result.stdout.strip().split("\n")[0].strip()
            if val and val != "[Not Supported]":
                return val
    except Exception as e:
        logger.debug("nvidia-smi query failed (%s): %s", query, e)
    return None


def _init_wmi():
    global _wmi_available, _wmi_conn, _wmi_thermal_instances
    try:
        import wmi
        _wmi_conn = wmi.WMI(namespace="root\\wmi")
        _wmi_available = True
        try:
            sensors = _wmi_conn.MSAcpi_ThermalZoneTemperature()
            for i, s in enumerate(sensors):
                temp_c = int(s.CurrentTemperature / 10 - 273.15)
                if 0 <= temp_c <= 120:
                    _wmi_thermal_instances.append(i)
            if _wmi_thermal_instances:
                logger.info(
                    "WMI thermal zones found: %s (°C: %s)",
                    _wmi_thermal_instances,
                    [int(sensors[i].CurrentTemperature / 10 - 273.15)
                     for i in _wmi_thermal_instances],
                )
            else:
                logger.info("WMI thermal zones found but no sensible values")
        except Exception as e:
            logger.info("MSAcpi_ThermalZoneTemperature query failed: %s", e)
    except Exception as e:
        _wmi_available = False
        logger.warning("WMI init failed: %s — CPU temp unavailable", e)


def _init_collectors():
    """Initialize all hardware collectors."""
    _init_nvml()
    if not _nvml_available:
        _init_nvidia_smi()
    _init_wmi()
    if not _wmi_available and not _wmi_thermal_instances:
        logger.info("CPU temperature monitoring unavailable")


@dataclass(slots=True)
class HWStatus:
    cpu_percent: float = 0.0
    gpu_percent: float = -1.0
    mem_percent: float = 0.0
    cpu_temp: int = -1
    gpu_temp: int = -1


def _get_cpu_temp() -> int:
    if not _wmi_available:
        return -1
    try:
        sensors = _wmi_conn.MSAcpi_ThermalZoneTemperature()
        for idx in _wmi_thermal_instances:
            if idx < len(sensors):
                temp_c = int(sensors[idx].CurrentTemperature / 10 - 273.15)
                if 0 <= temp_c <= 120:
                    return temp_c
        if sensors:
            temp_c = int(sensors[0].CurrentTemperature / 10 - 273.15)
            if 0 <= temp_c <= 120:
                return temp_c
    except Exception as e:
        logger.debug("CPU temp read failed: %s", e)
    return -1


def _get_gpu_usage() -> float:
    if _nvml_available:
        try:
            return float(_pynvml.nvmlDeviceGetUtilizationRates(_nvml_handle).gpu)
        except Exception as e:
            logger.debug("NVML GPU usage read failed: %s", e)
    val = _nvidia_smi_query("utilization.gpu")
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
    return -1.0


def _get_gpu_temp() -> int:
    if _nvml_available:
        try:
            return _pynvml.nvmlDeviceGetTemperature(
                _nvml_handle, _pynvml.NVML_TEMPERATURE_GPU
            )
        except Exception as e:
            logger.debug("NVML GPU temp read failed: %s", e)
    val = _nvidia_smi_query("temperature.gpu")
    if val is not None:
        try:
            return int(float(val))
        except ValueError:
            pass
    return -1


def collect() -> HWStatus:
    return HWStatus(
        cpu_percent=psutil.cpu_percent(interval=0),
        gpu_percent=_get_gpu_usage(),
        mem_percent=psutil.virtual_memory().percent,
        cpu_temp=_get_cpu_temp(),
        gpu_temp=_get_gpu_temp(),
    )


# ===========================================================================
# Overlay
# ===========================================================================
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


# ===========================================================================
# Tray
# ===========================================================================
def _create_icon_image() -> Image.Image:
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([1, 1, 14, 14], radius=3, fill="#a0d8ef")
    draw.rectangle([3, 6, 5, 12], fill="#1a1a2e")
    draw.rectangle([7, 4, 9, 12], fill="#1a1a2e")
    draw.rectangle([11, 8, 13, 12], fill="#1a1a2e")
    return img


class TrayManager:
    def __init__(self, overlay: Overlay):
        self._overlay = overlay
        self._icon = pystray.Icon(
            "mobar",
            icon=_create_icon_image(),
            title="MoBar",
            menu=pystray.Menu(
                pystray.MenuItem(
                    "Show/Hide", self._on_toggle, default=True,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._on_quit),
            ),
        )

    def _on_toggle(self, icon, item):
        self._overlay.root.after(0, self._overlay.toggle_visibility)

    def _on_quit(self, icon, item):
        icon.stop()
        self._overlay.root.after(0, self._overlay.quit)

    def start(self):
        thread = threading.Thread(target=self._icon.run, daemon=True)
        thread.start()

    def stop(self):
        self._icon.stop()


# ===========================================================================
# Main
# ===========================================================================
def main():
    _setup_logging()
    _init_collectors()
    config = load_config()
    overlay = Overlay(config)
    tray = TrayManager(overlay)
    tray.start()
    overlay.run()


if __name__ == "__main__":
    main()
