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
    QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QMimeData, QSize
from PyQt6.QtGui import QDrag, QIcon, QPixmap
from pynput import keyboard

# Configuration path
CONFIG_FILE = os.path.expanduser("~/.sonar_config.json")

THEME = {
    "Bg": "#0b0e12", "Card": "#13171e", "Accent": "#00ffcc",
    "Game": "#00ffcc", "Chat": "#4d94ff", "Media": "#ff4d88",
    "Text": "#ffffff", "DimText": "#5c6672", "Border": "#21262e"
}

class AudioDataSignaler(QObject):
    update_apps = pyqtSignal(dict)

class DraggableAppLabel(QFrame):
    """عنصر تطبيق قابل للسحب مع أيقونة"""
    def __init__(self, name, app_id, icon_name, parent_app):
        super().__init__()
        self.app_id = app_id
        self.app_name = name
        self.parent_app = parent_app
        self.setStyleSheet("background: transparent; border: none;")
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(8)

        # جلب الأيقونة من النظام
        icon_label = QLabel()
        icon = QIcon.fromTheme(icon_name)
        if icon.isNull():
            icon = QIcon.fromTheme("audio-card")
        
        pixmap = icon.pixmap(QSize(18, 18))
        icon_label.setPixmap(pixmap)
        layout.addWidget(icon_label)

        text_label = QLabel(name[:15])
        text_label.setStyleSheet(f"color: {THEME['Text']}; font-size: 11px; font-weight: bold;")
        layout.addWidget(text_label)
        layout.addStretch()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.parent_app.is_dragging_app = True
            drag = QDrag(self)
            mime_data = QMimeData()
            mime_data.setText(str(self.app_id))
            drag.setMimeData(mime_data)
            drag.exec(Qt.DropAction.MoveAction)
            self.parent_app.is_dragging_app = False

class AudioChannel(QFrame):
    def __init__(self, name, vol_cb, mute_cb, hk_cb, move_app_cb, parent_app):
        super().__init__()
        self.name = name
        self.parent_app = parent_app
        self.move_app_cb = move_app_cb
        self.color = THEME.get(name, "white")
        self.setFixedWidth(200)
        self.setAcceptDrops(True)
        self.setStyleSheet(f"QFrame {{ background: {THEME['Card']}; border-radius: 8px; border: 1px solid {THEME['Border']}; }}")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 20, 15, 20)

        header = QHBoxLayout()
        name_lbl = QLabel(name.upper())
        name_lbl.setStyleSheet(f"color: {self.color}; font-weight: 900; font-size: 17px; border: none;")
        header.addWidget(name_lbl)
        
        gear_btn = QPushButton("⚙")
        gear_btn.setFixedSize(30, 30)
        gear_btn.setStyleSheet("color: #444; font-size: 22px; background: transparent; border: none;")
        gear_btn.clicked.connect(lambda: hk_cb(self.name))
        header.addWidget(gear_btn)
        layout.addLayout(header)

        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setRange(0, 100)
        self.slider.setMinimumHeight(350)
        self.slider.setFixedWidth(50)
        self.slider.setStyleSheet(f"""
            QSlider::groove:vertical {{ background: #1c222d; width: 12px; border-radius: 6px; }}
            QSlider::handle:vertical {{ background: white; height: 24px; width: 24px; margin: 0 -6px; border-radius: 12px; }}
            QSlider::add-page:vertical {{ background: {self.color}; width: 12px; border-radius: 6px; }}
        """)
        self.slider.valueChanged.connect(lambda v: vol_cb(self.name, v))
        layout.addWidget(self.slider, alignment=Qt.AlignmentFlag.AlignCenter)

        self.mute_btn = QPushButton("🔊")
        self.mute_btn.setFixedSize(55, 55)
        self.mute_btn.clicked.connect(lambda: mute_cb(self.name))
        layout.addWidget(self.mute_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.app_frame = QFrame()
        self.app_frame.setMinimumHeight(140)
        self.app_frame.setStyleSheet(f"background: #0b0e12; border: 1px solid #1c222d; border-radius: 4px;")
        self.app_layout = QVBoxLayout(self.app_frame)
        self.app_layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.app_frame)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.accept()
            self.setStyleSheet(f"QFrame {{ background: {THEME['Card']}; border: 2px solid {self.color}; border-radius: 8px; }}")

    def dragLeaveEvent(self, event):
        self.setStyleSheet(f"QFrame {{ background: {THEME['Card']}; border: 1px solid {THEME['Border']}; border-radius: 8px; }}")

    def dropEvent(self, event):
        app_id = event.mimeData().text()
        self.move_app_cb(app_id, self.name)
        self.setStyleSheet(f"QFrame {{ background: {THEME['Card']}; border: 1px solid {THEME['Border']}; border-radius: 8px; }}")
        event.accept()

    def update_apps_list(self, apps_info):
        while self.app_layout.count():
            item = self.app_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        
        if not apps_info:
            lbl = QLabel("No active apps")
            lbl.setStyleSheet("color: #333; font-size: 10px; border: none;")
            self.app_layout.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        else:
            for app_name, app_id, icon_name in apps_info:
                app_widget = DraggableAppLabel(app_name, app_id, icon_name, self.parent_app)
                self.app_layout.addWidget(app_widget)
        self.app_layout.addStretch()

class SonarPro(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Linux Sonar GG - Ultimate")
        self.setFixedSize(800, 900)
        self.setStyleSheet(f"background-color: {THEME['Bg']};")
        
        self.is_dragging_app = False
        self.sinks = {"Game": "Game", "Chat": "Chat", "Media": "Media"}
        self.hotkeys_config = self.load_config()
        self.widgets = {}
        
        self.signaler = AudioDataSignaler()
        self.signaler.update_apps.connect(self.dispatch_app_updates)

        self.setup_ui()
        self.init_audio_engine()

        threading.Thread(target=self.sync_loop, daemon=True).start()
        threading.Thread(target=self.start_hotkeys, daemon=True).start()

    def run_cmd(self, cmd):
        try: return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
        except: return ""

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f: return json.load(f)
            except: pass
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
        main_layout.setContentsMargins(30, 30, 30, 30)
        
        top = QHBoxLayout()
        header = QLabel("SONAR MIXER")
        header.setStyleSheet("color: white; font-size: 28px; font-weight: 900; border: none;")
        top.addWidget(header)
        top.addStretch()
        
        setup_btn = QPushButton("⚙ INITIAL SETUP")
        setup_btn.setStyleSheet(f"background: {THEME['Accent']}; color: #000; font-weight: bold; padding: 12px 25px; border-radius: 4px;")
        setup_btn.clicked.connect(self.open_setup_dialog)
        top.addWidget(setup_btn)
        main_layout.addLayout(top)

        mixer_row = QHBoxLayout()
        mixer_row.setSpacing(20)
        for name in self.sinks.keys():
            w = AudioChannel(name, self.set_vol, self.do_mute, self.open_hk_dialog, self.move_app_to_sink, self)
            self.widgets[name] = w
            mixer_row.addWidget(w)
        main_layout.addLayout(mixer_row)

    def move_app_to_sink(self, app_id, target_name):
        self.run_cmd(f"pactl move-sink-input {app_id} {target_name}")

    def set_vol(self, name, val): self.run_cmd(f"pactl set-sink-volume {name} {int(val)}%")
    def do_mute(self, name): self.run_cmd(f"pactl set-sink-mute {name} toggle")

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
                        m = "yes" in mute_raw.lower()
                        w = self.widgets[name]
                        if not w.slider.isSliderDown():
                            w.slider.blockSignals(True)
                            w.slider.setValue(v)
                            w.slider.blockSignals(False)
                        
                        btn_color = "#ff4444" if m else "white"
                        w.mute_btn.setText("🔇" if m else "🔊")
                        w.mute_btn.setStyleSheet(f"background: #1c222d; color: {btn_color}; border-radius: 27px; border: 1px solid #2a313d; font-size: 22px;")
                    except: pass

            if not self.is_dragging_app:
                app_mapping = {"Game": [], "Chat": [], "Media": []}
                sink_id_map = {}
                sink_list = self.run_cmd("pactl list short sinks")
                for line in sink_list.split('\n'):
                    parts = line.split('\t')
                    if len(parts) > 1:
                        for s_name in self.sinks:
                            if s_name in parts[1]: sink_id_map[parts[0]] = s_name

                inputs_raw = self.run_cmd("pactl list sink-inputs")
                blocks = inputs_raw.split("Sink Input #")
                for block in blocks:
                    if not block.strip(): continue
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
                            if name_match: app_name = name_match.group(1)
                            icon_match = re.search(r'application.icon_name = "(.*?)"', block)
                            if icon_match: icon_name = icon_match.group(1)
                            elif "brave" in app_name.lower(): icon_name = "brave-browser"
                            elif "discord" in app_name.lower(): icon_name = "discord"
                            app_mapping[target_track].append((app_name, i_id, icon_name))
                self.signaler.update_apps.emit(app_mapping)
            time.sleep(1)

    def start_hotkeys(self):
        def on_press(sink, action):
            if action == "up": self.run_cmd(f"pactl set-sink-volume {sink} +5%")
            elif action == "down": self.run_cmd(f"pactl set-sink-volume {sink} -5%")
            elif action == "mute": self.do_mute(sink)
        while True:
            hotkeys = {key: (lambda s=sn, a=act: on_press(s, a)) for sn, acts in self.hotkeys_config.items() for act, key in acts.items() if key}
            if hotkeys:
                try:
                    with keyboard.GlobalHotKeys(hotkeys) as h: h.join()
                except: pass
            time.sleep(1)

    def open_hk_dialog(self, ch):
        d = QDialog(self); d.setFixedSize(300, 300); d.setStyleSheet(f"background: {THEME['Card']}; color: white;")
        l = QVBoxLayout(d); l.addWidget(QLabel(f"HOTKEYS: {ch.upper()}"))
        entries = {}
        for act in ["up", "down", "mute"]:
            l.addWidget(QLabel(f"{act}:"))
            e = QLineEdit(); e.setText(self.hotkeys_config[ch][act]); e.setStyleSheet("background: #1c222d; padding: 8px;")
            l.addWidget(e); entries[act] = e
        btn = QPushButton("SAVE"); btn.clicked.connect(lambda: [self.save_hk(ch, {k: v.text() for k, v in entries.items()}), d.close()])
        l.addWidget(btn); d.exec()

    def save_hk(self, ch, data):
        self.hotkeys_config[ch] = data
        with open(CONFIG_FILE, 'w') as f: json.dump(self.hotkeys_config, f)

    def open_setup_dialog(self):
        hw_info = {}; output = self.run_cmd("pactl list sinks"); curr = ""
        for line in output.split('\n'):
            line = line.strip()
            if line.startswith("Name:"): curr = line.split(":", 1)[1].strip()
            elif line.startswith("Description:") and curr:
                desc = line.split(":", 1)[1].strip()
                if curr not in self.sinks.values(): hw_info[desc] = curr
        d = QDialog(self); d.setFixedSize(400, 220); d.setStyleSheet(f"background: {THEME['Card']}; color: white;")
        l = QVBoxLayout(d); l.addWidget(QLabel("PRIMARY OUTPUT DEVICE:"))
        c = QComboBox(); c.addItems(list(hw_info.keys())); c.setStyleSheet("background: #1c222d; padding: 10px; color: white;"); l.addWidget(c)
        b = QPushButton("CONFIRM"); b.clicked.connect(lambda: [self.apply_full_route(hw_info[c.currentText()]), d.close()])
        l.addWidget(b); d.exec()

    def apply_full_route(self, sink_id):
        for v in self.sinks.values():
            self.run_cmd(f"pw-link {v}:monitor_FL {sink_id}:playback_FL")
            self.run_cmd(f"pw-link {v}:monitor_FR {sink_id}:playback_FR")
        self.run_cmd("pactl set-default-sink Game")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = SonarPro()
    win.show()
    sys.exit(app.exec())
