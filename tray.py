import threading

from PIL import Image, ImageDraw
import pystray

from overlay import Overlay


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
