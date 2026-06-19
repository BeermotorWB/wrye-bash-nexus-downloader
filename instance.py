"""Single-instance gate using Windows mutex + TCP IPC."""
import ctypes
import socket
import threading
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MUTEX_NAME = "WryeBashNXMDownloader_SingleInstance"
IPC_PORT = 29717
ERROR_ALREADY_EXISTS = 183

_mutex_handle = None
_listener: socket.socket | None = None
_on_receive = None
_lock = threading.Lock()


def set_receive_handler(handler):
    global _on_receive
    with _lock:
        _on_receive = handler


def try_be_primary() -> bool:
    """Attempt to acquire the single-instance mutex. Returns True if primary."""
    global _mutex_handle
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return False
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    _start_listener()
    return True


def send_to_primary(url: str) -> bool:
    """Send a URL to the running primary instance. Returns True on success."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", IPC_PORT))
        sock.sendall((url + "\n").encode("utf-8"))
        sock.close()
        return True
    except OSError:
        return False


def release_primary():
    """Release mutex and stop listener."""
    global _mutex_handle, _listener
    if _listener:
        try:
            _listener.close()
        except OSError:
            pass
        _listener = None
    if _mutex_handle:
        kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None


def _start_listener():
    global _listener
    try:
        _listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _listener.bind(("127.0.0.1", IPC_PORT))
        _listener.listen(5)
        threading.Thread(target=_accept_loop, daemon=True).start()
    except OSError:
        _listener = None


def _accept_loop():
    while _listener:
        try:
            conn, _ = _listener.accept()
            threading.Thread(target=_handle_conn, args=(conn,), daemon=True).start()
        except OSError:
            break


def _handle_conn(conn: socket.socket):
    try:
        data = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        for line in data.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                with _lock:
                    handler = _on_receive
                if handler:
                    handler(line)
    except OSError:
        pass
    finally:
        conn.close()
