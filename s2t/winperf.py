"""Windows 11 applies EcoQoS power throttling to background processes, which can slow
LM Studio's headless inference service ~20x (observed: identical requests taking 6s or
124s). This module force-disables execution-speed throttling and raises the priority of
all LM Studio processes. Same-user access only; failures are harmless (best effort)."""

import ctypes
import logging
import subprocess
from ctypes import wintypes

log = logging.getLogger(__name__)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_PROCESS_SET_INFORMATION = 0x0200
_ABOVE_NORMAL_PRIORITY_CLASS = 0x8000
_ProcessPowerThrottling = 4
_PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1


class _POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", wintypes.ULONG),
                ("ControlMask", wintypes.ULONG),
                ("StateMask", wintypes.ULONG)]


def _unthrottle_pid(pid: int) -> bool:
    handle = _kernel32.OpenProcess(_PROCESS_SET_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        # ControlMask = EXECUTION_SPEED with StateMask = 0 forces throttling OFF
        state = _POWER_THROTTLING_STATE(1, _PROCESS_POWER_THROTTLING_EXECUTION_SPEED, 0)
        ok = _kernel32.SetProcessInformation(
            handle, _ProcessPowerThrottling, ctypes.byref(state), ctypes.sizeof(state))
        _kernel32.SetPriorityClass(handle, _ABOVE_NORMAL_PRIORITY_CLASS)
        return bool(ok)
    finally:
        _kernel32.CloseHandle(handle)


def unthrottle_lmstudio():
    try:
        out = subprocess.run(
            'tasklist /FI "IMAGENAME eq LM Studio.exe" /FO CSV /NH',
            capture_output=True, text=True, shell=True, timeout=30,
        ).stdout
        pids = [int(line.split('","')[1]) for line in out.strip().splitlines() if '","' in line]
        done = [pid for pid in pids if _unthrottle_pid(pid)]
        if done:
            log.info("Disabled power throttling for %d LM Studio process(es)", len(done))
    except Exception as exc:
        log.debug("Could not adjust LM Studio process throttling (%s)", exc)
