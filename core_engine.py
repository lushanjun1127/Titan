# -*- coding: utf-8 -*-
"""
core_engine.py —— 核心数据处理引擎（单机版 / 工业级 / 并发限流版）

严格业务规范 + 并发加速：
- 子线程（线程池）只负责「读取 + 清洗 + 过滤」，绝不碰 SQLite 与切片 CSV。
- 主进程（run_engine 所在线程）统一收口：SQLite 去重查询、新号码落库、切片 CSV 写出。
- 并发池大小 = max(1, int(CPU核心数 * 0.7))，给系统留 30% 呼吸空间。
- 全局 threading.Event 作为停止信号：用户点【停止】，子线程完成当前文件后退出，
  主进程保存数据并关闭 SQLite。

运行：
    python core_engine.py            # 命令行模式（按默认路径跑）
    python main.py                   # 启动 GUI
"""

from __future__ import annotations

import atexit
import hashlib
import os
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------- #
# 1. 路径配置
#    数据根目录解析优先级：环境变量 TITAN_ROOT > D:/Titan（存在则用）> 脚本同目录。
#    保证在 Windows 部署机与 Linux/macOS 上都能开箱即跑；GUI 里仍可为每次运行
#    单独选择输入/黑名单/输出目录（run_engine 参数）。
# --------------------------------------------------------------------------- #
def _resolve_titan_root() -> Path:
    env = os.environ.get("TITAN_ROOT", "").strip()
    if env:
        return Path(env)
    d_root = Path("D:/Titan")
    if d_root.exists():
        return d_root
    return Path(__file__).resolve().parent


TITAN_ROOT = _resolve_titan_root()

INPUT_FOLDER = TITAN_ROOT / "1_底料入库"
BLACKLIST_FOLDER = TITAN_ROOT / "2_剔除名单"
OUTPUT_FOLDER = TITAN_ROOT / "3_待触达库"
ERROR_FOLDER = TITAN_ROOT / "4_残次品库"
AREA_CODE_CSV = TITAN_ROOT / "area_codes.csv"

# 同目录官方区号库回退（schema 与 area_codes.csv 一致，文件缺失时启用）
AREA_CODE_FALLBACK = TITAN_ROOT / "npa_report.csv"

# 全局已触达总库（跨运行持久化去重）：SQLite，主键索引查询极快，支持亿级
SENT_DB = TITAN_ROOT / "sent_database.db"
SENT_FLUSH_THRESHOLD = 50_000   # 新号码缓冲达到此值即批量落库，控制内存占用
CHECK_EXISTING_OUTPUT = True    # 启动前扫描历史产出，内容相同则跳过（防重复文件）

# --------------------------------------------------------------------------- #
# 2. 业务参数
# --------------------------------------------------------------------------- #
CHUNK_SIZE = 10_000              # 分块读取行数
MAX_ROWS_PER_FILE = 1_000_000   # 单个 csv 文件最大行数（超出切片）
ERROR_FILE_NAME = "error_phones.csv"
UNKNOWN_STATE = "Unknown_State"

# 列名候选（按你真实表头调整；按顺序命中第一个存在的列）
COLUMN_CONFIG = {
    "phone": ["phone", "手机号", "电话", "mobile", "cell", "number", "号码", "telephone"],
    "age":   ["age", "年龄", "ages"],
    "gender": ["gender", "sex", "性别"],
}

# 无表头文件的位置映射（首字段为纯数字时按此顺序赋予逻辑列名）
# 顺序须与无表头底料的实际列序一致：号码, 姓名, 年龄, 性别
POSITIONAL_COLUMNS = ["phone", "name", "age", "gender"]
AUTO_DETECT_HEADERLESS = True   # 首字段为纯数字 -> 判定无表头

# 年龄分段（含端点）；<30 一律丢弃
AGE_SEGMENTS = [
    (30, 39, "30-39"),
    (40, 49, "40-49"),
    (50, 999, "50+"),
]

# 性别归一：统一为 Male / Female
GENDER_MAP = {
    "male": "Male", "m": "Male", "man": "Male", "男": "Male", "1": "Male",
    "female": "Female", "f": "Female", "woman": "Female", "女": "Female",
    "0": "Female", "2": "Female",
}

# 本次运行批次时间戳（用于文件名，保证不覆盖历史）
BATCH_TIME = datetime.now().strftime("%Y%m%d_%H%M")

# --------------------------------------------------------------------------- #
# 3. 全局状态
# --------------------------------------------------------------------------- #
blacklist: set[str] = set()          # 剔除名单（纯数字）
area_code_dict: dict[str, str] = {}  # NPA -> LOCATION
seen_phones: set[str] = set()        # 本次运行内号码去重
error_seen: set[str] = set()         # 残次号码去重（含历史）
sent_conn = None                    # SQLite 连接（main 中打开/关闭）
new_sent: list[str] = []             # 本次新产出、待落库的号码

# 内存缓冲：key=(州, 年龄段, 性别) -> 行列表
# （规范中的「6 个列表」即 3 年龄段 × 2 性别；因导出按州分目录，故 key 含州名）
buffers: dict[tuple, list[dict]] = {}
part_no: dict[tuple, int] = {}       # 每个 key 当前的切片序号（从 1 起）
rows_in_part: dict[tuple, int] = {}  # 每个 key 当前切片已累积行数

# 历史产出内容指纹集合（启动前扫描 3_待触达库建立，用于“内容相同则跳过”防重复文件）
existing_output_fps: set[str] = set()

stats = {
    "files": 0, "rows_total": 0, "rows_blacklist": 0, "rows_dup": 0,
    "rows_bad_phone": 0, "rows_age_lt_30": 0, "rows_bad_gender": 0,
    "rows_sent_db": 0, "rows_dupe_file": 0, "rows_written": 0, "errors": 0,
}
_error_buffer: list[dict] = []       # 残次行缓冲（主进程统一写出）

# 并发安全锁：主进程收口写操作，子线程不调用；此锁用于防御性保护
_write_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# 4. 工具函数
# --------------------------------------------------------------------------- #
def safe_name(text: str) -> str:
    """清洗为安全目录/文件名（去掉 Windows 非法字符）。"""
    return re.sub(r'[\\/:*?"<>|\r\n\t]', "_", text).strip() or "UNNAMED"


def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """返回 DataFrame 中第一个存在的候选列名。"""
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for cand in candidates:
        key = cand.strip().lower()
        if key in lower_map:
            return lower_map[key]
    return None


def _detect_text_format(path: Path) -> tuple[str, str]:
    """探测 txt 分隔符，返回 (sep, engine)。优先 Tab，其次逗号，最后按空白。"""
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.strip():
                    if "\t" in line:
                        return "\t", "c"
                    if "," in line:
                        return ",", "c"
                    return r"\s+", "python"
    except Exception:  # noqa: BLE001
        pass
    return ",", "c"


def csv_is_headerless(path: Path, sep: str = ",") -> bool:
    """首行首字段为纯数字 -> 判定无表头（首行即数据）。sep 支持 , / Tab / 正则 \\s+。"""
    if not AUTO_DETECT_HEADERLESS:
        return False
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                first = re.split(sep, line, maxsplit=1)[0].strip()
                return bool(first) and first.isdigit()
    except Exception:  # noqa: BLE001
        return False
    return False


def apply_positional_columns(df: pd.DataFrame) -> pd.DataFrame:
    """无表头时按 POSITIONAL_COLUMNS 顺序重命名（长度不够则仅重命名前 N 列）。"""
    n = min(len(POSITIONAL_COLUMNS), len(df.columns))
    return df.rename(columns={df.columns[i]: POSITIONAL_COLUMNS[i] for i in range(n)})


# --------------------------------------------------------------------------- #
# 5. 加载类（只读，子线程安全）
# --------------------------------------------------------------------------- #
def load_blacklist() -> None:
    """读取剔除名单目录下所有 txt，正则提取纯数字存入全局 set。"""
    if not BLACKLIST_FOLDER.exists():
        print(f"[WARN] 剔除名单目录不存在: {BLACKLIST_FOLDER}")
        return
    txt_files = sorted(BLACKLIST_FOLDER.glob("*.txt"))
    if not txt_files:
        print(f"[WARN] 剔除名单目录无 .txt 文件: {BLACKLIST_FOLDER}")
    for txt in txt_files:
        try:
            text = txt.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                num = re.sub(r"\D", "", line.strip())
                if num:
                    blacklist.add(num)
            print(f"[INFO] 已加载黑名单: {txt.name}（累计 {len(blacklist)} 个）")
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] 读取黑名单失败 {txt.name}: {exc}")


def load_area_codes() -> None:
    """读取官方区号库，建立 NPA_ID -> LOCATION 字典（USE=G 且 IN_SERVICE=Y）。"""
    global area_code_dict
    area_code_dict = {}
    src = AREA_CODE_CSV
    if not src.exists():
        print(f"[WARN] 区号库不存在: {src}，回退 {AREA_CODE_FALLBACK.name}")
        src = AREA_CODE_FALLBACK
    if not src.exists():
        print(f"[ERROR] 区号库缺失，州名仅能依赖文件名（Unknown_State 将增多）")
        return
    try:
        df = pd.read_csv(src, encoding="utf-8", dtype=str, on_bad_lines="skip")
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 读取区号库失败 {src}: {exc}")
        return

    for col in ("NPA_ID", "LOCATION", "USE", "IN_SERVICE"):
        if col not in df.columns:
            print(f"[ERROR] 区号库缺少必需列: {col}（现有列: {list(df.columns)}）")
            return

    kept = 0
    for _, row in df.iterrows():
        try:
            if (str(row.get("USE", "")).strip().upper() != "G" or
                    str(row.get("IN_SERVICE", "")).strip().upper() != "Y"):
                continue
            npa = re.sub(r"\D", "", str(row.get("NPA_ID", "")).strip())
            loc = str(row.get("LOCATION", "")).strip()
            if npa and loc:
                area_code_dict[npa] = loc
                kept += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] 区号记录解析异常: {exc}")
    print(f"[INFO] 区号字典建立完成: 有效记录 {kept} 条")


def load_error_history() -> None:
    """载入历史残次号码，避免重复追加。"""
    err_path = ERROR_FOLDER / ERROR_FILE_NAME
    if not err_path.exists():
        return
    try:
        df = pd.read_csv(err_path, encoding="utf-8", dtype=str, on_bad_lines="skip")
        if "phone" in df.columns:
            for v in df["phone"].dropna():
                error_seen.add(re.sub(r"\D", "", str(v).strip()))
        print(f"[INFO] 已载入历史残次号码 {len(error_seen)} 个")
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 读取历史残次文件失败: {exc}")


# --------------------------------------------------------------------------- #
# 6. SQLite 已触达总库（主进程收口，线程安全）
# --------------------------------------------------------------------------- #
def open_sent_db() -> bool:
    """连接 SQLite，建表 sent_phones(phone PRIMARY KEY)，开启 WAL。成功返回 True。"""
    global sent_conn
    try:
        SENT_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(SENT_DB))
        conn.execute("PRAGMA journal_mode=WAL")    # 写前日志：提升读写并发
        conn.execute("PRAGMA busy_timeout=5000")   # 锁等待，避免并发抢占报错
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sent_phones (phone TEXT PRIMARY KEY)"
        )
        conn.commit()
        sent_conn = conn
        cnt = conn.execute("SELECT COUNT(*) FROM sent_phones").fetchone()[0]
        print(f"[INFO] 已连接已触达总库(SQLite): {cnt} 条")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 打开已触达总库失败 {SENT_DB}: {exc}")
        sent_conn = None
        return False


def is_phone_sent(phone: str) -> bool:
    """查询号码是否已触达（主键索引，极快）。连接异常时降级为 False。"""
    if sent_conn is None:
        return False
    try:
        return sent_conn.execute(
            "SELECT 1 FROM sent_phones WHERE phone = ?", (phone,)
        ).fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 查询已触达总库失败 {phone}: {exc}")
        return False


def flush_sent_db_buffer() -> None:
    """把内存缓冲的新号码批量落库（INSERT OR IGNORE 防冲突），随后清空缓冲。"""
    global new_sent
    if not new_sent or sent_conn is None:
        return
    try:
        with _write_lock:
            sent_conn.executemany(
                "INSERT OR IGNORE INTO sent_phones (phone) VALUES (?)",
                [(p,) for p in new_sent],
            )
            sent_conn.commit()
        print(f"[WRITE] 已触达总库追加 {len(new_sent)} 个号码")
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 写入已触达总库失败: {exc}")
    new_sent = []


def close_sent_db() -> None:
    """提交并关闭连接；确保程序退出时释放数据库资源。"""
    global sent_conn
    if sent_conn is None:
        return
    try:
        sent_conn.commit()
        sent_conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 关闭已触达总库失败: {exc}")
    finally:
        sent_conn = None


# 保险：无论以何种方式退出都尝试关闭连接
atexit.register(close_sent_db)


# --------------------------------------------------------------------------- #
# 7. 号码清洗 / 州名 / 残次（纯函数，子线程安全）
# --------------------------------------------------------------------------- #
def clean_phone(raw) -> str | None:
    """正则提取纯数字。11 位且以 1 开头保留；10 位补 1；否则返回 None（残次）。"""
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw).strip())
    if len(digits) == 11 and digits.startswith("1"):
        return digits
    if len(digits) == 10:
        return "1" + digits
    return None


def classify_gender(raw) -> str | None:
    return None if raw is None else GENDER_MAP.get(str(raw).strip().lower())


def classify_age(age_val) -> str | None:
    try:
        age = int(float(str(age_val).strip()))
    except (ValueError, TypeError):
        return None
    if age < 30:
        return None
    for lo, hi, label in AGE_SEGMENTS:
        if lo <= age <= hi:
            return label
    return None


def extract_state_from_filename(fname: str) -> str | None:
    m = re.search(r"([\u4e00-\u9fff]+)州", fname)
    return m.group(1) if m else None


def lookup_state_by_npa(phone: str) -> str:
    """用号码区号(NPA)查字典；查不到填 Unknown_State。
    11 位且以 1 开头（含国家码）时 NPA 取第 2~4 位，否则取前 3 位。"""
    npa = phone[1:4] if (len(phone) == 11 and phone.startswith("1")) else phone[:3]
    return area_code_dict.get(npa, UNKNOWN_STATE)


def emit_error(raw_phone, reason: str) -> None:
    """残次号码去重后计入缓冲（主进程调用，线程安全）。"""
    num = re.sub(r"\D", "", str(raw_phone).strip()) if raw_phone is not None else ""
    with _write_lock:
        key = num or f"__RAW__{reason}"
        if key in error_seen:
            return
        error_seen.add(key)
        _error_buffer.append({"phone": num, "raw": str(raw_phone), "reason": reason})


# --------------------------------------------------------------------------- #
# 8. 切片导出（仅主进程调用，线程安全）
# --------------------------------------------------------------------------- #
def content_fingerprint(rows: list[dict]) -> str:
    """对一批合格行生成内容指纹：按 clean_phone 排序后做 sha256。

    相同号码集合 -> 相同指纹，跨批次/跨运行稳定；与列顺序、原始字段无关。
    空批次返回空串（调用方据此跳过）。
    """
    phones = sorted(str(r.get("clean_phone", "")) for r in rows if r.get("clean_phone"))
    if not phones:
        return ""
    h = hashlib.sha256()
    h.update("\n".join(phones).encode("utf-8"))
    return h.hexdigest()


def scan_existing_output() -> int:
    """扫描 3_待触达库 历史产出，建立内容指纹集合（防重复文件）。

    仅读取每文件的号码列（clean_phone，回退首列），内存占用极低。
    返回扫描到的文件数。CHECK_EXISTING_OUTPUT=False 时直接返回 0。
    """
    global existing_output_fps
    existing_output_fps = set()
    if not CHECK_EXISTING_OUTPUT:
        return 0
    if not OUTPUT_FOLDER.exists():
        return 0
    count = 0
    for csv in OUTPUT_FOLDER.rglob("*.csv"):
        try:
            df = pd.read_csv(csv, encoding="utf-8", dtype=str,
                             usecols=["clean_phone"], on_bad_lines="skip")
            phones = [str(v).strip() for v in df["clean_phone"].dropna() if str(v).strip()]
        except Exception:  # noqa: BLE001
            # 旧文件无 clean_phone 列 -> 回退读取首列
            try:
                head = pd.read_csv(csv, encoding="utf-8", dtype=str,
                                   on_bad_lines="skip", nrows=0)
                if len(head.columns) == 0:
                    continue
                first_col = head.columns[0]
                df2 = pd.read_csv(csv, encoding="utf-8", dtype=str,
                                  usecols=[first_col], on_bad_lines="skip")
                phones = [str(v).strip() for v in df2[first_col].dropna() if str(v).strip()]
            except Exception:  # noqa: BLE001
                continue
        if phones:
            existing_output_fps.add(content_fingerprint([{"clean_phone": p} for p in phones]))
            count += 1
    return count


def flush_category(key: tuple) -> None:
    """把某 (州, 年龄段, 性别) 桶的缓冲写出为一个切片文件。"""
    rows = buffers.get(key)
    if not rows:
        return
    # —— 内容指纹防重复：若本批次内容与历史产出完全一致，跳过写文件（仍计入已触达总库）——
    if CHECK_EXISTING_OUTPUT:
        fp = content_fingerprint(rows)
        if fp and fp in existing_output_fps:
            stats["rows_dupe_file"] += len(rows)   # 本运行内被跳过的重复行数（不计入 rows_written）
            st, ag, gd = key
            print(f"[SKIP] 内容指纹已存在，跳过重复批次: {st}/{ag}_{gd} "
                  f"({len(rows)} 行)")
            existing_output_fps.add(fp)        # 本运行内后续同内容批次也跳过
            buffers[key] = []
            rows_in_part[key] = 0
            part_no[key] = part_no.get(key, 1) + 1
            return
    state, age_group, gender = key
    part = part_no.get(key, 1)

    folder = OUTPUT_FOLDER / safe_name(state)
    folder.mkdir(parents=True, exist_ok=True)
    fname = f"{age_group}_{gender}_{BATCH_TIME}_第{part}部分.csv"
    out_path = folder / fname
    # 防覆盖：若同名文件已存在（同分钟重跑等），递增后缀直到不冲突
    n = 2
    while out_path.exists():
        out_path = folder / f"{age_group}_{gender}_{BATCH_TIME}_第{part}部分_{n}.csv"
        n += 1

    try:
        with _write_lock:
            pd.DataFrame(rows).to_csv(out_path, index=False, encoding="utf-8")
        stats["rows_written"] += len(rows)
        print(f"[WRITE] {out_path}  ({len(rows)} 行)")
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 写出失败 {out_path}: {exc}")
        stats["errors"] += 1

    buffers[key] = []
    rows_in_part[key] = 0
    part_no[key] = part + 1


def add_row(state: str, age_group: str, gender: str, row_dict: dict) -> None:
    """将合格数据加入对应桶；满 1,000,000 行立即切片导出。"""
    key = (state, age_group, gender)
    buffers.setdefault(key, [])
    part_no.setdefault(key, 1)
    rows_in_part[key] = rows_in_part.get(key, 0) + 1
    buffers[key].append(row_dict)
    new_sent.append(row_dict.get("clean_phone"))   # 记录本次新产出号码
    if len(new_sent) >= SENT_FLUSH_THRESHOLD:
        flush_sent_db_buffer()                      # 定期落库，控制内存
    if rows_in_part[key] >= MAX_ROWS_PER_FILE:
        flush_category(key)


def flush_errors() -> None:
    """残次文件去重追加写出（主进程调用）。"""
    if not _error_buffer:
        return
    ERROR_FOLDER.mkdir(parents=True, exist_ok=True)
    out_path = ERROR_FOLDER / ERROR_FILE_NAME
    existed = out_path.exists()
    try:
        with _write_lock:
            pd.DataFrame(_error_buffer).to_csv(
                out_path, index=False, encoding="utf-8", mode="a", header=not existed)
        print(f"[WRITE] {out_path}（追加 {len(_error_buffer)} 条残次）")
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 残次文件写出失败 {out_path}: {exc}")


# --------------------------------------------------------------------------- #
# 8.1 精准发货 · 自定义条件导出（多线程扫描 3_待触达库）
# --------------------------------------------------------------------------- #
def _export_scan_folder(folder: Path, age_set: set, gender_set: set, limit: int,
                        on_log=None) -> list[dict]:
    """扫描单个州文件夹：逐文件读入命中年段/性别的 CSV，凑够 limit 即停。
    返回行列表（dict），最多 limit 条。仅读取，不写任何产出。"""
    on_log = on_log or (lambda m: None)
    collected: list[dict] = []
    try:
        for csv in sorted(folder.glob("*.csv")):
            if len(collected) >= limit:
                break
            stem = csv.name.rsplit(".", 1)[0]
            parts = stem.split("_")
            if len(parts) < 2:
                continue
            age_tok, gender_tok = parts[0], parts[1]
            if age_tok not in age_set or gender_tok not in gender_set:
                continue
            # 分块读取，达到 limit 立即停止（控制内存 + 提速）
            for chunk in pd.read_csv(csv, chunksize=CHUNK_SIZE, encoding="utf-8",
                                     dtype=str, on_bad_lines="skip"):
                collected.extend(chunk.to_dict("records"))
                if len(collected) >= limit:
                    break
            if len(collected) >= limit:
                on_log(f"[EXPORT] 目录 {folder.name} 已凑够，提前停止扫描")
                break
    except Exception as exc:  # noqa: BLE001
        on_log(f"[EXPORT-ERR] 扫描 {folder} 失败: {exc}")
    return collected[:limit]


def export_custom(age_groups: list, genders: list, limit: int,
                  source_folder=None, on_log=None, stop_event=None) -> dict:
    """按自定义条件从 3_待触达库(各州文件夹)精准提取号码并导出。

    - age_groups: 如 ["30-39","50+"]；genders: 如 ["Male","Female"]。
    - 多线程：每个州文件夹一个 worker（并发池 = max(1, CPU*0.7)），
      as_completed 收口，凑够 limit 即取消剩余任务。
    - 输出：<source父目录>/5_精准发货/导出_{年段}_{性别}_{数量}条_{YYYYMMDD}.csv
    返回 {"exported": N, "path": str}；条件不完整/无结果返回 {"exported": 0}。
    """
    on_log = on_log or (lambda m: print(m) if isinstance(m, str) else None)
    stop_event = stop_event or threading.Event()
    age_groups = [a for a in (age_groups or []) if a]
    genders = [g for g in (genders or []) if g]
    if not age_groups or not genders or not isinstance(limit, int) or limit <= 0:
        on_log("[EXPORT] 条件不完整：需至少勾选一个年龄段、一个性别，且数量>0")
        return {"exported": 0}

    src = Path(source_folder) if source_folder else OUTPUT_FOLDER
    if not src.exists():
        on_log(f"[EXPORT] 待触达库不存在: {src}")
        return {"exported": 0}

    age_set, gender_set = set(age_groups), set(genders)
    folders = [d for d in src.iterdir() if d.is_dir()]
    on_log(f"[EXPORT] 扫描 {len(folders)} 个州文件夹，条件: 年段={age_groups} "
           f"性别={genders} 数量={limit}")

    collected: list[dict] = []
    cpu = os.cpu_count() or 1
    workers = max(1, int(cpu * 0.7))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_export_scan_folder, f, age_set, gender_set, limit, on_log): f
                for f in folders}
        try:
            for fut in as_completed(futs):
                if stop_event.is_set():
                    on_log("[EXPORT] 收到停止信号，终止扫描")
                    break
                try:
                    rows = fut.result()
                except Exception as exc:  # noqa: BLE001
                    on_log(f"[EXPORT-ERR] 任务异常: {exc}")
                    continue
                collected.extend(rows)
                on_log(f"[EXPORT] 已扫描 {futs[fut].name}，累计 {len(collected)}/{limit}")
                if len(collected) >= limit:
                    for f2 in futs:          # 凑够即取消未开始的任务
                        if not f2.done():
                            f2.cancel()
                    break
        finally:
            pass

    collected = collected[:limit]
    if not collected:
        on_log("[EXPORT] 未找到符合条件的号码")
        return {"exported": 0}

    # 输出目录：待触达库的同级「5_精准发货」
    export_root = src.parent / "5_精准发货"
    export_root.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y%m%d")
    age_lbl = "+".join(age_groups)
    gender_lbl = "+".join("男性" if g == "Male" else "女性" for g in genders)
    fname = f"精准导出_{age_lbl}_{gender_lbl}_{limit}条_{date}.csv"
    out_path = export_root / fname
    n = 2
    while out_path.exists():            # 防覆盖
        out_path = export_root / f"精准导出_{age_lbl}_{gender_lbl}_{limit}条_{date}_{n}.csv"
        n += 1
    try:
        pd.DataFrame(collected).to_csv(out_path, index=False, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        on_log(f"[EXPORT-ERR] 写出失败 {out_path}: {exc}")
        return {"exported": 0}

    on_log(f"[EXPORT] 成功提取 {len(collected)} 条号码，已保存至 5_精准发货")
    return {"exported": len(collected), "path": str(out_path)}


# --------------------------------------------------------------------------- #
# 9. 子线程：读取 + 清洗 + 过滤（不碰 SQLite / 输出）
# --------------------------------------------------------------------------- #
def _process_chunk(chunk: pd.DataFrame, fname: str, state_from_file,
                  local: dict, qualified: list, errors: list) -> None:
    """处理单个数据块（CSV 块 / Excel 某一 Sheet 切片）：定位列、清洗、过滤。"""
    phone_col = find_column(chunk, COLUMN_CONFIG["phone"])
    age_col = find_column(chunk, COLUMN_CONFIG["age"])
    gender_col = find_column(chunk, COLUMN_CONFIG["gender"])
    if phone_col is None:
        print(f"[WARN] 文件 {fname} 未找到手机号列，跳过该块")
        return
    for _, series in chunk.iterrows():
        local["rows_total"] += 1
        row = series.to_dict()
        phone = clean_phone(row.get(phone_col))
        if phone is None:
            local["rows_bad_phone"] += 1
            raw = row.get(phone_col)
            errors.append((re.sub(r"\D", "", str(raw).strip()) if raw is not None else "", "非法号码长度"))
            continue
        if phone in blacklist:
            local["rows_blacklist"] += 1
            continue
        raw_age = row.get(age_col) if age_col is not None else None
        age_group = classify_age(raw_age) if age_col is not None else None
        if age_group is None:
            local["rows_age_lt_30"] += 1
            miss = raw_age is None or str(raw_age).strip().lower() in ("", "nan", "none")
            errors.append((phone, "年龄缺失" if miss else "年龄<30"))
            continue
        gender = classify_gender(row.get(gender_col)) if gender_col is not None else None
        if gender is None:
            local["rows_bad_gender"] += 1
            errors.append((phone, "性别无效"))
            continue
        state = state_from_file or lookup_state_by_npa(phone)
        out = dict(row)
        out["clean_phone"] = phone
        out["state"] = state
        out["age_group"] = age_group
        out["gender_std"] = gender
        qualified.append(out)


def process_file_worker(path: Path, stop_event: threading.Event):
    """子线程工作：读文件、清洗、过滤（黑名单/年龄/性别/州名）。
    返回 (local_stats, qualified_rows, error_rows)。绝不写 SQLite 或 CSV。
    - CSV：分块迭代器；Excel：pd.ExcelFile 遍历全部 Sheet，逐 Sheet 释放内存。
    """
    local = {"rows_total": 0, "rows_blacklist": 0, "rows_bad_phone": 0,
             "rows_age_lt_30": 0, "rows_bad_gender": 0}
    qualified: list[dict] = []
    errors: list[tuple] = []   # (phone_or_digits, reason)
    try:
        fname = path.name
        state_from_file = extract_state_from_filename(fname)
        suffix = path.suffix.lower()

        if suffix in (".csv", ".tsv", ".txt"):
            # 分隔符：csv=逗号, tsv=Tab, txt=自动探测（Tab / 逗号 / 空白）
            if suffix == ".csv":
                sep, engine = ",", "c"
            elif suffix == ".tsv":
                sep, engine = "\t", "c"
            else:
                sep, engine = _detect_text_format(path)
            read_kw = dict(chunksize=CHUNK_SIZE, encoding="utf-8", dtype=str,
                           on_bad_lines="skip", sep=sep)
            if engine == "python":
                read_kw["engine"] = "python"
            if csv_is_headerless(path, sep=sep):
                read_kw["header"] = None
                read_kw["names"] = POSITIONAL_COLUMNS
            reader = pd.read_csv(path, **read_kw)
            for chunk in reader:
                if stop_event.is_set():
                    break
                _process_chunk(chunk, fname, state_from_file, local, qualified, errors)
        elif suffix in (".xlsx", ".xls"):  # 多 Sheet 终极兼容
            try:
                xls = pd.ExcelFile(path)
            except Exception as exc:  # noqa: BLE001
                print(f"[ERROR] 打开 Excel 失败 {path.name}: {exc}")
                return local, qualified, errors
            for sh in xls.sheet_names:
                if stop_event.is_set():
                    break
                try:
                    # header=None 统一读取，避免 pandas 默认把无表头首行当表头吞掉
                    sheet_df = pd.read_excel(xls, sheet_name=sh, dtype=str, header=None)
                except Exception as exc:  # noqa: BLE001
                    print(f"[WARN] Sheet 读取失败已跳过: {path.name}/{sh}: {exc}")
                    continue
                try:
                    if (AUTO_DETECT_HEADERLESS and len(sheet_df) > 0
                            and str(sheet_df.iloc[0, 0]).strip().isdigit()):
                        # 无表头：首字段为数字 -> 按位置赋予逻辑列名
                        sheet_df = apply_positional_columns(sheet_df)
                    elif len(sheet_df) > 0:
                        # 有表头：把首行提升为列名，数据从第二行起
                        new_cols = [str(c).strip() for c in sheet_df.iloc[0].tolist()]
                        sheet_df = sheet_df.iloc[1:].reset_index(drop=True)
                        sheet_df.columns = new_cols
                    nrows = len(sheet_df)
                    for i in range(0, nrows, CHUNK_SIZE):
                        if stop_event.is_set():
                            break
                        chunk = sheet_df.iloc[i:i + CHUNK_SIZE]
                        _process_chunk(chunk, fname, state_from_file, local, qualified, errors)
                finally:
                    del sheet_df   # 读完即释放该 Sheet 内存，防多 Sheet 叠加 OOM
            try:
                xls.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 子线程处理失败 {path.name}: {exc}")
    return local, qualified, errors


# --------------------------------------------------------------------------- #
# 10. 主进程：并发调度 + 统一落库（线程安全收口）
# --------------------------------------------------------------------------- #
def _reset_run_state() -> None:
    """每次运行前重置全局可变状态（支持 GUI 多次启动）。"""
    for k in list(stats):
        stats[k] = 0
    buffers.clear(); part_no.clear(); rows_in_part.clear()
    seen_phones.clear(); new_sent.clear(); error_seen.clear(); _error_buffer.clear()


# 支持的输入表格后缀（无限深度递归扫描）
INPUT_SUFFIXES = {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
# 防呆：扫描时排除这些自身产出目录，避免读到程序生成的结果
SELF_OUTPUT_DIR_NAMES = {"3_待触达库", "4_残次品库"}


def scan_input_files(input_folder: Path = None, output_folder: Path = None,
                     error_folder: Path = None) -> list[Path]:
    """无限深度递归扫描输入目录下所有表格文件（csv/tsv/txt/xlsx/xls）。
    - 使用 rglob('*') 穿透任意层级子文件夹。
    - 防呆：路径中任一目录名命中 3_待触达库 / 4_残次品库 即跳过；
      且绝对路径落在输出/残次目录下的也跳过，绝不吃到自己的产出。
    """
    input_folder = Path(input_folder or INPUT_FOLDER)
    output_folder = Path(output_folder or OUTPUT_FOLDER)
    error_folder = Path(error_folder or ERROR_FOLDER)
    try:
        out_res, err_res = output_folder.resolve(), error_folder.resolve()
    except OSError:
        out_res, err_res = output_folder, error_folder

    found: list[Path] = []
    for p in input_folder.rglob("*"):
        try:
            if not p.is_file():
                continue
            if p.suffix.lower() not in INPUT_SUFFIXES:
                continue
            # 名称级防呆：排除自身产出目录
            if any(part in SELF_OUTPUT_DIR_NAMES for part in p.parts):
                continue
            # 排除垃圾文件：macOS 苹果元数据(._*)、Office 临时锁文件(~$*)、系统文件、空文件
            name = p.name
            if name.startswith("._") or name.startswith("~$"):
                continue
            if name.lower() in {".ds_store", "thumbs.db", "desktop.ini"}:
                continue
            if p.stat().st_size == 0:
                continue
            # 绝对路径级防呆：落在输出/残次目录下的跳过
            rp = p.resolve()
            if rp.is_relative_to(out_res) or rp.is_relative_to(err_res):
                continue
            found.append(p)
        except (OSError, ValueError):
            continue
    found.sort()
    return found


def run_engine(input_folder=None, blacklist_folder=None, output_folder=None,
               stop_event: threading.Event = None,
               on_progress=None, on_log=None) -> dict:
    """引擎主入口（并发限流版）。
    - 子线程并发读取+清洗；主进程统一 SQLite 去重、落库、切片写出。
    - stop_event 置位后，完成在途文件并安全退出（保存数据 + 关闭 SQLite）。
    """
    global INPUT_FOLDER, BLACKLIST_FOLDER, OUTPUT_FOLDER, BATCH_TIME
    if input_folder:
        INPUT_FOLDER = Path(input_folder)
    if blacklist_folder:
        BLACKLIST_FOLDER = Path(blacklist_folder)
    if output_folder:
        OUTPUT_FOLDER = Path(output_folder)

    stop_event = stop_event or threading.Event()
    BATCH_TIME = datetime.now().strftime("%Y%m%d_%H%M")
    _reset_run_state()

    on_log = on_log or (lambda m: print(m) if isinstance(m, str) else None)
    on_progress = on_progress or (lambda d, t: None)

    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    ERROR_FOLDER.mkdir(parents=True, exist_ok=True)

    load_blacklist()
    load_area_codes()
    load_error_history()
    open_sent_db()

    # 启动前扫描历史产出，建立内容指纹集合（防重复文件，独立于 SQLite 去重）
    scanned = scan_existing_output()
    if scanned:
        on_log(f"[INFO] 已扫描历史产出 {scanned} 个文件，建立内容指纹防重库")

    cpu = os.cpu_count() or 1
    workers = max(1, int(cpu * 0.7))
    on_log(f"[INFO] CPU 核心 {cpu} → 并发池大小 {workers}（保留 30% 余量）")

    files = scan_input_files(INPUT_FOLDER, OUTPUT_FOLDER, ERROR_FOLDER)
    total = len(files)
    stats["files"] = total
    on_log(f"[SCAN] 在输入目录下共递归找到 {total} 个表格文件，开始并发处理...")
    on_progress(0, total)

    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(process_file_worker, fp, stop_event): fp for fp in files}
            processed: set = set()

            def consume(fut):
                """处理单个 future 的结果（主进程收口写操作）。"""
                processed.add(fut)
                try:
                    local, qualified, errors = fut.result()
                except Exception as exc:  # noqa: BLE001
                    on_log(f"[ERROR] 处理失败 {futures.get(fut)}: {exc}")
                    return
                for k, v in local.items():
                    stats[k] = stats.get(k, 0) + v
                for phone, reason in errors:
                    emit_error(phone, reason)
                for row in qualified:
                    phone = row.get("clean_phone")
                    if is_phone_sent(phone):
                        stats["rows_sent_db"] += 1
                        continue
                    if phone in seen_phones:
                        stats["rows_dup"] += 1
                        continue
                    seen_phones.add(phone)
                    add_row(row.get("state"), row.get("age_group"), row.get("gender_std"), row)

            for fut in as_completed(futures):
                if stop_event.is_set() and fut not in processed:
                    # 停止信号：仍收口已完成的，避免丢数据
                    pass
                consume(fut)
                done = len(processed)
                on_progress(done, total)
                if stop_event.is_set():
                    break

            if stop_event.is_set():
                # 收口其余已完成的 future，取消未完成的
                for fut in as_completed([f for f in futures if f not in processed]):
                    consume(fut)
                    on_progress(len(processed), total)
                for fut in futures:
                    if not fut.done():
                        fut.cancel()
    finally:
        # 收尾：导出剩余缓冲 + 残次 + 落库剩余 + 关闭连接
        for key in list(buffers.keys()):
            flush_category(key)
        flush_errors()
        flush_sent_db_buffer()
        close_sent_db()

    summary = (
        "处理完成 | 统计:\n"
        f"  文件: {stats['files']}  总行数: {stats['rows_total']}\n"
        f"  黑名单跳过: {stats['rows_blacklist']}  已触达跳过: {stats['rows_sent_db']}\n"
        f"  运行内重复: {stats['rows_dup']}  内容重复跳过: {stats['rows_dupe_file']}\n"
        f"  残次号码: {stats['rows_bad_phone']}\n"
        f"  年龄<30/缺失: {stats['rows_age_lt_30']}  性别无效: {stats['rows_bad_gender']}\n"
        f"  实际写出: {stats['rows_written']}  错误: {stats['errors']}"
    )
    on_log(summary)
    return dict(stats)


# --------------------------------------------------------------------------- #
# 11. 命令行入口
# --------------------------------------------------------------------------- #
def main() -> None:
    print("=" * 60)
    print(f"核心数据处理启动 | 批次: {BATCH_TIME}")
    print("=" * 60)
    run_engine(
        on_log=lambda m: print(m) if isinstance(m, str) else None,
        on_progress=lambda d, t: print(f"[PROGRESS] {d}/{t}"),
    )


if __name__ == "__main__":
    main()
