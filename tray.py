"""System tray integration using pystray."""
import os
import sys
import threading
from pathlib import Path

import pystray
from PIL import Image


def _icon_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    return base / "icons" / "bash_icons_red.ico"


def start_tray(on_show, on_exit) -> pystray.Icon:
    """Start the system tray icon in a background thread. Returns the Icon instance."""
    image = Image.open(_icon_path())

    menu = pystray.Menu(
        pystray.MenuItem("Show Download Window", lambda icon, item: on_show(), default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", lambda icon, item: on_exit()),
    )

    icon = pystray.Icon(
        name="WryeBashNXMDownloader",
        icon=image,
        title="Wrye Bash Nexus Downloader",
        menu=menu,
    )

    threading.Thread(target=icon.run, daemon=True).start()
    return icon
