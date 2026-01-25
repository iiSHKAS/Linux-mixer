import sys
import subprocess
import threading
import time
import json
import os
import re
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSlider, QPushButton, QLabel, QDialog, QComboBox, QLineEdit,
    QFrame, QGraphicsDropShadowEffect, QScrollArea, QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QMimeData, QSize, QTimer, QEvent
from PyQt6.QtGui import QDrag, QIcon, QColor, QAction
from pynput import keyboard

CONFIG_FILE = os.path.expanduser("~/.mux_config.json")

AUDIO_SINKS = ["Game", "Chat", "Media"]
STREAM_MIX_NAME = "Stream_Mix"
MIC_DISPLAY_NAME = "Mux Mic"
MIC_INTERNAL_ID = "Mux_Mic"
INTERNAL_MIC_PROCESSING = "Internal_Mic_Processing"

THEME = {
    "Bg": "#0F1117",
    "Card": "#171A23",
    "CardAlt": "#1C2030",
    "Accent": "#5EE7FF",
    "Game": "#8CFF6A",
    "Chat": "#B693FF",
    "Media": "#FF6B6B",
    "Mic": "#FFD34D",
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

class ChannelState:
    def __init__(self, name):
        self.name = name
        self.volume = 0
        self.stream_volume = 0
        self.muted = False
        self.stream_muted = False
        self.apps = []

def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        if item.layout():
            _clear_layout(item.layout())

class AudioChannel(QFrame):
    def __init__(self, name, vol_cb, stream_vol_cb, mute_cb, stream_mute_cb, hk_cb, move_app_cb, parent_app, streamer_mode, slider_height, streamer_slider_height):
        super().__init__()
        self.name = name
        self.parent_app = parent_app
        self.move_app_cb = move_app_cb
        self.volume_cb = vol_cb
        self.stream_volume_cb = stream_vol_cb
        self.mute_cb = mute_cb
        self.stream_mute_cb = stream_mute_cb
        self.hk_cb = hk_cb
        self.color = THEME.get(name, "#FFFFFF")
        self.streamer_mode = streamer_mode
        self.slider_height = slider_height
        self.streamer_slider_height = streamer_slider_height

        self.user_slider = None
        self.stream_slider = None
        self.user_mute_btn = None
        self.stream_mute_btn = None

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
        layout.setSpacing(12)

        header = QFrame()
        header.setStyleSheet("background: #1C2030; border-radius: 12px;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)
        name_lbl = QLabel(name.upper())
        name_lbl.setStyleSheet(f"color: {self.color}; font-weight: 900; font-size: 18px; letter-spacing: 1px; border: none; background: transparent;")
        header_layout.addStretch()
        header_layout.addWidget(name_lbl)
        header_layout.addStretch()

        gear_btn = QPushButton()
        gear_btn.setIcon(QIcon.fromTheme("preferences-system"))
        gear_btn.setIconSize(QSize(22, 22))
        gear_btn.setFixedSize(44, 44)
        gear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        gear_btn.clicked.connect(lambda: hk_cb(self.name))
        gear_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['CardAlt']};
                border: 2px solid rgba(255,255,255,0.12);
                border-radius: 22px;
            }}
            QPushButton:hover {{
                background: #262B3B;
                border: 2px solid {THEME['Accent']};
            }}
        """)
        header_layout.addWidget(gear_btn)
        layout.addWidget(header)

        self.slider_wrap = QFrame()
        self.slider_wrap.setStyleSheet(f"background: {THEME['CardAlt']}; border: none; border-radius: 18px;")
        self.slider_layout = QHBoxLayout(self.slider_wrap)
        self.slider_layout.setContentsMargins(18, 14, 18, 14)
        self.slider_layout.setSpacing(12)
        self._rebuild_sliders()
        layout.addWidget(self.slider_wrap)

        self.btn_wrap = QFrame()
        self.btn_wrap.setStyleSheet("background: #1C2030; border-radius: 12px;")
        self.btn_layout = QHBoxLayout(self.btn_wrap)
        self.btn_layout.setContentsMargins(8, 6, 8, 6)
        self.btn_layout.setSpacing(12)
        self.btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rebuild_buttons()
        layout.addWidget(self.btn_wrap)

        apps_container = QFrame()
        apps_container.setStyleSheet("background: rgba(255,255,255,0.04); border-radius: 10px; border: none;")
        self.app_layout = QVBoxLayout(apps_container)
        self.app_layout.setContentsMargins(6, 6, 6, 6)
        self.app_layout.setSpacing(6)
        self.app_layout.addStretch()

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

    def _slider_stylesheet(self, color):
        return f"""
            QSlider::groove:vertical {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #272B3A, stop:1 #171A24);
                width: 14px;
                border-radius: 7px;
                border: 1px solid rgba(255,255,255,0.08);
            }}
            QSlider::add-page:vertical {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {color}, stop:1 rgba(255,255,255,0.2));
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
                background: {color};
                border: 2px solid rgba(255,255,255,0.9);
            }}
        """

    def _build_slider(self, color, height, on_change):
        slider = QSlider(Qt.Orientation.Vertical)
        slider.setRange(0, 100)
        slider.setMinimumHeight(height)
        slider.setFixedWidth(90)
        slider.setCursor(Qt.CursorShape.PointingHandCursor)
        slider.setStyleSheet(self._slider_stylesheet(color))
        slider.valueChanged.connect(on_change)
        return slider

    def _rebuild_sliders(self):
        _clear_layout(self.slider_layout)
        self.user_slider = None
        self.stream_slider = None

        if self.streamer_mode:
            user_col = QVBoxLayout()
            user_label = QLabel("USER")
            user_label.setStyleSheet(f"color: {THEME['Text']}; font-size: 11px; font-weight: 700; border: none; background: transparent;")
            user_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            user_col.addWidget(user_label)
            self.user_slider = self._build_slider(self.color, self.streamer_slider_height, lambda v: self.volume_cb(self.name, v))
            user_col.addWidget(self.user_slider, alignment=Qt.AlignmentFlag.AlignCenter)

            stream_col = QVBoxLayout()
            stream_label = QLabel("STREAM")
            stream_label.setStyleSheet(f"color: {THEME['Text']}; font-size: 11px; font-weight: 700; border: none; background: transparent;")
            stream_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stream_col.addWidget(stream_label)
            self.stream_slider = self._build_slider(THEME['Accent'], self.streamer_slider_height, lambda v: self.stream_volume_cb(self.name, v))
            stream_col.addWidget(self.stream_slider, alignment=Qt.AlignmentFlag.AlignCenter)

            self.slider_layout.addLayout(user_col)
            self.slider_layout.addLayout(stream_col)
        else:
            col = QVBoxLayout()
            self.user_slider = self._build_slider(self.color, self.slider_height, lambda v: self.volume_cb(self.name, v))
            col.addWidget(self.user_slider, alignment=Qt.AlignmentFlag.AlignCenter)
            self.slider_layout.addLayout(col)

    def _icon_for_mute(self, muted):
        if self.name == 'Mic':
            if muted:
                icon = QIcon.fromTheme("audio-input-microphone-muted")
                if icon.isNull():
                    icon = QIcon.fromTheme("microphone-sensitivity-muted")
            else:
                icon = QIcon.fromTheme("audio-input-microphone")
                if icon.isNull():
                    icon = QIcon.fromTheme("microphone-sensitivity-high")
        else:
            icon = QIcon.fromTheme("audio-volume-muted" if muted else "audio-volume-high")
        return icon

    def _apply_mute_style(self, btn, muted, border_color):
        if muted:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {THEME['Muted']};
                    border: 2px solid rgba(255,255,255,0.75);
                    border-radius: 22px;
                }}
                QPushButton:hover {{
                    background: {THEME['Muted']};
                    border: 2px solid rgba(255,255,255,0.85);
                }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {THEME['CardAlt']};
                    border: 2px solid {border_color};
                    border-radius: 22px;
                }}
                QPushButton:hover {{
                    background: #262B3B;
                    border: 2px solid {border_color};
                }}
            """)

    def _build_mute_button(self, on_click):
        btn = QPushButton()
        btn.setIconSize(QSize(22, 22))
        btn.setFixedSize(44, 44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(on_click)
        return btn

    def _rebuild_buttons(self):
        _clear_layout(self.btn_layout)
        self.user_mute_btn = self._build_mute_button(lambda: self.mute_cb(self.name))
        self.btn_layout.addWidget(self.user_mute_btn)
        if self.streamer_mode:
            self.stream_mute_btn = self._build_mute_button(lambda: self.stream_mute_cb(self.name))
            self.btn_layout.addWidget(self.stream_mute_btn)
        else:
            self.stream_mute_btn = None

    def set_streamer_mode(self, enabled):
        if self.streamer_mode == enabled:
            return
        self.streamer_mode = enabled
        self._rebuild_sliders()
        self._rebuild_buttons()

    def update_state(self, volume, stream_volume, muted, stream_muted):
        if self.user_slider and not self.user_slider.isSliderDown():
            self.user_slider.blockSignals(True)
            self.user_slider.setValue(volume)
            self.user_slider.blockSignals(False)
        if self.stream_slider and not self.stream_slider.isSliderDown():
            self.stream_slider.blockSignals(True)
            self.stream_slider.setValue(stream_volume)
            self.stream_slider.blockSignals(False)

        if self.user_mute_btn:
            self.user_mute_btn.setIcon(self._icon_for_mute(muted))
            self._apply_mute_style(self.user_mute_btn, muted, self.color)
        if self.stream_mute_btn:
            self.stream_mute_btn.setIcon(self._icon_for_mute(stream_muted))
            self._apply_mute_style(self.stream_mute_btn, stream_muted, THEME['Accent'])

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

class MuxHome(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MUX")
        self.setFixedSize(1285, 735)
        self.setStyleSheet(f"background-color: {THEME['Bg']}; font-family: 'Segoe UI', Sans-Serif;")

        self.is_dragging_app = False
        self.sinks = {"Game": "Game", "Chat": "Chat", "Media": "Media"}
        self.channels = {name: ChannelState(name) for name in ["Game", "Chat", "Media", "Mic"]}
        self.hotkeys_config = {}
        self.active_inputs = {}
        self.streamer_mode = False
        self.selected_output = None
        self.selected_input = None
        self.start_in_tray = False
        self.tray_icon = None
        self.tray_menu = None
        self.tray_toggle_action = None
        self.restoring_from_tray = False

        self.hotkey_listener = None
        self.hotkey_reload_event = threading.Event()

        self.signaler = AudioDataSignaler()
        self.signaler.update_apps.connect(self.dispatch_app_updates)

        self.hotkeys_config = self.load_config()
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save_config)
        self.setup_ui()
        self.init_tray()
        self.init_audio_engine()
        self.startup_cleanup()
        self.initial_setup()
        self.apply_saved_volumes()
        if self.start_in_tray:
            QTimer.singleShot(0, self.hide_to_tray)

        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.sync_once)
        self.sync_timer.start(1000)
        self.sync_once()

        threading.Thread(target=self.start_hotkeys, daemon=True).start()
        self.register_hotkeys()

    def run_cmd(self, cmd):
        try:
            return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
        except:
            return ""

    def init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = QIcon.fromTheme("audio-card")
        if icon.isNull():
            icon = self.windowIcon()
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_menu = QMenu()
        self.tray_toggle_action = QAction("Hide", self)
        self.tray_toggle_action.triggered.connect(self.toggle_tray)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        self.tray_menu.addAction(self.tray_toggle_action)
        self.tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.toggle_tray()

    def toggle_tray(self):
        if self.isVisible():
            self.hide_to_tray()
        else:
            self.show_from_tray()

    def hide_to_tray(self):
        if not self.tray_icon:
            return
        self.hide()
        if self.tray_toggle_action:
            self.tray_toggle_action.setText("Show")

    def show_from_tray(self):
        self.restoring_from_tray = True
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()
        if self.tray_toggle_action:
            self.tray_toggle_action.setText("Hide")
        QTimer.singleShot(200, self._clear_restore_flag)

    def _clear_restore_flag(self):
        self.restoring_from_tray = False

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized() and not self.restoring_from_tray:
                QTimer.singleShot(0, self.hide_to_tray)
        super().changeEvent(event)

    def load_config(self):
        defaults = {s: {"up": "", "down": "", "mute": "", "stream_up": "", "stream_down": "", "stream_mute": ""} for s in self.channels}
        hotkeys = defaults
        selected_output = None
        selected_input = None
        streamer_mode = False
        start_in_tray = False
        user_volumes = {name: None for name in self.channels}
        stream_volumes = {name: None for name in self.channels}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                if "hotkeys" in data:
                    raw = data.get("hotkeys", {})
                    hotkeys = {k: {kk: str(vv) for kk, vv in v.items()} for k, v in raw.items()}
                    selected_output = data.get("selected_output")
                    selected_input = data.get("selected_input")
                    streamer_mode = data.get("streamer_mode") is True
                    start_in_tray = data.get("start_in_tray") is True
                    raw_user_volumes = data.get("user_volumes", {})
                    raw_stream_volumes = data.get("stream_volumes", {})
                    for name in self.channels:
                        if name in raw_user_volumes:
                            try:
                                user_volumes[name] = int(raw_user_volumes[name])
                            except:
                                user_volumes[name] = None
                        if name in raw_stream_volumes:
                            try:
                                stream_volumes[name] = int(raw_stream_volumes[name])
                            except:
                                stream_volumes[name] = None
                else:
                    hotkeys = {k: {kk: str(vv) for kk, vv in v.items()} for k, v in data.items()}
            except:
                hotkeys = defaults

        for ch in defaults:
            if ch not in hotkeys:
                hotkeys[ch] = defaults[ch]
            else:
                for key in defaults[ch]:
                    hotkeys[ch].setdefault(key, "")

        self.selected_output = selected_output
        self.selected_input = selected_input
        self.streamer_mode = streamer_mode
        self.start_in_tray = start_in_tray
        self.user_volumes = user_volumes
        self.stream_volumes = stream_volumes
        return hotkeys

    def save_config(self):
        data = {
            "hotkeys": self.hotkeys_config,
            "selected_output": self.selected_output,
            "selected_input": self.selected_input,
            "streamer_mode": self.streamer_mode,
            "start_in_tray": self.start_in_tray,
            "user_volumes": self.user_volumes,
            "stream_volumes": self.stream_volumes
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(data, f)

    def schedule_save(self):
        if not self.save_timer.isActive():
            self.save_timer.start(500)

    def apply_saved_volumes(self):
        for name, val in self.user_volumes.items():
            if val is None:
                continue
            self.channels[name].volume = int(val)
            self._apply_user_volume(name, int(val))
        if self.streamer_mode:
            QTimer.singleShot(150, self.apply_stream_defaults)

    def init_audio_engine(self):
        existing = self.run_cmd("pactl list short sinks")
        for name in self.sinks.values():
            if f"{name}\t" not in existing:
                self.create_device(name, name, is_source=False)

        existing_sources = self.run_cmd("pactl list short sources")
        if MIC_INTERNAL_ID not in existing_sources:
            self.create_device(MIC_INTERNAL_ID, MIC_DISPLAY_NAME, is_source=True)

    def create_device(self, name, desc, is_source):
        props = f"device.description='{desc}' node.nick='{desc}' media.name='{desc}' device.product.name='{desc}'"
        if is_source:
            self.run_cmd(f"pactl load-module module-null-sink sink_name={INTERNAL_MIC_PROCESSING} sink_properties=\"device.description='INTERNAL'\"")
            time.sleep(0.1)
            self.run_cmd(f"pactl load-module module-remap-source master={INTERNAL_MIC_PROCESSING}.monitor source_name={name} source_properties=\"{props} device.icon_name='audio-input-microphone'\"")
        else:
            self.run_cmd(f"pactl load-module module-null-sink sink_name={name} sink_properties=\"{props}\"")
            self.run_cmd(f"pactl set-sink-volume {name} 100%")
            self.run_cmd(f"pactl set-sink-mute {name} 0")

    def startup_cleanup(self):
        self.remove_links()
        mods = self.run_cmd("pactl list short modules")
        for line in mods.split('\n'):
            if f"sink_name={STREAM_MIX_NAME}" in line:
                mod_id = line.split('\t')[0].strip()
                if mod_id:
                    self.run_cmd(f"pactl unload-module {mod_id}")

    def initial_setup(self):
        phy_out = self.selected_output
        if phy_out:
            self.run_cmd(f"pactl set-sink-mute {phy_out} 1")
        self.rebuild_routing()
        self.set_system_defaults()
        self.refresh_input_ids()
        if phy_out:
            time.sleep(0.3)
            self.run_cmd(f"pactl set-sink-mute {phy_out} 0")

    def handle_mode_toggle(self):
        self.save_config()
        phy_out = self.selected_output
        if phy_out:
            self.run_cmd(f"pactl set-sink-mute {phy_out} 1")
        self.rebuild_routing()
        self.set_system_defaults()
        self.refresh_input_ids()
        if self.streamer_mode:
            QTimer.singleShot(150, self.apply_stream_defaults)
        if phy_out:
            time.sleep(0.3)
            self.run_cmd(f"pactl set-sink-mute {phy_out} 0")

    def set_system_defaults(self):
        self.run_cmd("pactl set-default-sink Game")
        self.run_cmd(f"pactl set-default-source {MIC_INTERNAL_ID}")

    def remove_links(self):
        output = self.run_cmd("pactl list sink-inputs")
        for block in output.split("Sink Input #"):
            if not block.strip():
                continue
            if 'media.name = "Link_' not in block:
                continue
            owner_match = re.search(r"Owner Module: (\d+)", block)
            if owner_match:
                mod_id = owner_match.group(1)
                if mod_id:
                    self.run_cmd(f"pactl unload-module {mod_id}")

    def rebuild_routing(self):
        phy_out = self.selected_output
        phy_mic = self.selected_input
        self.remove_links()
        if not phy_out:
            return

        if self.streamer_mode:
            mods = self.run_cmd("pactl list short modules")
            if f"sink_name={STREAM_MIX_NAME}" not in mods:
                self.create_device(STREAM_MIX_NAME, "Stream Mix", is_source=False)
        else:
            mods = self.run_cmd("pactl list short modules")
            for line in mods.split('\n'):
                if f"sink_name={STREAM_MIX_NAME}" in line:
                    mod_id = line.split('\t')[0].strip()
                    if mod_id:
                        self.run_cmd(f"pactl unload-module {mod_id}")

        for ch in self.sinks:
            self.run_cmd(f"pactl load-module module-loopback source={ch}.monitor sink={phy_out} latency_msec=40 adjust_time=0 sink_input_properties=media.name=Link_User_{ch}")
            if self.streamer_mode:
                self.run_cmd(f"pactl load-module module-loopback source={ch}.monitor sink={STREAM_MIX_NAME} latency_msec=60 adjust_time=0 sink_input_properties=media.name=Link_Stream_{ch}")

        if phy_mic:
            self.run_cmd(f"pactl load-module module-loopback source={phy_mic} sink={INTERNAL_MIC_PROCESSING} latency_msec=40 adjust_time=0 sink_input_properties=media.name=Link_Mic_Chat")
            if self.streamer_mode:
                self.run_cmd(f"pactl load-module module-loopback source={phy_mic} sink={STREAM_MIX_NAME} latency_msec=40 adjust_time=0 sink_input_properties=media.name=Link_Mic_Stream")

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(7, 7, 7, 7)
        main_layout.setSpacing(14)

        top_bar = QFrame()
        top_bar.setFixedHeight(52)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addStretch()

        self.streamer_btn = QPushButton("STREAMER MODE")
        self.streamer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.streamer_btn.clicked.connect(self.toggle_streamer_mode)
        top_layout.addWidget(self.streamer_btn)

        setup_btn = QPushButton("INITIAL SETUP")
        setup_btn.setIcon(QIcon.fromTheme("preferences-system"))
        setup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        setup_btn.clicked.connect(self.open_setup_dialog)
        top_layout.addWidget(setup_btn)

        main_layout.addWidget(top_bar)

        mixer_row = QHBoxLayout()
        mixer_row.setSpacing(20)

        self.widgets = {}
        slider_height = 280
        streamer_slider_height = 220
        for name in self.channels.keys():
            w = AudioChannel(
                name,
                self.set_user_volume,
                self.set_stream_volume,
                self.toggle_user_mute,
                self.toggle_stream_mute,
                self.open_hk_dialog,
                self.move_app_to_sink,
                self,
                self.streamer_mode,
                slider_height,
                streamer_slider_height
            )
            self.widgets[name] = w
            mixer_row.addWidget(w)

        main_layout.addLayout(mixer_row)
        self.update_button_styles()

    def update_button_styles(self):
        if self.streamer_mode:
            self.streamer_btn.setStyleSheet(f"background: {THEME['Accent']}; color: #0B0C10; font-weight: 800; padding: 10px 18px; border-radius: 12px; border: none; font-size: 12px;")
        else:
            self.streamer_btn.setStyleSheet(f"background: {THEME['CardAlt']}; color: {THEME['Text']}; font-weight: 800; padding: 10px 18px; border-radius: 12px; border: none; font-size: 12px;")
        for btn in self.findChildren(QPushButton):
            if btn is self.streamer_btn:
                continue

        for btn in [b for b in self.findChildren(QPushButton) if b.text() == "INITIAL SETUP"]:
            btn.setStyleSheet(f"background: {THEME['CardAlt']}; color: {THEME['Text']}; font-weight: 800; padding: 10px 18px; border-radius: 12px; border: none; font-size: 12px;")

    def toggle_streamer_mode(self):
        self.streamer_mode = not self.streamer_mode
        for w in self.widgets.values():
            w.set_streamer_mode(self.streamer_mode)
        self.update_button_styles()
        self.handle_mode_toggle()
        self.register_hotkeys()

    def move_app_to_sink(self, app_id, target_name):
        if target_name in self.sinks:
            self.run_cmd(f"pactl move-sink-input {app_id} {target_name}")

    def _apply_user_volume(self, name, v):
        if name in self.sinks:
            self.run_cmd(f"pactl set-sink-volume {self.sinks[name]} {v}%")
            self.run_cmd(f"pactl set-sink-mute {self.sinks[name]} 0")
            return
        if name == "Mic" and self.selected_input:
            self.run_cmd(f"pactl set-source-volume {self.selected_input} {v}%")
            self.run_cmd(f"pactl set-source-mute {self.selected_input} 0")
            return
        input_id = self.get_input_id(name, self.user_input_key(name))
        if input_id:
            self.set_input_volume(input_id, v)

    def set_user_volume(self, name, val):
        self.channels[name].volume = int(val)
        v = int(val)
        self.user_volumes[name] = v
        self._apply_user_volume(name, v)
        self.schedule_save()

    def set_stream_volume(self, name, val):
        if not self.streamer_mode:
            return
        self.channels[name].stream_volume = int(val)
        self.stream_volumes[name] = int(val)
        input_id = self.get_input_id(name, "stream_input")
        if input_id:
            self.set_input_volume(input_id, int(val))
        self.schedule_save()

    def toggle_user_mute(self, name):
        input_id = self.get_input_id(name, self.user_input_key(name))
        if input_id:
            new_state = not self.channels[name].muted
            self.channels[name].muted = new_state
            widget = self.widgets.get(name)
            if widget:
                ch = self.channels[name]
                widget.update_state(ch.volume, ch.stream_volume, ch.muted, ch.stream_muted)
            threading.Thread(target=self.set_input_mute, args=(input_id, new_state), daemon=True).start()

    def toggle_stream_mute(self, name):
        if not self.streamer_mode:
            return
        input_id = self.get_input_id(name, "stream_input")
        if input_id:
            new_state = not self.channels[name].stream_muted
            self.channels[name].stream_muted = new_state
            widget = self.widgets.get(name)
            if widget:
                ch = self.channels[name]
                widget.update_state(ch.volume, ch.stream_volume, ch.muted, ch.stream_muted)
            threading.Thread(target=self.set_input_mute, args=(input_id, new_state), daemon=True).start()

    def apply_stream_defaults(self):
        if not self.streamer_mode:
            return
        for name, ch in self.channels.items():
            stream_id = self.get_input_id(name, "stream_input")
            if stream_id:
                target = self.stream_volumes.get(name)
                if target is None:
                    target = ch.volume
                    self.stream_volumes[name] = target
                ch.stream_volume = target
                self.set_input_volume(stream_id, target)
        self.schedule_save()
        for name, widget in self.widgets.items():
            ch = self.channels[name]
            widget.update_state(ch.volume, ch.stream_volume, ch.muted, ch.stream_muted)

    def dispatch_app_updates(self, data):
        if not self.is_dragging_app:
            for name, apps in data.items():
                if name in self.widgets:
                    self.widgets[name].update_apps_list(apps)

    def fetch_app_mapping(self):
        mapping = {"Game": [], "Chat": [], "Media": [], "Mic": []}
        sink_list = self.run_cmd("pactl list short sinks")
        sink_id_map = {}
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
            if 'media.name = "Link_' in block:
                continue
            input_id_match = re.search(r"^(\d+)", block.strip())
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

                    mapping[target_track].append((app_name, i_id, icon_name))
        return mapping

    def user_input_key(self, name):
        return "chat_input" if name == "Mic" else "user_input"

    def refresh_input_ids(self):
        active = {name: {} for name in self.channels}
        output = self.run_cmd("pactl list sink-inputs")
        for block in output.split("Sink Input #"):
            if not block.strip():
                continue
            id_match = re.search(r"^(\d+)", block.strip())
            name_match = re.search(r'media.name = "(.*?)"', block)
            if not id_match or not name_match:
                continue
            input_id = id_match.group(1)
            link_name = name_match.group(1)
            if not link_name.startswith("Link_"):
                continue
            parts = link_name.split("_")
            if len(parts) < 3:
                continue
            category = parts[1]
            target = parts[2]
            if category == "Mic":
                if target == "Chat":
                    active["Mic"]["chat_input"] = input_id
                elif target == "Stream":
                    active["Mic"]["stream_input"] = input_id
            else:
                if target not in active:
                    continue
                if category == "User":
                    active[target]["user_input"] = input_id
                elif category == "Stream":
                    active[target]["stream_input"] = input_id
        self.active_inputs = active

    def get_input_id(self, name, key):
        input_id = self.active_inputs.get(name, {}).get(key)
        if input_id is None:
            self.refresh_input_ids()
            input_id = self.active_inputs.get(name, {}).get(key)
        return input_id

    def get_input_volume(self, input_id):
        raw = self.run_cmd(f"pactl get-sink-input-volume {input_id}")
        match = re.search(r"(\d+)%", raw)
        if not match:
            return None
        return int(match.group(1))

    def get_sink_volume(self, sink_name):
        raw = self.run_cmd(f"pactl get-sink-volume {sink_name}")
        match = re.search(r"(\d+)%", raw)
        if not match:
            return None
        return int(match.group(1))

    def get_source_volume(self, source_name):
        raw = self.run_cmd(f"pactl get-source-volume {source_name}")
        match = re.search(r"(\d+)%", raw)
        if not match:
            return None
        return int(match.group(1))

    def get_input_mute(self, input_id):
        raw = self.run_cmd(f"pactl get-sink-input-mute {input_id}")
        if not raw:
            return None
        return "yes" in raw.lower()

    def set_input_volume(self, input_id, value):
        v = max(0, min(100, int(value)))
        self.run_cmd(f"pactl set-sink-input-volume {input_id} {v}%")
        self.run_cmd(f"pactl set-sink-input-mute {input_id} 0")

    def set_input_mute(self, input_id, muted):
        self.run_cmd(f"pactl set-sink-input-mute {input_id} {1 if muted else 0}")

    def sync_once(self):
        self.refresh_input_ids()
        changed = False
        for name, ch in self.channels.items():
            user_key = self.user_input_key(name)
            user_id = self.active_inputs.get(name, {}).get(user_key)
            stream_id = self.active_inputs.get(name, {}).get("stream_input")

            if name in self.sinks:
                v = self.get_sink_volume(self.sinks[name])
                if v is not None:
                    ch.volume = v
                    if self.user_volumes.get(name) != v:
                        self.user_volumes[name] = v
                        changed = True
            elif name == "Mic" and self.selected_input:
                v = self.get_source_volume(self.selected_input)
                if v is not None:
                    ch.volume = v
                    if self.user_volumes.get(name) != v:
                        self.user_volumes[name] = v
                        changed = True
            elif user_id:
                v = self.get_input_volume(user_id)
                if v is not None:
                    ch.volume = v
                    if self.user_volumes.get(name) != v:
                        self.user_volumes[name] = v
                        changed = True
                m = self.get_input_mute(user_id)
                if m is not None:
                    ch.muted = m

            if stream_id:
                sv = self.get_input_volume(stream_id)
                if sv is not None:
                    ch.stream_volume = sv
                    if self.stream_volumes.get(name) != sv:
                        self.stream_volumes[name] = sv
                        changed = True
                sm = self.get_input_mute(stream_id)
                if sm is not None:
                    ch.stream_muted = sm

        if not self.is_dragging_app:
            app_mapping = self.fetch_app_mapping()
            for name, ch in self.channels.items():
                ch.apps = app_mapping.get(name, [])

        for name, widget in self.widgets.items():
            ch = self.channels[name]
            widget.update_state(ch.volume, ch.stream_volume, ch.muted, ch.stream_muted)
            if not self.is_dragging_app:
                widget.update_apps_list(ch.apps)
        if changed:
            self.schedule_save()

    def start_hotkeys(self):
        while True:
            self.hotkey_reload_event.wait()
            self.hotkey_reload_event.clear()
            if self.hotkey_listener:
                try:
                    self.hotkey_listener.stop()
                except:
                    pass

            def on_press(ch, action):
                if action == "up":
                    next_v = max(0, min(100, self.channels[ch].volume + 5))
                    self.channels[ch].volume = next_v
                    self.set_user_volume(ch, next_v)
                elif action == "down":
                    next_v = max(0, min(100, self.channels[ch].volume - 5))
                    self.channels[ch].volume = next_v
                    self.set_user_volume(ch, next_v)
                elif action == "mute":
                    self.toggle_user_mute(ch)
                elif action == "stream_up":
                    next_v = max(0, min(100, self.channels[ch].stream_volume + 5))
                    self.channels[ch].stream_volume = next_v
                    self.set_stream_volume(ch, next_v)
                elif action == "stream_down":
                    next_v = max(0, min(100, self.channels[ch].stream_volume - 5))
                    self.channels[ch].stream_volume = next_v
                    self.set_stream_volume(ch, next_v)
                elif action == "stream_mute":
                    self.toggle_stream_mute(ch)

            hotkeys = {}
            for ch, acts in self.hotkeys_config.items():
                if ch not in self.channels:
                    continue
                for action, key in acts.items():
                    if action.startswith("stream_") and not self.streamer_mode:
                        continue
                    if key:
                        hotkeys[key] = lambda s=ch, a=action: on_press(s, a)

            if hotkeys:
                try:
                    self.hotkey_listener = keyboard.GlobalHotKeys(hotkeys)
                    self.hotkey_listener.start()
                except:
                    self.hotkey_listener = None

    def open_hk_dialog(self, ch):
        d = FixedDialog(self)
        d.setWindowTitle("Shortcuts")
        d.setFixedSize(540, 420)
        d.setStyleSheet(f"background: {THEME['Card']}; color: white; border-radius: 12px;")

        l = QVBoxLayout(d)
        l.setContentsMargins(12, 10, 12, 10)
        l.setSpacing(8)

        title = QLabel(f"HOTKEYS: {ch.upper()}")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 13px; font-weight: 700; color: #C8D0E0; margin: 0 0 8px 0;")
        l.addWidget(title)

        user_actions = [
            ("mute", "Mute", "audio-volume-muted"),
            ("down", "Volume Down", "go-down"),
            ("up", "Volume Up", "go-up")
        ]

        for act, label, icon_name in user_actions:
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
            text_lbl.setFixedWidth(150)
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
            clear_btn = QPushButton("Clear")
            clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            clear_btn.setFixedHeight(30)
            clear_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {THEME['CardAlt']};
                    color: {THEME['Text']};
                    border: 1px solid {THEME['Stroke']};
                    border-radius: 8px;
                    padding: 4px 10px;
                }}
                QPushButton:hover {{
                    background: #262B3B;
                    border: 1px solid {THEME['Accent']};
                }}
            """)
            row.addWidget(clear_btn)
            l.addWidget(row_wrap)
            e.hotkeyChanged.connect(lambda value, act=act: self.save_hk_value(ch, act, value))
            def clear_action(checked=False, edit=e, action=act):
                edit.setText("")
                self.save_hk_value(ch, action, "")
            clear_btn.clicked.connect(clear_action)

        if self.streamer_mode:
            spacer_top = QFrame()
            spacer_top.setFixedHeight(4)
            l.addWidget(spacer_top)
            divider = QFrame()
            divider.setFixedHeight(1)
            divider.setStyleSheet("background: #2A3040;")
            l.addWidget(divider)
            spacer_bottom = QFrame()
            spacer_bottom.setFixedHeight(4)
            l.addWidget(spacer_bottom)

            stream_actions = [
                ("stream_mute", "Stream Mute", "audio-volume-muted"),
                ("stream_down", "Stream Volume Down", "go-down"),
                ("stream_up", "Stream Volume Up", "go-up")
            ]
            for act, label, icon_name in stream_actions:
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
                text_lbl.setFixedWidth(150)
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
                clear_btn = QPushButton("Clear")
                clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                clear_btn.setFixedHeight(30)
                clear_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {THEME['CardAlt']};
                        color: {THEME['Text']};
                        border: 1px solid {THEME['Stroke']};
                        border-radius: 8px;
                        padding: 4px 10px;
                    }}
                    QPushButton:hover {{
                        background: #262B3B;
                        border: 1px solid {THEME['Accent']};
                    }}
                """)
                row.addWidget(clear_btn)
                l.addWidget(row_wrap)
                e.hotkeyChanged.connect(lambda value, act=act: self.save_hk_value(ch, act, value))
                def clear_action(checked=False, edit=e, action=act):
                    edit.setText("")
                    self.save_hk_value(ch, action, "")
                clear_btn.clicked.connect(clear_action)
        d.setFocus()
        d.exec()

    def save_hk_value(self, ch, act, value):
        self.hotkeys_config.setdefault(ch, {"up": "", "down": "", "mute": "", "stream_up": "", "stream_down": "", "stream_mute": ""})
        self.hotkeys_config[ch][act] = value
        self.save_config()
        self.register_hotkeys()

    def open_setup_dialog(self):
        hw_outputs = {}
        output = self.run_cmd("pactl list sinks")
        curr = ""
        for line in output.split('\n'):
            line = line.strip()
            if line.startswith("Name:"):
                curr = line.split(":", 1)[1].strip()
            elif line.startswith("Description:") and curr:
                desc = line.split(":", 1)[1].strip()
                is_virtual = curr in self.sinks.values() or STREAM_MIX_NAME in curr or INTERNAL_MIC_PROCESSING in curr or "Internal" in curr
                if not is_virtual:
                    hw_outputs[desc] = curr

        hw_inputs = {}
        sources = self.run_cmd("pactl list sources")
        curr_src = ""
        for line in sources.split('\n'):
            line = line.strip()
            if line.startswith("Name:"):
                curr_src = line.split(":", 1)[1].strip()
            elif line.startswith("Description:") and curr_src:
                desc = line.split(":", 1)[1].strip()
                is_virtual = MIC_INTERNAL_ID in curr_src or ".monitor" in curr_src
                if not is_virtual:
                    hw_inputs[desc] = curr_src

        d = FixedDialog(self)
        d.setWindowTitle("Audio Routing Setup")
        d.setFixedSize(420, 320)
        d.setStyleSheet(f"background: #0C0F16; color: white; border-radius: 18px;")

        l = QVBoxLayout(d)
        l.setContentsMargins(16, 16, 16, 16)
        l.setSpacing(8)

        desc = QLabel("Select your primary output device")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("font-size: 13px; font-weight: 600; color: #E9EEF7; margin-top: 8px; margin-bottom: 8px;")
        l.addWidget(desc)

        out_box = QFrame()
        out_layout = QVBoxLayout(out_box)
        out_layout.setContentsMargins(0, 0, 0, 0)
        out_layout.setSpacing(0)

        out_combo = SpacedComboBox()
        out_combo.addItems(list(hw_outputs.keys()))
        if self.selected_output:
            for i, (k, v) in enumerate(hw_outputs.items()):
                if v == self.selected_output:
                    out_combo.setCurrentIndex(i)
                    break
        out_combo.setStyleSheet("""
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
        out_layout.addWidget(out_combo)
        l.addWidget(out_box)

        in_desc = QLabel("Select your microphone input")
        in_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        in_desc.setStyleSheet("font-size: 13px; font-weight: 600; color: #E9EEF7; margin-top: 12px; margin-bottom: 8px;")
        l.addWidget(in_desc)

        in_box = QFrame()
        in_layout = QVBoxLayout(in_box)
        in_layout.setContentsMargins(0, 0, 0, 0)
        in_layout.setSpacing(0)

        in_combo = SpacedComboBox()
        in_combo.addItems(list(hw_inputs.keys()))
        if self.selected_input:
            for i, (k, v) in enumerate(hw_inputs.items()):
                if v == self.selected_input:
                    in_combo.setCurrentIndex(i)
                    break
        in_combo.setStyleSheet(out_combo.styleSheet())
        in_layout.addWidget(in_combo)
        l.addWidget(in_box)

        l.addStretch()

        b = QPushButton("APPLY")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet("background: #5EE7FF; color: #0B0C10; font-weight: bold; padding: 12px; border-radius: 12px; font-size: 12px;")
        b.clicked.connect(lambda: self.apply_setup(hw_outputs.get(out_combo.currentText(), ""), hw_inputs.get(in_combo.currentText(), ""), d))
        l.addWidget(b)
        d.exec()

    def apply_setup(self, output_id, input_id, dialog):
        self.selected_output = output_id or None
        self.selected_input = input_id or None
        self.save_config()
        self.initial_setup()
        dialog.close()

    def register_hotkeys(self):
        self.hotkey_reload_event.set()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    win = MuxHome()
    if "--minimized" in sys.argv:
        win.hide_to_tray()
    else:
        win.show()
    sys.exit(app.exec())
