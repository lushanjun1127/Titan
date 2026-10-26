# -*- coding: utf-8 -*-
"""
ui_app.py —— PySide6 桥接层（QObject）

作为 QML 与 core_engine 之间的桥梁：
- 三个 Signal（驼峰命名，供 QML 的 onXxx 精确匹配）：
  logChanged(str) / progressChanged(float) / statusChanged(bool)。
- 暴露三个路径属性（inputPath / blacklistPath / outputPath）供 QML 双向绑定。
- startEngine() / exportCustom(list, list, int) 两个 Slot，均在后台线程跑 core_engine，
  通过 Signal 把日志、进度、状态抛回主线程（Qt 自动排队，UI 不卡、丝滑 60fps）。
底层 core_engine.py 保持不变。
"""

import threading
from PySide6.QtCore import QObject, Signal, Slot, Property

import core_engine as ce


class Backend(QObject):
    # 驼峰命名：QML 的 onLogChanged / onProgressChanged / onStatusChanged 才能精确匹配
    logChanged = Signal(str)
    progressChanged = Signal(float)
    statusChanged = Signal(bool)
    pathsChanged = Signal()           # 供 QML 绑定刷新路径文本

    def __init__(self):
        super().__init__()
        self._input = str(ce.INPUT_FOLDER)
        self._black = str(ce.BLACKLIST_FOLDER)
        self._output = str(ce.OUTPUT_FOLDER)
        self._running = False
        self._exporting = False
        self._stop = threading.Event()

    # ---------------- 路径属性 ----------------
    def _get_input(self):
        return self._input

    def _set_input(self, v):
        self._input = v
        self.pathsChanged.emit()

    def _get_black(self):
        return self._black

    def _set_black(self, v):
        self._black = v
        self.pathsChanged.emit()

    def _get_output(self):
        return self._output

    def _set_output(self, v):
        self._output = v
        self.pathsChanged.emit()

    inputPath = Property(str, _get_input, _set_input, notify=pathsChanged)
    blacklistPath = Property(str, _get_black, _set_black, notify=pathsChanged)
    outputPath = Property(str, _get_output, _set_output, notify=pathsChanged)

    # ---------------- 清洗引擎 ----------------
    @Slot()
    def startEngine(self):
        if self._running or self._exporting:
            return
        self._running = True
        self._stop = threading.Event()
        self.statusChanged.emit(True)
        self.logChanged.emit("[START] 引擎启动……")
        threading.Thread(target=self._run_engine, daemon=True).start()

    def _run_engine(self):
        try:
            ce.run_engine(
                input_folder=self._input,
                blacklist_folder=self._black,
                output_folder=self._output,
                stop_event=self._stop,
                on_progress=lambda d, t: self.progressChanged.emit(d / t if t else 0.0),
                on_log=lambda m: self.logChanged.emit(m) if isinstance(m, str) else None,
            )
        except Exception as exc:  # noqa: BLE001
            self.logChanged.emit(f"[FATAL] 引擎异常: {exc}")
        finally:
            self._running = False
            self.statusChanged.emit(False)
            self.progressChanged.emit(1.0)
            self.logChanged.emit("[DONE] 引擎已安全退出，SQLite 已关闭。")

    # ---------------- 精准点单导出 ----------------
    @Slot(list, list, int)
    def exportCustom(self, ages, genders, limit):
        if self._running or self._exporting:
            return
        # QML 传来的 QVariantList -> Python list
        ages = list(ages) if ages else []
        genders = list(genders) if genders else []
        if not ages or not genders or not isinstance(limit, int) or limit <= 0:
            self.logChanged.emit("[EXPORT] 条件不完整：需勾选年龄段+性别且数量>0。")
            return
        self._exporting = True
        self.statusChanged.emit(True)
        self.logChanged.emit(f"[EXPORT] 开始：年段={ages} 性别={genders} 数量={limit}（后台扫描中…）")
        threading.Thread(target=self._run_export, args=(ages, genders, limit),
                         daemon=True).start()

    def _run_export(self, ages, genders, limit):
        try:
            ce.export_custom(ages, genders, limit,
                             source_folder=self._output,
                             on_log=lambda m: self.logChanged.emit(m) if isinstance(m, str) else None)
        except Exception as exc:  # noqa: BLE001
            self.logChanged.emit(f"[EXPORT-FATAL] 导出异常: {exc}")
        finally:
            self._exporting = False
            self.statusChanged.emit(False)
            self.logChanged.emit("[EXPORT] 导出任务结束。")
