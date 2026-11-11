"""Start Meerkat when the user signs in to Windows, and allow only one running copy.

Autostart uses the per-user ``Run`` registry key (no admin rights needed). It runs the
``.exe`` when frozen, or ``pythonw -m meerkat`` (no console window) from source.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from pathlib import Path

from meerkat import paths

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Meerkat"
MUTEX_NAME = "Local\\MeerkatPostureSingleInstance"

_mutex_handles: list[int] = []  # held for the life of the process


def supported() -> bool:
    return sys.platform == "win32"


def command() -> str:
    if paths.is_frozen():
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return f'"{pythonw if pythonw.exists() else exe}" -m meerkat'


def is_enabled() -> bool:
    if not supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> bool:
    """Turn autostart on/off. Returns the new state."""
    if not supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
                log.info("autostart on: %s", command())
            else:
                with contextlib.suppress(FileNotFoundError):
                    winreg.DeleteValue(key, VALUE_NAME)
                log.info("autostart off")
    except OSError:
        log.exception("cannot change autostart")
    return is_enabled()


def acquire_single_instance(name: str = MUTEX_NAME) -> bool:
    """True if this is the only process holding ``name``. Keep the process alive to hold it."""
    if not supported():
        return True
    import ctypes

    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return True  # can't tell; don't block startup
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return False
    _mutex_handles.append(handle)
    return True
