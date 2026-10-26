# -*- coding: utf-8 -*-
"""
main.py —— PySide6 + QML 入口

针对「独立打包版 pythoncore 找不到系统 DLL / QML 插件」的兜底：
- 强制把 PySide6 的 qml / plugins 目录写入环境变量，并把其目录前置到 PATH。
- 强制使用 OpenGL 渲染（QQuickWindow.setGraphicsApi），绕过部分 Windows 下 QML 渲染崩溃。
- 仍把 Backend 桥接对象注入 QML 上下文，并以绝对路径加载 main.qml。
底层 core_engine.py 保持不变。
"""

import os
import sys

import PySide6
from PySide6.QtGui import QGuiApplication, QFont
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import Qt, QUrl
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtQuickControls2 import QQuickStyle

# 强制使用 OpenGL 渲染（规避某些 Windows 环境下的 QML 渲染崩溃）
QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
# 强制 Basic 风格，彻底消灭 "current style does not support customization" 警告
QQuickStyle.setStyle("Basic")

# 1. 强行把 PySide6 的 QML / 插件路径喂给 Qt（应对独立打包版 Python 挡住系统 DLL）
_PYSIDE_DIR = os.path.dirname(PySide6.__file__)
os.environ["QML2_IMPORT_PATH"] = os.path.join(_PYSIDE_DIR, "qml")
os.environ["QT_PLUGIN_PATH"] = os.path.join(_PYSIDE_DIR, "plugins")
os.environ["PATH"] = _PYSIDE_DIR + os.pathsep + os.environ.get("PATH", "")
# 关键兜底：把 PySide6 根目录加入 Windows DLL 搜索目录。
# 否则 QtQuick.Controls 的 Basic 样式插件(qtquickcontrols2basicstyleplugin.dll)
# 会因找不到依赖的 Qt6*.dll 而报 "无法加载库 ... 找不到指定的模块"，导致界面整体白屏。
try:
    os.add_dll_directory(_PYSIDE_DIR)
except Exception:
    pass

from ui_app import Backend


def main():
    # 开启高 DPI 缩放（适配 2K/4K 屏幕）
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

    app = QGuiApplication(sys.argv)
    app.setApplicationName("Core Engine · 核心数据处理")
    app.setFont(QFont("Microsoft YaHei"))   # 全局默认字体（兜底，保证 QML 统一微软雅黑）

    engine = QQmlApplicationEngine()
    bridge = Backend()
    # 3. 强行把桥梁对象塞进 QML 上下文
    engine.rootContext().setContextProperty("backend", bridge)

    # 4. 确保加载的是绝对路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 让同目录的本地 QML 模块（qmldir 中的 TitanTheme 单例）可被 import 解析
    engine.addImportPath(current_dir)
    qml_file = os.path.join(current_dir, "main.qml")
    engine.load(QUrl.fromLocalFile(qml_file))

    if not engine.rootObjects():
        print("[FATAL] 无法加载 main.qml")
        sys.exit(-1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
