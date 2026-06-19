"""Windows registry operations for nxm:// and modl:// protocol handler registration."""
import os
import sys
import winreg

_REG_BASE_NXM = r"Software\Classes\nxm"
_REG_BASE_MODL = r"Software\Classes\modl"


def _exe_path() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(sys.argv[0])


def register() -> None:
    _register_protocol(_REG_BASE_NXM, "URL:NXM Protocol")


def deregister() -> None:
    _delete_key_tree(_REG_BASE_NXM)


def is_registered() -> bool:
    return _check_registered(_REG_BASE_NXM)


def register_modl() -> None:
    _register_protocol(_REG_BASE_MODL, "URL:MODL Protocol")


def deregister_modl() -> None:
    _delete_key_tree(_REG_BASE_MODL)


def is_modl_registered() -> bool:
    return _check_registered(_REG_BASE_MODL)


def _register_protocol(base: str, description: str) -> None:
    exe = _exe_path()
    cmd = f'"{exe}" "%1"'

    key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, base, 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, description)
    winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    winreg.CloseKey(key)

    cmd_key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command", 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd)
    winreg.CloseKey(cmd_key)


def _check_registered(base: str) -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command", 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, "")
        winreg.CloseKey(key)
        exe = _exe_path()
        return exe.lower() in val.lower()
    except OSError:
        return False


def _delete_key_tree(path: str) -> None:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ)
        subkeys = []
        i = 0
        while True:
            try:
                subkeys.append(winreg.EnumKey(key, i))
                i += 1
            except OSError:
                break
        winreg.CloseKey(key)
        for sub in subkeys:
            _delete_key_tree(path + "\\" + sub)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        pass
