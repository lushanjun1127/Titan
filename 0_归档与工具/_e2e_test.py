# -*- coding: utf-8 -*-
"""端到端实测：真实调用 core_engine.run_engine / export_custom，抓日志/耗时/内存/停止信号。"""
import os, sys, time, threading, ctypes, ctypes.wintypes as wt
from pathlib import Path

sys.path.insert(0, r"D:/Titan")
import core_engine as ce

# ---------- Windows 进程内存采样 ----------
class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

def _mem():
    p = PMC(); p.cb = ctypes.sizeof(p)
    ctypes.windll.psapi.GetProcessMemoryInfo(
        ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(p), p.cb)
    return p.WorkingSetSize / 1048576.0, p.PeakWorkingSetSize / 1048576.0

class MemSampler:
    def __init__(self): self.peak = 0.0; self._run = True; self._t = None
    def start(self): self._t = threading.Thread(target=self._loop, daemon=True); self._t.start()
    def _loop(self):
        while self._run:
            w, _ = _mem(); self.peak = max(self.peak, w); time.sleep(0.05)
    def stop(self):
        self._run = False; self._t.join(timeout=1); _, pk = _mem(); self.peak = max(self.peak, pk); return self.peak

def log(m):
    if isinstance(m, str):
        print("  |", m)

print("=" * 72)
print("PHASE A：全量清洗（1_底料入库 02.csv + 101.csv）")
print("=" * 72)
ms = MemSampler(); ms.start()
t0 = time.perf_counter()
stats = ce.run_engine(
    input_folder=r"D:/Titan/1_底料入库",
    blacklist_folder=r"D:/Titan/2_剔除名单",
    output_folder=r"D:/Titan/3_待触达库",
    on_log=log,
    on_progress=lambda d, t: print(f"  [PROGRESS] {d}/{t}") if d == t else None,
)
dur = time.perf_counter() - t0
peak = ms.stop()
print("\n[PHASE A 结果]")
print(f"  耗时: {dur:.2f}s    峰值内存: {peak:.1f} MB")
for k, v in stats.items():
    print(f"    {k}: {v}")

print()
print("=" * 72)
print("PHASE B：精准点单发货（50+ / 男性 / 500 条）")
print("=" * 72)
t0 = time.perf_counter()
res = ce.export_custom(["50+"], ["Male"], 500,
                       source_folder=r"D:/Titan/3_待触达库", on_log=log)
print(f"  耗时 {time.perf_counter() - t0:.2f}s  返回: {res}")

print()
print("=" * 72)
print("PHASE C：停止信号测试（隔离临时库，避免污染真实 sent_db / 残次库）")
print("=" * 72)
import shutil, tempfile
tmp = Path(tempfile.mkdtemp(prefix="titan_stop_"))
inp = tmp / "in"; out = tmp / "out"; inp.mkdir()
shutil.copy(r"D:/Titan/1_底料入库/101.csv", inp / "101.csv")
shutil.copy(r"D:/Titan/1_底料入库/02.csv", inp / "02.csv")
_old_db = ce.SENT_DB; _old_err = ce.ERROR_FOLDER
ce.SENT_DB = tmp / "sent.db"; ce.ERROR_FOLDER = tmp / "err"
ev = threading.Event(); holder = {}
def _run():
    holder.update(ce.run_engine(input_folder=str(inp), blacklist_folder=r"D:/Titan/2_剔除名单",
                                output_folder=str(out), stop_event=ev,
                                on_log=lambda m: None, on_progress=lambda d, t: None))
th = threading.Thread(target=_run); th.start()
time.sleep(0.20)
t0 = time.perf_counter(); ev.set(); th.join(timeout=30)
dt = time.perf_counter() - t0
ce.SENT_DB = _old_db; ce.ERROR_FOLDER = _old_err
print(f"  发出停止后 {dt*1000:.0f}ms 内线程结束={not th.is_alive()}  停止时统计={holder}")
print()
print("E2E_DONE")
