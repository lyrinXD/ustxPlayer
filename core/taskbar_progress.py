"""Windows 任务栏进度条（ITaskbarList3，纯 ctypes 调用）。

关键坑：ITaskbarList3 的 IID 是
{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}（末尾 8A5EEFAF）。
网上不少资料写成 ...8A5EEAAF（EAAF）是错的，QI 必然 E_NOINTERFACE；
微软 WPF 源码 PresentationFramework.dll 里也是 EFAF。

设计要点：
- 进度直通不过滤：导出帧进度单调递增，指数平滑反而造成滞后；
- 状态机：准备阶段（value=None）-> 转圈，进行中 -> 正常进度，完成/无任务 -> 清除；
- 正常进度每次写 State+Value（10Hz 更新，COM 调用开销可忽略）；
- 所有 COM 调用失败只记日志并停用，绝不干扰主流程。
"""

from __future__ import annotations

import ctypes

from core.log import logger

from ctypes import (
    POINTER, Structure, WINFUNCTYPE, byref, c_int, c_ubyte,
    c_ulonglong, c_void_p, cast, windll,
)
from ctypes import wintypes


class _GUID(Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", c_ubyte * 8),
    ]


# COM 标识符（GUID 直接写成字节）：
# - CLSID_TaskbarList：任务栏进度条 COM 组件的类 ID
# - IID_ITaskbarList3：所需接口的 ID（末尾 8A5EEFAF）
# - IID_IUnknown：标准接口 ID，CoCreateInstance 只按它取回 IUnknown，
#   之后再用 QueryInterface 换 ITaskbarList3
_CLSID_TASKBAR_LIST = _GUID(
    0x56FDF344, 0xFD6D, 0x11D0,
    (0x95, 0x8A, 0x00, 0x60, 0x97, 0xC9, 0xA0, 0x90))
_IID_ITASKBAR_LIST3 = _GUID(
    0xEA1AFB91, 0x9E28, 0x4B86,
    (0x90, 0xE9, 0x9E, 0x9F, 0x8A, 0x5E, 0xEF, 0xAF))
_IID_IUNKNOWN = _GUID(
    0x00000000, 0x0000, 0x0000,
    (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))

_ole32 = windll.ole32
_ole32.CoInitializeEx.argtypes = [c_void_p, wintypes.DWORD]
_ole32.CoInitializeEx.restype = ctypes.c_long  # 负数 HRESULT 不转异常
_ole32.CoCreateInstance.argtypes = [
    c_void_p, c_void_p, wintypes.DWORD, c_void_p, POINTER(c_void_p)]
_ole32.CoCreateInstance.restype = ctypes.c_long  # 手动检查 HRESULT

# TBPFLAG（taskbar progress flags）
TBPF_NOPROGRESS = 0
TBPF_INDETERMINATE = 1
TBPF_NORMAL = 2


class TaskbarProgress:
    """Windows 任务栏进度（value 为 0~1，None 表示不确定阶段）。"""

    def __init__(self, hwnd: int):
        self._hwnd = int(hwnd)
        self._last_state = None
        self._taskbar = None
        self._release = None
        self._set_state = None
        self._set_value = None
        try:
            self._open()
            logger.info(f"任务栏进度已初始化（hwnd={self._hwnd:#x}）")
        except Exception as exc:
            logger.warning(f"任务栏进度初始化失败，功能不可用：{exc}")
            self._disable()

    def _open(self) -> None:
        # 已初始化过（如 Qt 主线程）时返回 RPC_E_CHANGED_MODE，可忽略
        _ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
        p_unk = c_void_p()
        hr = _ole32.CoCreateInstance(
            ctypes.addressof(_CLSID_TASKBAR_LIST), None, 0x1,
            ctypes.addressof(_IID_IUNKNOWN), byref(p_unk))
        if hr != 0:
            raise OSError(hr, "CoCreateInstance(CLSID_TaskbarList) 失败")

        vtbl = cast(p_unk, POINTER(POINTER(c_void_p)))[0]
        query_interface = WINFUNCTYPE(
            ctypes.c_long, c_void_p, c_void_p, c_void_p)(vtbl[0])
        p_tb = c_void_p()
        hr = query_interface(
            p_unk, ctypes.addressof(_IID_ITASKBAR_LIST3),
            ctypes.addressof(p_tb))
        if hr != 0:
            raise OSError(hr, "QueryInterface(ITaskbarList3) 失败")

        vtbl3 = cast(p_tb, POINTER(POINTER(c_void_p)))[0]
        # vtable：0-2 IUnknown，3 HrInit，4-8 ITaskbarList/2，
        # 9 SetProgressValue，10 SetProgressState
        WINFUNCTYPE(ctypes.c_long, c_void_p)(vtbl3[3])(p_tb)  # HrInit
        self._release = WINFUNCTYPE(ctypes.c_ulong, c_void_p)(vtbl3[2])
        self._set_state = WINFUNCTYPE(
            ctypes.c_long, c_void_p, c_void_p, c_int)(vtbl3[10])
        self._set_value = WINFUNCTYPE(
            ctypes.c_long, c_void_p, c_void_p, c_ulonglong,
            c_ulonglong)(vtbl3[9])
        self._taskbar = p_tb

    def _disable(self) -> None:
        taskbar, self._taskbar = self._taskbar, None
        release, self._release = self._release, None
        self._set_state = None
        self._set_value = None
        if taskbar is not None and release is not None:
            try:
                release(taskbar)
            except Exception:
                pass

    def _write(self, state: int, percent: int) -> None:
        try:
            hr = self._set_state(self._taskbar, self._hwnd, state)
            if hr == 0 and state == TBPF_NORMAL:
                hr = self._set_value(
                    self._taskbar, self._hwnd, percent, 100)
            if hr != 0:
                logger.warning(
                    f"写入任务栏进度 hr={hr:#x}（state={state}, "
                    f"percent={percent}）")
                raise OSError(hr, "写入任务栏进度失败")
        except Exception as exc:
            logger.warning(f"更新任务栏进度失败，已停用：{exc}")
            self._disable()

    def set_progress(self, value: float | None) -> None:
        """更新进度。value 为 0~1；None 表示不确定阶段（转圈）。"""
        if self._taskbar is None:
            return

        # 状态机：准备阶段 -> 转圈；进行中（0%~99%）-> 正常进度；完成 -> 清除
        if value is None:
            state, percent = TBPF_INDETERMINATE, 0
        elif value >= 1.0:
            state, percent = TBPF_NOPROGRESS, 0
        else:
            state, percent = TBPF_NORMAL, max(1, min(100, round(value * 100)))

        if state != self._last_state or state == TBPF_NORMAL:
            self._write(state, percent)
            self._last_state = state

    def clear(self) -> None:
        """清除任务栏进度并释放 COM 对象。"""
        if self._taskbar is None:
            return
        self._write(TBPF_NOPROGRESS, 0)
        self._last_state = TBPF_NOPROGRESS
        self._disable()

    def __del__(self):
        try:
            self._disable()
        except Exception:
            pass
