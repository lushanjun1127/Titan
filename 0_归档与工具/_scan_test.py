# -*- coding: utf-8 -*-
"""递归扫描 + 混合格式 单元验证：不碰真实数据，全在临时目录。"""
import sys, shutil, tempfile
from pathlib import Path
sys.path.insert(0, r"D:/Titan")
import pandas as pd
import core_engine as ce

root = Path(tempfile.mkdtemp(prefix="titan_scan_"))
inp = root / "in"; out = root / "out"; err = root / "err"; bl = root / "bl"
for p in (inp, out, err, bl): p.mkdir(parents=True)

def mk(phone_base, kind):
    rows = [[f"{phone_base}", "N", "62", "Female"],
            [f"{phone_base[:-1]}1", "N2", "55", "Male"],
            [f"{phone_base[:-1]}2", "N3", "25", "Female"]]
    return rows

def write_csv(path, base):
    pd.DataFrame(mk(base, "csv"), columns=["Phone","Name","Age","Gender"]).to_csv(path, index=False)

def write_tsv(path, base):
    pd.DataFrame(mk(base, "tsv"), columns=["Phone","Name","Age","Gender"]).to_csv(path, index=False, sep="\t")

def write_xlsx(path, base):
    pd.DataFrame(mk(base, "xlsx"), columns=["Phone","Name","Age","Gender"]).to_excel(path, index=False)

# 正常文件：分布在多层子文件夹
(inp / "sub1" / "deep").mkdir(parents=True)
(inp / "sub2" / "deep" / "deeper").mkdir(parents=True)
(inp / "sub3").mkdir()
write_csv(inp / "root.csv", "12052230000")
write_csv(inp / "sub1" / "a.csv", "12052230100")
write_tsv(inp / "sub1" / "deep" / "b.tsv", "12052230200")
write_tsv(inp / "sub2" / "deep" / "deeper" / "c.txt", "12052230300")   # txt 用 Tab 分隔
write_xlsx(inp / "sub2" / "d.xlsx", "12052230400")
(inp / "sub3" / "e.log").write_text("not a table", encoding="utf-8")

# 防呆：子文件夹里残留的自身产出，必须被排除
(inp / "sub1" / "3_待触达库").mkdir()
write_csv(inp / "sub1" / "3_待触达库" / "skip1.csv", "12052230900")
(inp / "sub2" / "4_残次品库").mkdir()
write_csv(inp / "sub2" / "4_残次品库" / "skip2.csv", "12052230910")

# ---- 1) 直接测扫描函数 ----
found = ce.scan_input_files(inp, out, err)
rel = sorted(str(p.relative_to(inp)) for p in found)
print("扫描到文件数:", len(found))
for r in rel: print("  +", r)
excluded_ok = not any("3_待触达库" in r or "4_残次品库" in r for r in rel)
suffix_ok = all(Path(r).suffix.lower() in ce.INPUT_SUFFIXES for r in rel)
print("防呆排除自身产出:", "✅" if excluded_ok else "❌ 泄漏!")
print("后缀过滤正确:", "✅" if suffix_ok else "❌")
print("期望 5 个:", "✅" if len(found) == 5 else f"❌ 实际 {len(found)}")

# ---- 2) 真跑 run_engine，验证 tsv/txt/xlsx 都能被 worker 正确读取 ----
old_db, old_err, old_bl = ce.SENT_DB, ce.ERROR_FOLDER, ce.BLACKLIST_FOLDER
ce.SENT_DB = root / "sent.db"; ce.ERROR_FOLDER = err; ce.BLACKLIST_FOLDER = bl
logs = []
stats = ce.run_engine(input_folder=str(inp), blacklist_folder=str(bl),
                      output_folder=str(out), on_log=lambda m: logs.append(m) if isinstance(m, str) else None,
                      on_progress=lambda d, t: None)
ce.SENT_DB, ce.ERROR_FOLDER, ce.BLACKLIST_FOLDER = old_db, old_err, old_bl

scan_line = [l for l in logs if l.startswith("[SCAN]")]
print("\nSCAN 日志:", scan_line[0] if scan_line else "❌ 未打印")
print("run_engine 统计: files=%d rows_total=%d written=%d age_lt30=%d errors=%d"
      % (stats["files"], stats["rows_total"], stats["rows_written"],
         stats["rows_age_lt_30"], stats["errors"]))
print("期望: files=5 rows_total=15 written=10 age_lt30=5 errors=0")
ok = (stats["files"] == 5 and stats["rows_total"] == 15 and stats["rows_written"] == 10
      and stats["rows_age_lt_30"] == 5 and stats["errors"] == 0)
print("综合判定:", "✅ 全通过（tsv/txt/xlsx 均正确解析，防呆生效）" if ok else "❌ 有偏差")

shutil.rmtree(root, ignore_errors=True)
