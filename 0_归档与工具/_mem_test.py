# -*- coding: utf-8 -*-
"""隔离内存测量：临时库跑满 2 文件 15 万行，采样峰值工作集，不污染真实 sent_db。"""
import ctypes, ctypes.wintypes as wt, time, threading, shutil, tempfile, sys
from pathlib import Path
sys.path.insert(0, r"D:/Titan")
import core_engine as ce

class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD),("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),("PeakPagefileUsage", ctypes.c_size_t)]
k32 = ctypes.WinDLL('kernel32', use_last_error=True)
_k32 = k32.K32GetProcessMemoryInfo
_k32.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]; _k32.restype = wt.BOOL
k32.GetCurrentProcess.restype = wt.HANDLE
def mem():
    p = PMC(); p.cb = ctypes.sizeof(p)
    _k32(k32.GetCurrentProcess(), ctypes.byref(p), p.cb)
    return p.WorkingSetSize/1048576.0

print(f"[基线] 导入后 RSS: {mem():.1f} MB")

tmp = Path(tempfile.mkdtemp(prefix="titan_mem_"))
inp = tmp/"in"; inp.mkdir()
shutil.copy(r"D:/Titan/1_底料入库/02.csv", inp/"02.csv")
shutil.copy(r"D:/Titan/1_底料入库/101.csv", inp/"101.csv")
old_db, old_err = ce.SENT_DB, ce.ERROR_FOLDER
ce.SENT_DB = tmp/"sent.db"; ce.ERROR_FOLDER = tmp/"err"

peak = [0.0]; running = [True]
def sampler():
    while running[0]:
        peak[0] = max(peak[0], mem()); time.sleep(0.03)
th = threading.Thread(target=sampler, daemon=True); th.start()

t0 = time.perf_counter()
stats = ce.run_engine(input_folder=str(inp), blacklist_folder=r"D:/Titan/2_剔除名单",
                      output_folder=str(tmp/"out"),
                      on_log=lambda m: None, on_progress=lambda d, t: None)
dur = time.perf_counter() - t0
running[0] = False; th.join(timeout=1)
ce.SENT_DB = old_db; ce.ERROR_FOLDER = old_err

print(f"[全量] 耗时 {dur:.2f}s  峰值内存 {peak[0]:.1f} MB  写出 {stats['rows_written']} 行  "
      f"黑名单 {stats['rows_blacklist']}  年龄<30 {stats['rows_age_lt_30']}")
