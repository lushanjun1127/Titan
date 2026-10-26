// main.qml —— 大厂级精修版（自适应 + 无边框三键 + 黑白主题 + 响应式缩放）
// 本轮精修：统一 24px 卡片内边距 / 16px 卡片间距；柔化阴影；READY 变淡背景水印；
// 路径区「选择」右对齐 + 弹性 Spacer；数量框去边框浅灰底；侧栏 Canvas/Shape 线条图标。
// 底层信号逻辑（onLogChanged / onProgressChanged / onStatusChanged）与槽（startEngine / exportCustom）原样保留。

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Shapes 1.15
import Qt5Compat.GraphicalEffects 1.0
import Qt.labs.platform 1.1
import TitanTheme 1.0

Window {
    id: root
    width: 1080
    height: 720
    minimumWidth: 880
    minimumHeight: 640
    visible: true
    color: Theme.bg                       // 主题背景
    title: "Core Engine · 核心数据处理"
    flags: Qt.FramelessWindowHint          // 无边框窗体

    // 响应式缩放因子：随窗口宽高比在 0.8~1.3 间平滑缩放
    property real ui: Math.max(0.8, Math.min(1.3, Math.min(root.width / 1080, root.height / 720)))

    // ---------- 带柔和呼吸阴影的卡片（浅灰、大模糊、低浓度）----------
    component ShadowCard : Item {
        id: sc
        default property alias content: body.data
        property color cardColor: Theme.card
        property int cardRadius: 20
        Rectangle {
            id: body
            anchors.fill: parent
            color: sc.cardColor
            radius: sc.cardRadius
        }
        DropShadow {
            anchors.fill: body
            source: body
            color: "#14000000"             // 极浅灰黑（8%），与背景温柔分离
            verticalOffset: 6
            radius: 30                      // 加大模糊半径 → 更柔和自然
            samples: 44
            transparentBorder: true
        }
    }

    // ---------- 纯黑主按钮（悬停深灰 200ms）----------
    component PrimaryButton : Button {
        hoverEnabled: true
        property bool _hov: false
        onHoveredChanged: _hov = hovered
        background: Rectangle {
            radius: 12
            color: parent._hov ? Theme.btnBgHover : Theme.btnBg
            Behavior on color { ColorAnimation { duration: 200 } }
        }
        contentItem: Text {
            text: parent.text
            color: Theme.btnText
            font.family: "Microsoft YaHei"
            font.bold: true
            font.pixelSize: 14 * ui
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    // ---------- 浅色幽灵按钮（路径选择）----------
    component GhostButton : Button {
        hoverEnabled: true
        property bool _hov: false
        onHoveredChanged: _hov = hovered
        background: Rectangle {
            radius: 8
            color: parent._hov ? Theme.ghostHover : Theme.ghostBg
            Behavior on color { ColorAnimation { duration: 140 } }
        }
        contentItem: Text {
            text: parent.text
            color: Theme.ghostText
            font.family: "Microsoft YaHei"
            font.bold: true
            font.pixelSize: 12 * ui
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    // ---------- 标题栏小按钮（最小化/最大化/关闭/主题）----------
    component IconBtn : Button {
        property string glyph: ""
        property bool danger: false
        hoverEnabled: true
        property bool _hov: false
        onHoveredChanged: _hov = hovered
        Layout.preferredWidth: 34 * ui
        Layout.preferredHeight: 28 * ui
        background: Rectangle {
            radius: 6
            color: parent._hov ? (parent.danger ? "#D50000" : "#E4E7EC") : "transparent"
            Behavior on color { ColorAnimation { duration: 140 } }
        }
        contentItem: Text {
            text: parent.glyph
            color: parent._hov && parent.danger ? "#FFFFFF" : (parent.danger ? "#D50000" : "#555555")
            font.family: "Microsoft YaHei"
            font.bold: true
            font.pixelSize: 14 * ui
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    // ---------- 侧栏线条图标（Shape 矢量描边，2px，浅灰→悬停变亮）----------
    component NavIcon : Item {
        id: ni
        property string pathData: ""
        property bool active: false
        property bool _hov: false
        implicitWidth: 44 * ui
        implicitHeight: 44 * ui

        Rectangle {
            anchors.fill: parent
            radius: 12
            color: (ni._hov || ni.active) ? "#1FFFFFFF" : "transparent"
            Behavior on color { ColorAnimation { duration: 150 } }
        }
        Shape {
            anchors.centerIn: parent
            width: 24
            height: 24
            ShapePath {
                fillColor: "transparent"
                strokeColor: (ni._hov || ni.active) ? "#FFFFFF" : "#6E6E78"
                strokeWidth: 2
                capStyle: ShapePath.RoundCap
                joinStyle: ShapePath.RoundJoin
                PathSvg { path: ni.pathData }
            }
        }
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onEntered: ni._hov = true
            onExited: ni._hov = false
        }
    }

    // ---------- 路径行（圆点 + 左对齐文字 + 弹性 Spacer + 右对齐选择）----------
    component PathRow : RowLayout {
        id: pr
        property color dotColor: "#E0F0FF"
        property string dotGlyph: "▤"
        property color dotGlyphColor: "#2E6FB0"
        property string label: ""
        property string pathText: ""
        property int target: 0
        Layout.fillWidth: true
        spacing: 12 * ui

        Rectangle {
            Layout.alignment: Qt.AlignVCenter
            width: 30 * ui; height: 30 * ui; radius: 15; color: pr.dotColor
            Text {
                text: pr.dotGlyph; color: pr.dotGlyphColor
                font.family: "Microsoft YaHei"; font.bold: true
                font.pixelSize: 14 * ui; anchors.centerIn: parent
            }
        }
        // 左对齐文字块；fillWidth 即中间的弹性 Spacer，把「选择」挤到最右
        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: 2 * ui
            Text {
                text: pr.label; color: Theme.title
                font.family: "Microsoft YaHei"; font.bold: true
                font.pixelSize: 12 * ui
            }
            Text {
                text: pr.pathText; color: Theme.desc
                font.family: "Microsoft YaHei"; font.pixelSize: 11 * ui
                Layout.fillWidth: true
                elide: Text.ElideMiddle
                wrapMode: Text.NoWrap
            }
        }
        GhostButton {
            text: "选择"
            Layout.alignment: Qt.AlignVCenter
            Layout.preferredWidth: 64 * ui
            Layout.preferredHeight: 30 * ui
            onClicked: { folderDlg.target = pr.target; folderDlg.open() }
        }
    }

    // ---------- 文件夹选择对话框 ----------
    FolderDialog {
        id: folderDlg
        property int target: 0
        onAccepted: {
            var p = folderDlg.folder.toString()
            if (p.indexOf("file:///") === 0) p = p.substring(8)
            if (folderDlg.target === 0) backend.inputPath = p
            else if (folderDlg.target === 1) backend.blacklistPath = p
            else backend.outputPath = p
        }
    }

    // ---------- 后端信号 -> UI（原样保留）----------
    Connections {
        target: backend
        function onLogChanged(text) {
            logArea.text += text + "\n"
            if (logArea.text.length > 20000)
                logArea.text = logArea.text.substring(logArea.text.length - 12000)
            logArea.cursorPosition = logArea.text.length
        }
        function onProgressChanged(v) {
            progBar.value = v
        }
        function onStatusChanged(s) {
            statusDot.color = s ? Theme.accentGreen : Theme.dotIdle
            statusText.text = s ? "SYS.ON" : "IDLE"
            statusText.color = s ? Theme.accentGreen : Theme.desc
            stateText.text = s ? "运行中" : "等待任务"
            stateText.color = s ? Theme.accentGreen : Theme.ready
            sidebarDot.color = s ? Theme.accentGreen : "#666666"
        }
    }

    // ---------- 根布局：侧栏 + 主内容（自适应）----------
    RowLayout {
        anchors.fill: parent
        anchors.margins: 20 * ui
        spacing: 16 * ui

        // ===== 纯黑侧栏（80px 浮动品牌栏）=====
        Rectangle {
            id: sidebar
            Layout.fillHeight: true
            Layout.preferredWidth: 80
            color: Theme.sidebar
            radius: 16
            ColumnLayout {
                anchors.fill: parent
                anchors.topMargin: 22 * ui
                anchors.bottomMargin: 18 * ui
                spacing: 16 * ui

                Rectangle {
                    Layout.alignment: Qt.AlignHCenter
                    width: 42 * ui; height: 42 * ui; radius: 13
                    color: Theme.primary
                    Text { text: "T"; color: "#FFFFFF"; font.family: "Microsoft YaHei";
                           font.bold: true; font.pixelSize: 20 * ui; anchors.centerIn: parent }
                }
                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Titan"; color: "#FFFFFF"; font.family: "Microsoft YaHei";
                    font.bold: true; font.pixelSize: 11 * ui
                }

                Item { Layout.fillHeight: true }

                // 三个极简线条图标：主页 / 数据 / 设置
                NavIcon {
                    Layout.alignment: Qt.AlignHCenter
                    active: true
                    pathData: "M3.5 10.5 L12 3.5 L20.5 10.5 M6 9.3 L6 20 L18 20 L18 9.3 M10 20 L10 14.5 L14 14.5 L14 20"
                }
                NavIcon {
                    Layout.alignment: Qt.AlignHCenter
                    pathData: "M3.5 20.5 L20.5 20.5 M7 20 L7 12 M12 20 L12 7 M17 20 L17 14.5"
                }
                NavIcon {
                    Layout.alignment: Qt.AlignHCenter
                    pathData: "M3.5 7 L9 7 M15 7 L20.5 7 M12 4.8 A2.2 2.2 0 1 0 12 9.2 A2.2 2.2 0 1 0 12 4.8 M3.5 12 L5 12 M11 12 L20.5 12 M8 9.8 A2.2 2.2 0 1 0 8 14.2 A2.2 2.2 0 1 0 8 9.8 M3.5 17 L14 17 M20 17 L20.5 17 M17 14.8 A2.2 2.2 0 1 0 17 19.2 A2.2 2.2 0 1 0 17 14.8"
                }

                Item { Layout.fillHeight: true }

                Rectangle {
                    id: sidebarDot
                    Layout.alignment: Qt.AlignHCenter
                    width: 10 * ui; height: 10 * ui; radius: 5
                    color: "#666666"
                }
            }
        }

        // ===== 主内容（自适应 ColumnLayout）=====
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 16 * ui

            // ----- 顶部标题栏（拖拽栏 + 状态灯 + 三键 + 主题切换）-----
            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: 40 * ui
                MouseArea {
                    id: dragArea
                    anchors.fill: parent
                    property int _px: 0
                    property int _py: 0
                    property int _wx: 0
                    property int _wy: 0
                    onPressed: {
                        _px = mouse.x; _py = mouse.y
                        _wx = root.x; _wy = root.y
                    }
                    onPositionChanged: {
                        if (root.visibility === Window.Maximized) return   // 仅非最大化可拖拽
                        root.x = _wx + (mouse.x - _px)
                        root.y = _wy + (mouse.y - _py)
                    }
                }
                RowLayout {
                    anchors.fill: parent
                    spacing: 8 * ui
                    Text {
                        text: "核心数据处理引擎"
                        color: Theme.title
                        font.family: "Microsoft YaHei"
                        font.bold: true
                        font.pixelSize: 16 * ui
                    }
                    Item { Layout.fillWidth: true }
                    // 状态灯（SYS.ON / IDLE）
                    RowLayout {
                        spacing: 6 * ui
                        Layout.alignment: Qt.AlignVCenter
                        Rectangle {
                            id: statusDot
                            width: 8 * ui; height: 8 * ui; radius: 4
                            color: Theme.dotIdle
                            Layout.alignment: Qt.AlignVCenter
                        }
                        Text {
                            id: statusText
                            text: "IDLE"
                            color: Theme.desc
                            font.family: "Microsoft YaHei"
                            font.bold: true
                            font.pixelSize: 11 * ui
                            Layout.alignment: Qt.AlignVCenter
                        }
                    }
                    Item { width: 4 * ui }
                    // 主题切换（☀ / ☾）
                    IconBtn {
                        glyph: Theme.isDarkMode ? "☀" : "☾"
                        onClicked: Theme.isDarkMode = !Theme.isDarkMode
                    }
                    // 最小化
                    IconBtn { glyph: "—"; onClicked: root.showMinimized() }
                    // 最大化 / 还原（图标跟随 visibility）
                    IconBtn {
                        glyph: root.visibility === Window.Maximized ? "❐" : "□"
                        onClicked: {
                            if (root.visibility === Window.Maximized) root.showNormal()
                            else root.showMaximized()
                        }
                    }
                    // 关闭
                    IconBtn { glyph: "✕"; danger: true; onClicked: Qt.quit() }
                }
            }

            // ----- 数据源路径卡片（马卡龙锚点）-----
            ShadowCard {
                Layout.fillWidth: true
                Layout.minimumHeight: 185 * ui
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 24 * ui
                    spacing: 10 * ui
                    Text {
                        text: "数据源路径"
                        color: Theme.title
                        font.family: "Microsoft YaHei"
                        font.bold: true
                        font.pixelSize: 15 * ui
                    }
                    PathRow { dotColor: "#E0F0FF"; dotGlyph: "▤"; dotGlyphColor: "#2E6FB0";
                              label: "底料入库"; pathText: backend.inputPath; target: 0 }
                    PathRow { dotColor: "#EAE4FF"; dotGlyph: "✕"; dotGlyphColor: "#7A5AC8";
                              label: "剔除名单"; pathText: backend.blacklistPath; target: 1 }
                    PathRow { dotColor: "#E1F7E5"; dotGlyph: "✓"; dotGlyphColor: "#2E9E5B";
                              label: "待触达库"; pathText: backend.outputPath; target: 2 }
                }
            }

            // ----- 中部双卡（1:1 自适应）-----
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 265 * ui
                spacing: 16 * ui

                // 左下：清洗引擎
                ShadowCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumWidth: 300
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 24 * ui
                        spacing: 14 * ui
                        Text {
                            text: "数据清洗引擎"
                            color: Theme.title
                            font.family: "Microsoft YaHei"
                            font.bold: true
                            font.pixelSize: 16 * ui
                        }
                        // 中央状态区：READY 缩为淡色背景水印
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            spacing: 8 * ui
                            Item { Layout.fillHeight: true }
                            Text {
                                id: stateText
                                text: "等待任务"
                                color: Theme.ready
                                opacity: 0.2                     // 降到 20% → 纯背景
                                font.family: "Microsoft YaHei"
                                font.weight: Font.Light
                                font.pixelSize: 24 * ui          // 字号缩为原来一半
                                Layout.alignment: Qt.AlignHCenter
                            }
                            Text {
                                text: "点击「一键清洗」开始处理"
                                color: Theme.desc
                                font.family: "Microsoft YaHei"
                                font.pixelSize: 12 * ui
                                Layout.alignment: Qt.AlignHCenter
                            }
                            Item { Layout.fillHeight: true }
                        }
                        PrimaryButton {
                            text: "一键清洗"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 46 * ui
                            onClicked: backend.startEngine()
                        }
                        ProgressBar {
                            id: progBar
                            value: 0
                            Layout.fillWidth: true
                            Layout.preferredHeight: 12 * ui
                            background: Rectangle { radius: 6; color: Theme.progressTrack }
                            contentItem: Rectangle {
                                width: progBar.visualPosition * progBar.width
                                height: progBar.height
                                radius: 6
                                color: Theme.primary
                            }
                            Behavior on value { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
                        }
                        Text {
                            text: "进度随处理实时更新"
                            color: Theme.desc
                            font.family: "Microsoft YaHei"
                            font.pixelSize: 11 * ui
                        }
                    }
                }

                // 右下：精准点单发货
                ShadowCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumWidth: 300
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 24 * ui
                        spacing: 9 * ui
                        Text {
                            text: "精准点单发货"
                            color: Theme.title
                            font.family: "Microsoft YaHei"
                            font.bold: true
                            font.pixelSize: 16 * ui
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: "年龄段"; color: Theme.desc; font.family: "Microsoft YaHei";
                                   font.pixelSize: 12 * ui; Layout.preferredWidth: 48 * ui }
                            CheckBox { id: cb30; text: "30-39"; checked: true; font.family: "Microsoft YaHei";
                                       palette.text: Theme.text }
                            CheckBox { id: cb40; text: "40-49"; checked: true; font.family: "Microsoft YaHei";
                                       palette.text: Theme.text }
                            CheckBox { id: cb50; text: "50+"; checked: true; font.family: "Microsoft YaHei";
                                       palette.text: Theme.text }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: "性别"; color: Theme.desc; font.family: "Microsoft YaHei";
                                   font.pixelSize: 12 * ui; Layout.preferredWidth: 48 * ui }
                            CheckBox { id: cbM; text: "男"; checked: true; font.family: "Microsoft YaHei";
                                       palette.text: Theme.text }
                            CheckBox { id: cbF; text: "女"; checked: true; font.family: "Microsoft YaHei";
                                       palette.text: Theme.text }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: "数量"; color: Theme.desc; font.family: "Microsoft YaHei";
                                   font.pixelSize: 12 * ui; Layout.preferredWidth: 48 * ui }
                            // 无边框浅灰底数字框
                            TextField {
                                id: qtyField
                                text: "50000"
                                Layout.preferredWidth: 140 * ui
                                Layout.preferredHeight: 38 * ui
                                color: Theme.fieldText
                                font.family: "Microsoft YaHei"
                                font.pixelSize: 14 * ui
                                leftPadding: 14 * ui
                                rightPadding: 14 * ui
                                verticalAlignment: TextInput.AlignVCenter
                                background: Rectangle {
                                    radius: 10
                                    color: "#F0F0F0"
                                    border.width: 0
                                }
                            }
                        }
                        Text {
                            text: "导出至 5_精准发货（待触达库同级）"
                            color: Theme.desc
                            font.family: "Microsoft YaHei"
                            font.pixelSize: 10 * ui
                        }
                        Item { Layout.fillHeight: true }
                        PrimaryButton {
                            text: "按条件精准导出"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 46 * ui
                            onClicked: {
                                var a = [], g = []
                                if (cb30.checked) a.push("30-39")
                                if (cb40.checked) a.push("40-49")
                                if (cb50.checked) a.push("50+")
                                if (cbM.checked) g.push("Male")
                                if (cbF.checked) g.push("Female")
                                backend.exportCustom(a, g, parseInt(qtyField.text, 10))
                            }
                        }
                    }
                }
            }

            // ----- 底部：深色日志大卡片（强黑白对比，占据剩余空间）-----
            ShadowCard {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 118 * ui
                cardColor: Theme.logBg
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 24 * ui
                    spacing: 10 * ui
                    Text {
                        text: "运行日志"
                        color: "#E8E8EA"
                        font.family: "Microsoft YaHei"
                        font.bold: true
                        font.pixelSize: 13 * ui
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: 12
                        color: Theme.logInner
                        TextArea {
                            id: logArea
                            anchors.fill: parent
                            anchors.margins: 10 * ui
                            readOnly: true
                            color: Theme.accentGreen
                            font.family: "Consolas"
                            font.pixelSize: 12 * ui
                            background: Rectangle { color: "transparent" }
                            text: "[READY] 引擎就绪。点击「一键清洗」开始处理。"
                        }
                    }
                }
            }
        }
    }
}
