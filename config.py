import json
import os
from dataclasses import dataclass, asdict

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
