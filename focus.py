"""Win32 window focus helpers."""
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

FindWindowW = user32.FindWindowW
FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
FindWindowW.restype = wintypes.HWND

GetForegroundWindow = user32.GetForegroundWindow
GetForegroundWindow.restype = wintypes.HWND

SetForegroundWindow = user32.SetForegroundWindow
SetForegroundWindow.argtypes = [wintypes.HWND]

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
GetWindowThreadProcessId.restype = wintypes.DWORD

AttachThreadInput = user32.AttachThreadInput
AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]

GetCurrentThreadId = kernel32.GetCurrentThreadId
GetCurrentThreadId.restype = wintypes.DWORD

ShowWindow = user32.ShowWindow
ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
SW_RESTORE = 9


def bring_to_front(title: str = "Wrye Bash Nexus Downloader"):
    """Force the application window to the foreground."""
    hwnd = FindWindowW(None, title)
    if not hwnd:
        return

    ShowWindow(hwnd, SW_RESTORE)

    foreground = GetForegroundWindow()
    if not foreground:
        SetForegroundWindow(hwnd)
        return

    fore_thread = GetWindowThreadProcessId(foreground, None)
    cur_thread = GetCurrentThreadId()

    if fore_thread != cur_thread:
        AttachThreadInput(cur_thread, fore_thread, True)
        SetForegroundWindow(hwnd)
        AttachThreadInput(cur_thread, fore_thread, False)
    else:
        SetForegroundWindow(hwnd)
