import sys

from config import load_config
from overlay import Overlay
from tray import TrayManager


def main():
    config = load_config()
    overlay = Overlay(config)
    tray = TrayManager(overlay)
    tray.start()
    overlay.run()


if __name__ == "__main__":
    main()
