"""Windows 任务栏进度条（ITaskbarList3）。

为什么值得花这个力气：任务栏上的绿色进度条是"这真是个桌面程序"最直观的信号，
而且在窗口被切到后台时，用户不用切回来就能知道转码还剩多少。这是浏览器里的
应用**做不到**的事——它恰好是第 6 条要求想要的那种"客户端基因"。

实现代价是不用任何第三方库：ctypes 直接走 COM，按 vtable 索引调方法。
失败一律静默降级（非 Windows、COM 不可用、窗口句柄还没创建），
绝不能让"一个进度条"把主流程带崩。
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import POINTER, c_ubyte, c_ulong, c_ushort, c_void_p
from uuid import UUID

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

# TBPFLAG
STATE_NONE = 0
STATE_INDETERMINATE = 1
STATE_NORMAL = 2
STATE_ERROR = 4
STATE_PAUSED = 8

CLSID_TASKBAR_LIST = "{56FDF344-FD6D-11D0-958A-006097C9A090}"
IID_TASKBAR_LIST3 = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEA84}"

# vtable 索引（去掉 IUnknown 的 3 个）
_IDX_HR_INIT = 3
_IDX_SET_PROGRESS_VALUE = 9
_IDX_SET_PROGRESS_STATE = 10


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", c_ulong),
        ("Data2", c_ushort),
        ("Data3", c_ushort),
        ("Data4", c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, text: str) -> "_GUID":
        u = UUID(text)
        g = cls()
        g.Data1, g.Data2, g.Data3 = u.time_low, u.time_mid, u.time_hi_version
        g.Data4 = (c_ubyte * 8)(*u.bytes[8:])
        return g


def _call(ptr: c_void_p, index: int, argtypes: list | None, *args):
    """按 vtable 索引调 COM 方法。"""
    vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, *(argtypes or []))
    return proto(vtable[index])(ptr, *args)


class TaskbarProgress:
    """任务栏进度条。所有方法都是"尽力而为"，失败不抛异常。"""

    def __init__(self) -> None:
        self._ptr: c_void_p | None = None
        self._hwnd: int | None = None
        self._tried = False

    # ---------- 内部 ----------
    def _ensure(self, hwnd: int) -> bool:
        if self._ptr is not None:
            return True
        if not IS_WINDOWS or self._tried:
            return False
        self._tried = True
        try:
            ole32 = ctypes.windll.ole32
            ole32.CoInitialize(None)
            clsid = _GUID.parse(CLSID_TASKBAR_LIST)
            iid = _GUID.parse(IID_TASKBAR_LIST3)
            ptr = c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(clsid), None, 1,  # CLSCTX_INPROC_SERVER
                ctypes.byref(iid), ctypes.byref(ptr),
            )
            if hr != 0 or not ptr:
                # 注意：某些环境（受限会话、虚拟机、被沙箱拦截的 COM）拿不到
                # ITaskbarList3，会返回 E_NOINTERFACE(0x80004002)。这不是致命问题，
                # 但没有进度条就是没有，日志里必须说清楚，不能静默当成功。
                log.info(
                    "任务栏进度不可用（COM 未暴露 ITaskbarList3，hr=0x%08X）；"
                    "转码本身不受影响",
                    hr & 0xFFFFFFFF,
                )
                return False
            _call(ptr, _IDX_HR_INIT, None)
            self._ptr = ptr
            self._hwnd = int(hwnd)
            return True
        except Exception as exc:  # noqa: BLE001 - 进度条失败绝不能影响转码
            log.debug("任务栏进度不可用：%s", exc)
            return False

    # ---------- 对外 ----------
    def set_value(self, hwnd: int, percent: float) -> None:
        if not self._ensure(hwnd):
            return
        try:
            value = max(0, min(100, int(round(percent))))
            _call(self._ptr, _IDX_SET_PROGRESS_VALUE, [c_void_p, c_ulong, c_ulong],
                  self._hwnd, value, 100)
        except Exception:  # noqa: BLE001
            pass

    def set_state(self, hwnd: int, state: int) -> None:
        if not self._ensure(hwnd):
            return
        try:
            _call(self._ptr, _IDX_SET_PROGRESS_STATE, [c_void_p, ctypes.c_int],
                  self._hwnd, state)
        except Exception:  # noqa: BLE001
            pass

    def clear(self) -> None:
        if self._ptr is None:
            return
        try:
            _call(self._ptr, _IDX_SET_PROGRESS_STATE, [c_void_p, ctypes.c_int],
                  self._hwnd, STATE_NONE)
        except Exception:  # noqa: BLE001
            pass
