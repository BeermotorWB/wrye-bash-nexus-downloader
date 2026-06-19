"""Wrye Bash Nexus Downloader — Python port entrypoint."""
import os
import sys
import threading

import webview

from api import Api
from config import Config
import instance
import tray


def get_frontend_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "frontend")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")


def main():
    args = sys.argv[1:]

    # Handle CLI flags
    if args:
        flag = args[0].lower()
        if flag == "--register":
            import registry
            registry.register()
            print("Registered as nxm:// protocol handler.")
            return
        elif flag == "--deregister":
            import registry
            registry.deregister()
            print("Deregistered nxm:// protocol handler.")
            return
        elif flag == "--register-modl":
            import registry
            registry.register_modl()
            print("Registered as modl:// protocol handler.")
            return
        elif flag == "--deregister-modl":
            import registry
            registry.deregister_modl()
            print("Deregistered modl:// protocol handler.")
            return

    # Detect nxm:// or modl:// URL in argv
    link_url = ""
    for arg in args:
        lower = arg.lower()
        if lower.startswith("nxm://") or lower.startswith("modl://"):
            link_url = arg
            break

    # Single-instance gate
    is_primary = instance.try_be_primary()
    if not is_primary:
        if link_url:
            instance.send_to_primary(link_url)
        return

    # Load config
    cfg = Config.load()

    # Window reference (mutable list so Api can access it)
    window_ref = []
    api = Api(cfg, window_ref)

    # IPC handler: when secondary sends a URL
    def on_ipc_receive(url: str):
        lower = url.lower()
        if lower.startswith("modl://"):
            api.handle_modl_url(url)
        elif lower.startswith("nxm://"):
            api.handle_nxm_url(url)
        w = window_ref[0] if window_ref else None
        if w:
            w.show()

    instance.set_receive_handler(on_ipc_receive)

    # Handle initial link after window loads
    def on_loaded():
        if link_url:
            lower = link_url.lower()
            if lower.startswith("modl://"):
                api.handle_modl_url(link_url)
            else:
                api.handle_nxm_url(link_url)

    # Create window
    frontend_dir = get_frontend_dir()
    window = webview.create_window(
        title="Wrye Bash Nexus Downloader",
        url=os.path.join(frontend_dir, "index.html"),
        js_api=api,
        width=800,
        height=500,
        min_size=(600, 300),
    )
    window_ref.append(window)

    # Close handler
    def on_closing():
        if cfg.minimize_to_tray:
            window.hide()
            return False  # prevent close
        instance.release_primary()
        return True  # allow close

    window.events.closing += on_closing
    window.events.loaded += on_loaded

    # Start tray
    def show_window():
        window.show()
        from focus import bring_to_front
        bring_to_front()

    def exit_app():
        instance.release_primary()
        os._exit(0)

    tray.start_tray(on_show=show_window, on_exit=exit_app)

    # Start webview (blocks)
    webview.start(debug=False)

    # Cleanup
    instance.release_primary()


if __name__ == "__main__":
    main()
