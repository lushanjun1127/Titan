# -*- coding: utf-8 -*-
"""
clean_npa.py —— 清洗官方区号库
把 D:/Titan/npa_report.csv 清洗为标准 D:/Titan/area_codes.csv
（自动跳过开头的元数据行，定位真正的表头）。
"""
from pathlib import Path

import pandas as pd

SRC = Path("D:/Titan/npa_report.csv")
DST = Path("D:/Titan/area_codes.csv")
KEEP_COLS = ["NPA_ID", "LOCATION", "USE", "IN_SERVICE"]


def find_header_index(path: Path) -> int:
    """找到包含 NPA_ID 和 LOCATION 的那一行作为真正表头（0-based 行号）。"""
    with path.open(encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f):
            if "NPA_ID" in line and "LOCATION" in line:
                return i
    raise ValueError("未找到包含 NPA_ID 和 LOCATION 的表头行")


def main() -> None:
    header_idx = find_header_index(SRC)
    # skiprows=header_idx：跳过元数据行，下一行即为表头
    df = pd.read_csv(SRC, skiprows=header_idx, encoding="utf-8",
                     dtype=str, on_bad_lines="skip")

    cols = [c for c in KEEP_COLS if c in df.columns]
    df = df[cols]

    df["USE"] = df["USE"].astype(str).str.strip().str.upper()
    df["IN_SERVICE"] = df["IN_SERVICE"].astype(str).str.strip().str.upper()
    df = df[(df["USE"] == "G") & (df["IN_SERVICE"] == "Y")]
    df = df.dropna(subset=["NPA_ID", "LOCATION"])

    df.to_csv(DST, index=False, encoding="utf-8")
    print(f"成功生成 area_codes.csv，共 {len(df)} 条有效数据")


if __name__ == "__main__":
    main()
