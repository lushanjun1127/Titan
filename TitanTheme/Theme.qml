pragma Singleton
import QtQuick 2.15

// Theme.qml —— 全局主题系统（单例）
// false = 浅色（金融冷灰白 / Coinview 风）；true = 深色（极客黑）
// 所有颜色经绑定派生：翻转 isDarkMode 即全量换肤。
QtObject {
    id: theme

    property bool isDarkMode: false

    // ---------- 背景与表面 ----------
    readonly property color bg:           isDarkMode ? "#0F0F11" : "#F5F7FA"
    readonly property color card:          isDarkMode ? "#18181A" : "#FFFFFF"
    readonly property color fieldBg:       isDarkMode ? "#2A2A2E" : "#F0F2F5"
    readonly property color fieldBorder:   isDarkMode ? "#3A3A40" : "#E0E3E8"
    readonly property color fieldText:      isDarkMode ? "#E8E8EA" : "#111111"
    readonly property color logBg:         isDarkMode ? "#000000" : "#1C1C1E"
    readonly property color logInner:      isDarkMode ? "#0A0A0C" : "#161618"

    // ---------- 文字 ----------
    readonly property color title:         isDarkMode ? "#F2F2F5" : "#111111"
    readonly property color text:          isDarkMode ? "#E8E8EA" : "#333333"
    readonly property color desc:          isDarkMode ? "#9A9AA2" : "#888888"
    readonly property color ready:         isDarkMode ? "#3A3A40" : "#D8D8DC"

    // ---------- 强调色 ----------
    readonly property color primary:       isDarkMode ? "#4F9BFF" : "#2979FF"
    readonly property color accentGreen:   "#00E676"
    readonly property color dotIdle:       isDarkMode ? "#555555" : "#B8B8BE"

    // ---------- 侧栏（始终纯黑品牌栏）----------
    readonly property color sidebar:       "#0A0A0A"
    readonly property color sideIcon:      "#5A5A60"

    // ---------- 主按钮（浅色黑底白字 / 深色白底黑字）----------
    readonly property color btnBg:         isDarkMode ? "#FFFFFF" : "#000000"
    readonly property color btnBgHover:    isDarkMode ? "#D8D8DC" : "#333333"
    readonly property color btnText:       isDarkMode ? "#0A0A0A" : "#FFFFFF"

    // ---------- 幽灵按钮（次要操作）----------
    readonly property color ghostBg:       isDarkMode ? "#2A2A2E" : "#F0F2F5"
    readonly property color ghostHover:    isDarkMode ? "#3A3A40" : "#E4E7EC"
    readonly property color ghostText:     isDarkMode ? "#E8E8EA" : "#333333"

    // ---------- 进度条轨道 ----------
    readonly property color progressTrack: isDarkMode ? "#2A2A2E" : "#EDEFF3"
}
