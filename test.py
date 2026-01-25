import sys
import subprocess
import threading
import time
import json
import os
import re

from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSlider,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from PyQt6.QtCore import (
    QEvent,
    QMimeData,
    QObject,
    QSize,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QColor, QDrag, QIcon
from pynput import keyboard

CONFIG_FILE = os.path.expanduser("~/.sonar_config.json")

THEME = {
    "Bg": "#0F1117",
    "Card": "#171A23",
    "CardAlt": "#1C2030",
    "Accent": "#5EE7FF",
    "Game": "#5EE7FF",
    "Chat": "#B693FF",
    "Media": "#FF6B6B",
    "Text": "#E9EEF7",
    "Muted": "#FF6B6B",
    "Stroke": "#2A3040"
}


class AudioDataSignaler(QObject):
    update_apps = pyqtSignal(dict)


class HotkeyEdit(QLineEdit):
    hotkeyChanged = pyqtSignal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setReadOnly(True)
        self._last_parts = None

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.clear()
            self.hotkeyChanged.emit("")
            return
        if key == Qt.Key.Key_Escape:
            self.clearFocus()
            return

        modifiers = event.modifiers()
        parts = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            parts.append("<ctrl>")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            parts.append("<alt>")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            parts.append("<shift>")
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            parts.append("<cmd>")

        special_map = {
            Qt.Key.Key_Space: "<space>",
            Qt.Key.Key_Return: "<enter>",
            Qt.Key.Key_Enter: "<enter>",
            Qt.Key.Key_Tab: "<tab>",
            Qt.Key.Key_Backtab: "<tab>",
            Qt.Key.Key_Escape: "<esc>",
            Qt.Key.Key_Up: "<up>",
            Qt.Key.Key_Down: "<down>",
            Qt.Key.Key_Left: "<left>",
            Qt.Key.Key_Right: "<right>",
            Qt.Key.Key_Home: "<home>",
            Qt.Key.Key_End: "<end>",
            Qt.Key.Key_PageUp: "<pageup>",
            Qt.Key.Key_PageDown: "<pagedown>",
            Qt.Key.Key_Insert: "<insert>",
            Qt.Key.Key_Delete: "<delete>",
            Qt.Key.Key_Backspace: "<backspace>",
            Qt.Key.Key_CapsLock: "<capslock>",
            Qt.Key.Key_NumLock: "<numlock>",
            Qt.Key.Key_ScrollLock: "<scrolllock>",
            Qt.Key.Key_F1: "<f1>",
            Qt.Key.Key_F2: "<f2>",
            Qt.Key.Key_F3: "<f3>",
            Qt.Key.Key_F4: "<f4>",
            Qt.Key.Key_F5: "<f5>",
            Qt.Key.Key_F6: "<f6>",
            Qt.Key.Key_F7: "<f7>",
            Qt.Key.Key_F8: "<f8>",
            Qt.Key.Key_F9: "<f9>",
            Qt.Key.Key_F10: "<f10>",
            Qt.Key.Key_F11: "<f11>",
            Qt.Key.Key_F12: "<f12>",
        }

        key_name = None
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            key_name = None
        else:
            key_name = special_map.get(key)
            if not key_name:
                if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
                    key_name = chr(key).lower()
                elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
                    key_name = chr(key)
                else:
                    text = event.text()
                    if text:
                        key_name = text.lower()

        if key_name:
            parts.append(key_name)
            text_value = "+".join(parts)
            if text_value != self._last_parts:
                self._last_parts = text_value
                self.setText(text_value)
                self.hotkeyChanged.emit(text_value)
            self.clearFocus()


class SpacedComboBox(QComboBox):
    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        rect = popup.geometry()
        # Move popup down by 4 pixels to create a gap
        popup.move(rect.x(), rect.y() + 4)


class DraggableAppLabel(QFrame):
    def __init__(self, name, app_id, icon_name, parent_app):
        super().__init__()
        self.app_id = app_id
        self.parent_app = parent_app

        self.setStyleSheet(f"""
            QFrame {{
                background: {THEME['CardAlt']};
                border: 1px solid {THEME['Stroke']};
                border-radius: 8px;
            }}
            QFrame:hover {{
                background: #262B3B;
                border: 1px solid {THEME['Accent']};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        icon_label = QLabel()
        icon = QIcon.fromTheme(icon_name)
        if icon.isNull():
            icon = QIcon.fromTheme("audio-card")
        pixmap = icon.pixmap(QSize(20, 20))
        icon_label.setPixmap(pixmap)
        icon_label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(icon_label)

        text_label = QLabel(name[:18])
        text_label.setStyleSheet(f"color: {THEME['Text']}; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        layout.addWidget(text_label)
        layout.addStretch()

        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.parent_app.is_dragging_app = True
            drag = QDrag(self)
            mime_data = QMimeData()
            mime_data.setText(str(self.app_id))
            drag.setMimeData(mime_data)

            pix = self.grab()
            drag.setPixmap(pix)
            drag.setHotSpot(event.pos())

            drag.exec(Qt.DropAction.MoveAction)
            self.parent_app.is_dragging_app = False


class AudioChannel(QFrame):
    def __init__(self, name, vol_cb, mute_cb, hk_cb, move_app_cb, parent_app):
        super().__init__()
        self.name = name
        self.parent_app = parent_app
        self.move_app_cb = move_app_cb
        self.color = THEME.get(name, "#FFFFFF")

        self.setFixedWidth(270)
        self.setAcceptDrops(True)

        self.setStyleSheet(f"""
            QFrame#ChannelCard {{
                background: {THEME['Card']};
                border-radius: 18px;
                border: none;
            }}
        """)
        self.setObjectName("ChannelCard")

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(0, 0, 0, 90))
        shadow.setOffset(0, 6)
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(16)

        name_lbl = QLabel(name.upper())
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet(f"color: {self.color}; font-weight: 900; font-size: 16px; letter-spacing: 1px; border: none; background: transparent;")
        layout.addWidget(name_lbl)

        slider_wrap = QFrame()
        slider_wrap.setStyleSheet(f"background: {THEME['CardAlt']}; border: none; border-radius: 18px;")
        slider_layout = QVBoxLayout(slider_wrap)
        slider_layout.setContentsMargins(18, 16, 18, 16)
        slider_layout.setSpacing(0)

        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setRange(0, 100)
        self.slider.setMinimumHeight(300)
        self.slider.setFixedWidth(90)
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slider.setStyleSheet(f"""
            QSlider::groove:vertical {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #272B3A, stop:1 #171A24);
                width: 14px;
                border-radius: 7px;
                border: 1px solid rgba(255,255,255,0.08);
            }}
            QSlider::add-page:vertical {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {self.color}, stop:1 rgba(255,255,255,0.2));
                width: 14px;
                border-radius: 7px;
            }}
            QSlider::sub-page:vertical {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1E2230, stop:1 #141724);
                border-radius: 7px;
            }}
            QSlider::handle:vertical {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFFFFF, stop:1 #D3D7E4);
                height: 30px;
                width: 30px;
                margin: 0 -8px;
                border-radius: 15px;
                border: 2px solid rgba(0,0,0,0.25);
            }}
            QSlider::handle:vertical:hover {{
                background: {self.color};
                border: 2px solid rgba(255,255,255,0.9);
            }}
        """)
        self.slider.valueChanged.connect(lambda v: vol_cb(self.name, v))
        slider_layout.addWidget(self.slider, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(slider_wrap, alignment=Qt.AlignmentFlag.AlignCenter)

        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(16)
        ctrl_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        BTN_SIZE = 44
        ICON_SIZE = 22
        RADIUS = BTN_SIZE // 2

        gear_btn = QPushButton()
        gear_btn.setIcon(QIcon.fromTheme("preferences-system"))
        gear_btn.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        gear_btn.setFixedSize(BTN_SIZE, BTN_SIZE)
        gear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        gear_btn.clicked.connect(lambda: hk_cb(self.name))
        gear_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['CardAlt']};
                border: 2px solid rgba(255,255,255,0.12);
                border-radius: {RADIUS}px;
            }}
            QPushButton:hover {{
                background: #262B3B;
                border: 2px solid {THEME['Accent']};
            }}
        """)
        ctrl_layout.addWidget(gear_btn)

        self.mute_btn = QPushButton()
        self.mute_btn_style = f"""
            QPushButton {{
                background: {THEME['CardAlt']};
                border: 2px solid {self.color};
                border-radius: {RADIUS}px;
            }}
            QPushButton:hover {{
                background: #262B3B;
                border: 2px solid {self.color};
            }}
        """

        self.mute_btn.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.mute_btn.setFixedSize(BTN_SIZE, BTN_SIZE)
        self.mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mute_btn.clicked.connect(lambda: mute_cb(self.name))
        self.update_mute_icon(False)
        self.mute_btn.setStyleSheet(self.mute_btn_style)
        ctrl_layout.addWidget(self.mute_btn)

        layout.addLayout(ctrl_layout)

        apps_container = QFrame()
        apps_container.setStyleSheet("background: rgba(255,255,255,0.04); border-radius: 10px; border: none;")
        self.app_layout = QVBoxLayout(apps_container)
        self.app_layout.setContentsMargins(6, 6, 6, 6)
        self.app_layout.setSpacing(6)
        self.app_layout.addStretch()  # Ensure items start from top

        apps_scroll = QScrollArea()
        apps_scroll.setWidgetResizable(True)
        apps_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        apps_scroll.setFrameShape(QFrame.Shape.NoFrame)
        apps_scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 6px;
                margin: 0px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #1c2030;
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        apps_scroll.setWidget(apps_container)
        layout.addWidget(apps_scroll)
        # Remove bottom stretch to let scroll area expand
        # layout.addStretch()

    def update_mute_icon(self, is_muted):
        RADIUS = 22
        if is_muted:
            self.mute_btn.setIcon(QIcon.fromTheme("audio-volume-muted"))
            self.mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {THEME['Muted']};
                    border: 2px solid rgba(255,255,255,0.75);
                    border-radius: {RADIUS}px;
                }}
                QPushButton:hover {{
                    background: {THEME['Muted']};
                    border: 2px solid rgba(255,255,255,0.85);
                }}
            """)
        else:
            self.mute_btn.setIcon(QIcon.fromTheme("audio-volume-high"))
            self.mute_btn.setStyleSheet(self.mute_btn_style)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.accept()
            self.setStyleSheet(f"""
                QFrame#ChannelCard {{
                    background: {THEME['Card']};
                    border-radius: 18px;
                    border: none;
                }}
            """)

    def dragLeaveEvent(self, event):
        self.setStyleSheet(f"""
            QFrame#ChannelCard {{
                background: {THEME['Card']};
                border-radius: 18px;
                border: none;
            }}
        """)

    def dropEvent(self, event):
        app_id = event.mimeData().text()
        self.move_app_cb(app_id, self.name)
        self.setStyleSheet(f"""
            QFrame#ChannelCard {{
                background: {THEME['Card']};
                border-radius: 18px;
                border: none;
            }}
        """)
        event.accept()

    def update_apps_list(self, apps_info):
        # Remove existing items except the stretch at the end
        while self.app_layout.count() > 1:
            item = self.app_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Insert before the stretch item
        insert_idx = 0

        # Add real apps
        for app_name, app_id, icon_name in apps_info:
            app_widget = DraggableAppLabel(app_name, app_id, icon_name, self.parent_app)
            self.app_layout.insertWidget(insert_idx, app_widget)
            insert_idx += 1

        if not apps_info and self.app_layout.count() == 1: # Only stretch remains
            lbl = QLabel("No Apps")
            lbl.setStyleSheet("color: #4E5566; font-size: 10px; font-weight: bold; border: none; background: transparent;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.app_layout.insertWidget(0, lbl)


class FixedDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog)

    def showEvent(self, event):
        super().showEvent(event)
        if self.parent():
            geo = self.frameGeometry()
            center = self.parent().frameGeometry().center()
            geo.moveCenter(center)
            self.move(geo.topLeft())

    def moveEvent(self, event):
        if self.parent():
            geo = self.frameGeometry()
            center = self.parent().frameGeometry().center()
            geo.moveCenter(center)
            if self.pos() != geo.topLeft():
                self.move(geo.topLeft())
        super().moveEvent(event)


class SonarProRedesign(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SONAR LINUX ULTIMATE")
        self.resize(980, 880)
        self.setStyleSheet(f"background-color: {THEME['Bg']}; font-family: 'Segoe UI', Sans-Serif;")

        self.is_dragging_app = False
        self.sinks = {"Game": "Game", "Chat": "Chat", "Media": "Media"}

        # هنا يتم تحميل الإعدادات (بما في ذلك المخرج الصوتي المحفوظ)
        self.hotkeys_config = self.load_config()
        self.widgets = {}

        self.signaler = AudioDataSignaler()
        self.signaler.update_apps.connect(self.dispatch_app_updates)

        self.setup_ui()
        self.init_audio_engine()

        # تشغيل حلقات المزامنة والاختصارات
        threading.Thread(target=self.sync_loop, daemon=True).start()
        threading.Thread(target=self.start_hotkeys, daemon=True).start()

        # ---------------------------------------------------------
        # (الجديد) تطبيق إعداد المخرج الصوتي المحفوظ عند بدء التشغيل
        # ---------------------------------------------------------
        saved_output = self.hotkeys_config.get("selected_output")
        if saved_output:
            # نستخدم Thread لكي لا يتجمد البرنامج أثناء تنفيذ أوامر الصوت
            threading.Thread(target=lambda: self.apply_full_route(saved_output), daemon=True).start()

    def changeEvent(self, event):
        # (الجديد) تحويل التصغير إلى إخفاء في التراي
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized():
                # نستخدم Timer بسيط لضمان الإخفاء السلس
                QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def run_cmd(self, cmd):
        try:
            return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
        except:
            return ""

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {s: {"up": "", "down": "", "mute": ""} for s in self.sinks}

    def init_audio_engine(self):
        existing = self.run_cmd("pactl list short sinks")
        for name in self.sinks.values():
            if name not in existing:
                self.run_cmd(f"pactl load-module module-null-sink sink_name={name} sink_properties=device.description={name}_Audio")

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(36, 32, 36, 32)
        main_layout.setSpacing(20)

        header = QFrame()
        header.setStyleSheet("background: transparent; border: none;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        title_wrap = QVBoxLayout()
        title = QLabel("SONAR")
        title.setStyleSheet("color: white; font-size: 34px; font-weight: 900; border: none; letter-spacing: 2px;")
        subtitle = QLabel("AUDIO MIXER")
        subtitle.setStyleSheet(f"color: {THEME['Accent']}; font-size: 14px; font-weight: 700; border: none; margin-top: -4px;")
        title_wrap.addWidget(title)
        title_wrap.addWidget(subtitle)
        header_layout.addLayout(title_wrap)
        header_layout.addStretch()

        setup_btn = QPushButton("INITIAL SETUP")
        setup_btn.setIcon(QIcon.fromTheme("utilities-terminal"))
        setup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        setup_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {THEME['Accent']}, stop:1 #88F5FF);
                color: #0B0C10;
                font-weight: 800;
                padding: 10px 20px;
                border-radius: 10px;
                border: none;
            }}
            QPushButton:hover {{
                background: #FFFFFF;
            }}
        """)
        setup_btn.clicked.connect(self.open_setup_dialog)
        header_layout.addWidget(setup_btn)
        main_layout.addWidget(header)

        mixer_row = QHBoxLayout()
        mixer_row.setSpacing(24)
        for name in self.sinks.keys():
            w = AudioChannel(name, self.set_vol, self.do_mute, self.open_hk_dialog, self.move_app_to_sink, self)
            self.widgets[name] = w
            mixer_row.addWidget(w)
        main_layout.addLayout(mixer_row)

        # ---------------------------------------------------------
        # (الجديد) إعدادات System Tray
        # ---------------------------------------------------------
        self.tray_icon = QSystemTrayIcon(self)
        # محاولة استخدام أيقونة النظام، إذا لم توجد نستخدم أيقونة بديلة
        icon = QIcon.fromTheme("audio-card")
        if icon.isNull():
            icon = QIcon.fromTheme("multimedia-volume-control")
        self.tray_icon.setIcon(icon)

        # إنشاء القائمة عند الضغط كليك يمين
        tray_menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.showNormal)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.instance().quit)

        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

        # عند الضغط كليك يسار على الأيقونة يفتح البرنامج
        self.tray_icon.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)

    def move_app_to_sink(self, app_id, target_name):
        self.run_cmd(f"pactl move-sink-input {app_id} {target_name}")

    def set_vol(self, name, val):
        self.run_cmd(f"pactl set-sink-volume {name} {int(val)}%")

    def do_mute(self, name):
        self.run_cmd(f"pactl set-sink-mute {name} toggle")

    def dispatch_app_updates(self, data):
        if not self.is_dragging_app:
            for name, apps in data.items():
                if name in self.widgets:
                    self.widgets[name].update_apps_list(apps)

    def sync_loop(self):
        while True:
            for name in self.sinks:
                vol_raw = self.run_cmd(f"pactl get-sink-volume {name}")
                mute_raw = self.run_cmd(f"pactl get-sink-mute {name}")
                if "%" in vol_raw:
                    try:
                        v = int(vol_raw.split('%')[0].split('/')[-1].strip())
                        is_muted = "yes" in mute_raw.lower()

                        w = self.widgets[name]
                        if not w.slider.isSliderDown():
                            w.slider.blockSignals(True)
                            w.slider.setValue(v)
                            w.slider.blockSignals(False)

                        w.update_mute_icon(is_muted)
                    except:
                        pass

            if not self.is_dragging_app:
                app_mapping = {"Game": [], "Chat": [], "Media": []}
                sink_id_map = {}
                sink_list = self.run_cmd("pactl list short sinks")
                for line in sink_list.split('\n'):
                    parts = line.split('\t')
                    if len(parts) > 1:
                        for s_name in self.sinks:
                            if s_name in parts[1]:
                                sink_id_map[parts[0]] = s_name

                inputs_raw = self.run_cmd("pactl list sink-inputs")
                blocks = inputs_raw.split("Sink Input #")
                for block in blocks:
                    if not block.strip():
                        continue
                    input_id_match = re.search(r"^(\d+)", block)
                    sink_match = re.search(r"Sink: (\d+)", block)
                    if input_id_match and sink_match:
                        i_id = input_id_match.group(1)
                        s_id = sink_match.group(1)
                        if s_id in sink_id_map:
                            target_track = sink_id_map[s_id]
                            app_name = "Unknown"
                            icon_name = "audio-card"
                            name_match = re.search(r'application.name = "(.*?)"', block)
                            if name_match:
                                app_name = name_match.group(1)
                            icon_match = re.search(r'application.icon_name = "(.*?)"', block)
                            if icon_match:
                                icon_name = icon_match.group(1)
                            elif "brave" in app_name.lower():
                                icon_name = "brave-browser"
                            elif "discord" in app_name.lower():
                                icon_name = "discord"
                            elif "firefox" in app_name.lower():
                                icon_name = "firefox"
                            elif "chrome" in app_name.lower():
                                icon_name = "google-chrome"
                            elif "spotify" in app_name.lower():
                                icon_name = "spotify-client"

                            app_mapping[target_track].append((app_name, i_id, icon_name))
                self.signaler.update_apps.emit(app_mapping)
            time.sleep(1)

    def start_hotkeys(self):
        def on_press(sink, action):
            if action == "up":
                self.run_cmd(f"pactl set-sink-volume {sink} +5%")
            elif action == "down":
                self.run_cmd(f"pactl set-sink-volume {sink} -5%")
            elif action == "mute":
                self.do_mute(sink)
        while True:
            hotkeys = {
                key: (lambda s=sn, a=act: on_press(s, a))
                for sn, acts in self.hotkeys_config.items()
                if sn in self.sinks
                for act, key in acts.items() if key
            }
            if hotkeys:
                try:
                    with keyboard.GlobalHotKeys(hotkeys) as h:
                        h.join()
                except:
                    pass
            time.sleep(1)

    def open_hk_dialog(self, ch):
        d = FixedDialog(self)
        d.setWindowTitle("Shortcuts")
        d.setFixedSize(440, 300)
        d.setStyleSheet(f"background: {THEME['Card']}; color: white; border-radius: 12px;")

        l = QVBoxLayout(d)
        l.setContentsMargins(12, 10, 12, 10)
        l.setSpacing(8)

        title = QLabel(f"HOTKEYS: {ch.upper()}")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 13px; font-weight: 700; color: #C8D0E0; margin: 0 0 8px 0;")
        l.addWidget(title)

        actions = [
            ("mute", "Mute", "audio-volume-muted"),
            ("down", "Volume Down", "go-down"),
            ("up", "Volume Up", "go-up")
        ]
        for act, label, icon_name in actions:
            row_wrap = QFrame()
            row_wrap.setStyleSheet(f"background: {THEME['CardAlt']}; border-radius: 10px;")
            row = QHBoxLayout(row_wrap)
            row.setContentsMargins(10, 8, 10, 8)
            row.setSpacing(10)

            icon_lbl = QLabel()
            icon_pix = QIcon.fromTheme(icon_name).pixmap(QSize(24, 24))
            icon_lbl.setPixmap(icon_pix)
            icon_lbl.setStyleSheet("background: transparent;")
            row.addWidget(icon_lbl)

            text_lbl = QLabel(label)
            text_lbl.setStyleSheet("color: #C8D0E0; font-size: 12px; font-weight: 700;")
            text_lbl.setFixedWidth(110)
            row.addWidget(text_lbl)

            e = HotkeyEdit()
            e.setText(self.hotkeys_config[ch][act])
            e.setPlaceholderText("Press keys...")
            e.setStyleSheet(f"""
                QLineEdit {{
                    background: #11141D;
                    padding: 8px 10px;
                    border: 1px solid transparent;
                    border-radius: 8px;
                    color: white;
                    min-width: 190px;
                }}
                QLineEdit:focus {{
                    background: #141A24;
                    border: 2px solid {THEME['Accent']};
                }}
            """)
            row.addWidget(e)
            l.addWidget(row_wrap)
            e.hotkeyChanged.connect(lambda value, act=act: self.save_hk_value(ch, act, value))
        d.setFocus()
        d.exec()

    def save_hk(self, ch, data):
        self.hotkeys_config[ch] = data
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.hotkeys_config, f)

    def save_hk_value(self, ch, act, value):
        self.hotkeys_config[ch][act] = value
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.hotkeys_config, f)

    def open_setup_dialog(self):
        hw_info = {}
        output = self.run_cmd("pactl list sinks")
        curr = ""
        # استخراج الأجهزة المتاحة
        for line in output.split('\n'):
            line = line.strip()
            if line.startswith("Name:"):
                curr = line.split(":", 1)[1].strip()
            elif line.startswith("Description:") and curr:
                desc = line.split(":", 1)[1].strip()
                if curr not in self.sinks.values():
                    hw_info[desc] = curr

        d = FixedDialog(self)
        d.setWindowTitle("Audio Routing Setup")
        d.setFixedSize(400, 240)
        d.setStyleSheet(f"background: #0C0F16; color: white; border-radius: 18px;")

        l = QVBoxLayout(d)
        l.setContentsMargins(16, 16, 16, 16)
        l.setSpacing(5)

        desc = QLabel("Select your primary output device")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("font-size: 13px; font-weight: 600; color: #E9EEF7; margin-top: 20px; margin-bottom: 10px;")
        l.addWidget(desc)

        out_box = QFrame()
        out_box.setStyleSheet("background: transparent;")
        out_layout = QVBoxLayout(out_box)
        out_layout.setContentsMargins(0, 0, 0, 0)
        out_layout.setSpacing(0)

        c = SpacedComboBox()
        c.addItems(list(hw_info.keys()))

        # --- التعديل هنا: تحديد العنصر المحفوظ سابقاً ---
        saved_sink = self.hotkeys_config.get("selected_output")
        if saved_sink:
            # البحث عن الاسم الظاهر الذي يقابل المعرف المحفوظ
            for index, (desc_text, sink_id) in enumerate(hw_info.items()):
                if sink_id == saved_sink:
                    c.setCurrentIndex(index)
                    break
        else:
            c.setCurrentIndex(0)
        # -----------------------------------------------

        c.setStyleSheet("""
            QComboBox {
                background: #171a23;
                padding: 10px 14px;
                color: white;
                border: 1px solid #2A3242;
                border-radius: 12px;
                font-size: 12px;
                font-weight: 500;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                image: none;
                width: 0px;
                height: 0px;
            }
            QComboBox QAbstractItemView {
                background: #171a23;
                selection-background-color: #243049;
                color: white;
                border: 1px solid #2A3242;
                padding: 4px;
                border-radius: 12px;
                outline: none;
            }
        """)
        out_layout.addWidget(c)
        l.addWidget(out_box)

        l.addStretch()

        b = QPushButton("APPLY")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet("background: #5EE7FF; color: #0B0C10; font-weight: bold; padding: 12px; border-radius: 12px; font-size: 12px;")
        b.clicked.connect(lambda: [self.apply_full_route(hw_info.get(c.currentText(), "")), d.close()])
        l.addWidget(b)
        d.exec()

    def apply_full_route(self, sink_id):
        # 1. تنفيذ الأوامر الصوتية
        for v in self.sinks.values():
            self.run_cmd(f"pw-link {v}:monitor_FL {sink_id}:playback_FL")
            self.run_cmd(f"pw-link {v}:monitor_FR {sink_id}:playback_FR")

        self.run_cmd("pactl set-default-sink Game")
        print(f"Routing applied to {sink_id}")

        # 2. حفظ الاختيار في ملف الإعدادات
        if sink_id:
            self.hotkeys_config["selected_output"] = sink_id
            try:
                with open(CONFIG_FILE, 'w') as f:
                    json.dump(self.hotkeys_config, f)
            except Exception as e:
                print(f"Error saving config: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # منع إغلاق التطبيق عند إغلاق آخر نافذة (لأننا نعتمد على التراي)
    app.setQuitOnLastWindowClosed(False)

    win = SonarProRedesign()

    # (الجديد) فحص إذا كان هناك أمر --minimized
    if "--minimized" in sys.argv:
        win.hide()  # يبدأ مخفياً في التراي
    else:
        win.show()  # يبدأ ظاهراً بشكل طبيعي

    sys.exit(app.exec())

