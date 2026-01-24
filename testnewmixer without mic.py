import tkinter as tk
from tkinter import ttk
import subprocess
import json
import os
import re
import time
import threading

# --- Config ---
CONFIG_FILE = os.path.expanduser("~/.sonar_proto.json")
THEME = {
    "Bg": "#0F1117", "Card": "#171A23", "Accent": "#5EE7FF",
    "Text": "#E9EEF7", "Game": "#5EE7FF", "Chat": "#B693FF", "Media": "#FF6B6B"
}
SINKS = ["Game", "Chat", "Media"]
STREAM_SINK_NAME = "StreamOutput"

class SonarProtoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SONAR - SILENT STARTUP")
        self.root.geometry("850x650")
        self.root.configure(bg=THEME["Bg"])
        
        self.active_inputs = {k: {} for k in SINKS}
        
        self.config = self.load_config()
        self.is_streamer_mode = tk.BooleanVar(value=self.config.get("streamer_mode", False))
        
        # 1. تهيئة المصادر الأساسية
        self.init_base_sinks()
        
        # 2. تنظيف أولي
        self.startup_cleanup()
        
        # 3. واجهة المستخدم
        self.setup_ui()
        
        # 4. التشغيل الأولي (داخل Thread لمنع تعليق الواجهة)
        # التعديل هنا: نستخدم initial_setup التي تحتوي على الكتم
        self.root.after(500, lambda: threading.Thread(target=self.initial_setup, daemon=True).start())

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f: return json.load(f)
            except: pass
        return {"selected_output": None, "streamer_mode": False}

    def save_config(self):
        self.config["streamer_mode"] = self.is_streamer_mode.get()
        with open(CONFIG_FILE, 'w') as f: json.dump(self.config, f)

    def run_cmd(self, cmd):
        try:
            return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
        except: return ""

    def init_base_sinks(self):
        existing = self.run_cmd("pactl list short sinks")
        for name in SINKS:
            if name not in existing:
                self.run_cmd(f"pactl load-module module-null-sink sink_name={name} sink_properties=device.description={name}_Audio")
            self.run_cmd(f"pactl set-sink-volume {name} 100%")
            self.run_cmd(f"pactl set-sink-mute {name} 0")

    def startup_cleanup(self):
        print("Startup Cleanup...")
        try:
            output = self.run_cmd("pactl list sink-inputs")
            for block in output.split("Sink Input #"):
                if 'media.name = "Sonar_' in block:
                    match = re.search(r"Owner Module: (\d+)", block)
                    if match: self.run_cmd(f"pactl unload-module {match.group(1)}")
        except: pass
        
        mods = self.run_cmd("pactl list short modules")
        for line in mods.split('\n'):
            if f"sink_name={STREAM_SINK_NAME}" in line:
                self.run_cmd(f"pactl unload-module {line.split()[0]}")

    def setup_ui(self):
        header = tk.Frame(self.root, bg=THEME["Bg"])
        header.pack(fill="x", padx=30, pady=30)
        
        tk.Label(header, text="SONAR FINAL", font=("Segoe UI", 24, "bold"), bg=THEME["Bg"], fg="white").pack(side="left")
        
        tk.Button(header, text="SETUP ⚙️", bg=THEME["Accent"], command=self.open_setup_dialog).pack(side="right", padx=10)
        
        tk.Checkbutton(header, text="STREAMER MODE", variable=self.is_streamer_mode,
                       bg=THEME["Bg"], fg="white", selectcolor=THEME["Card"], font=("bold"),
                       command=self.handle_mode_toggle).pack(side="right", padx=20)

        self.mixer_frame = tk.Frame(self.root, bg=THEME["Bg"])
        self.mixer_frame.pack(expand=True, fill="both", padx=30, pady=10)

    # -------------------------------------------------------------------------
    # Core Logic
    # -------------------------------------------------------------------------

    def initial_setup(self):
        """
        يتم تشغيله عند بدء البرنامج.
        التعديل: كتم الهاردوير -> بناء -> إعادة الصوت
        """
        phy = self.config.get("selected_output")
        
        # 1. كتم الهاردوير (لمنع صوت الكهرباء في البداية)
        if phy: 
            print("Muting Hardware for Startup...")
            self.run_cmd(f"pactl set-sink-mute {phy} 1")

        # 2. البناء
        self.rebuild_user_routing()
        if self.is_streamer_mode.get():
            self.add_stream_routing()
        
        # 3. تحديث الواجهة
        self.refresh_ui()

        # 4. إعادة الصوت (بعد استقرار الاتصال)
        if phy:
            time.sleep(0.5) # وقت كافي لاستقرار الموديولز
            print("Unmuting Hardware...")
            self.run_cmd(f"pactl set-sink-mute {phy} 0")

    def handle_mode_toggle(self):
        self.save_config()
        threading.Thread(target=self._toggle_process, daemon=True).start()

    def _toggle_process(self):
        phy = self.config.get("selected_output")
        
        # 1. كتم الهاردوير أثناء التبديل
        if phy: self.run_cmd(f"pactl set-sink-mute {phy} 1")
        
        # 2. التعديل
        if self.is_streamer_mode.get():
            self.add_stream_routing()
        else:
            self.remove_stream_routing()
            
        # 3. تحديث
        self.refresh_input_ids()
        self.root.after(0, self.render_mixer)
        
        # 4. إعادة الصوت
        if phy:
            time.sleep(0.3)
            self.run_cmd(f"pactl set-sink-mute {phy} 0")

    def rebuild_user_routing(self):
        phy = self.config.get("selected_output")
        if not phy: return
        
        self.remove_routing_by_prefix("Sonar_User_")
        
        print("Building User Routing...")
        for ch in SINKS:
            loop_name = f"Sonar_User_{ch}"
            # latency 40ms
            cmd = f"pactl load-module module-loopback source={ch}.monitor sink={phy} latency_msec=40 adjust_time=0 sink_input_properties=media.name={loop_name}"
            self.run_cmd(cmd)

    def add_stream_routing(self):
        print("Adding Stream Routing...")
        mods = self.run_cmd("pactl list short modules")
        if f"sink_name={STREAM_SINK_NAME}" not in mods:
            self.run_cmd(f"pactl load-module module-null-sink sink_name={STREAM_SINK_NAME} sink_properties=device.description=SONAR_STREAM_MIX")
            self.run_cmd(f"pactl set-sink-volume {STREAM_SINK_NAME} 100%")
            self.run_cmd(f"pactl set-sink-mute {STREAM_SINK_NAME} 0")

        for ch in SINKS:
            loop_name = f"Sonar_Stream_{ch}"
            if not self.check_loopback_exists(loop_name):
                # latency 60ms للبث
                cmd = f"pactl load-module module-loopback source={ch}.monitor sink={STREAM_SINK_NAME} latency_msec=60 adjust_time=0 sink_input_properties=media.name={loop_name}"
                self.run_cmd(cmd)

    def remove_stream_routing(self):
        print("Removing Stream Routing...")
        self.remove_routing_by_prefix("Sonar_Stream_")
        mods = self.run_cmd("pactl list short modules")
        for line in mods.split('\n'):
            if f"sink_name={STREAM_SINK_NAME}" in line:
                self.run_cmd(f"pactl unload-module {line.split()[0]}")

    def remove_routing_by_prefix(self, prefix):
        try:
            output = self.run_cmd("pactl list sink-inputs")
            for block in output.split("Sink Input #"):
                if f'media.name = "{prefix}' in block:
                    match = re.search(r"Owner Module: (\d+)", block)
                    if match: self.run_cmd(f"pactl unload-module {match.group(1)}")
        except: pass

    def check_loopback_exists(self, name):
        output = self.run_cmd("pactl list sink-inputs")
        return f'media.name = "{name}"' in output

    def refresh_ui(self):
        self.refresh_input_ids()
        self.root.after(0, self.render_mixer)

    def refresh_input_ids(self):
        self.active_inputs = {k: {} for k in SINKS}
        try:
            output = self.run_cmd("pactl list sink-inputs")
            current_id = None
            for line in output.split('\n'):
                line = line.strip()
                if line.startswith("Sink Input #"):
                    current_id = line.split("#")[1]
                elif 'media.name = "' in line and current_id:
                    match = re.search(r'media.name = "(.*?)"', line)
                    if match:
                        name = match.group(1)
                        if name.startswith("Sonar_"):
                            parts = name.split("_")
                            if len(parts) >= 3:
                                type_k = parts[1].lower()
                                ch = parts[2]
                                if ch in self.active_inputs:
                                    self.active_inputs[ch][f"{type_k}_input"] = current_id
        except: pass

    def set_volume(self, channel, val, target_type):
        input_id = self.active_inputs.get(channel, {}).get(f"{target_type}_input")
        if input_id:
            self.run_cmd(f"pactl set-sink-input-volume {input_id} {int(val)}%")
            self.run_cmd(f"pactl set-sink-input-mute {input_id} 0")
        else:
            self.refresh_input_ids()

    def render_mixer(self):
        for widget in self.mixer_frame.winfo_children(): widget.destroy()
        mode = self.is_streamer_mode.get()

        for name in SINKS:
            color = THEME.get(name, "white")
            card = tk.Frame(self.mixer_frame, bg=THEME["Card"])
            card.pack(side="left", expand=True, fill="both", padx=10)
            
            tk.Label(card, text=name.upper(), font=("Segoe UI", 16, "bold"), bg=THEME["Card"], fg=color).pack(pady=20)
            controls = tk.Frame(card, bg=THEME["Card"])
            controls.pack(expand=True, fill="both", padx=10)

            self.create_slider(controls, name, "YOU" if mode else "VOL", color, 0, 100, "user", side="left" if mode else "top")

            if mode:
                ttk.Separator(controls, orient="vertical").pack(side="left", fill="y", padx=10, pady=30)
                self.create_slider(controls, name, "STREAM", "#FFFFFF", 0, 100, "stream", side="right")

    def create_slider(self, parent, channel, label, color, min_v, max_v, target_type, side="top"):
        f = tk.Frame(parent, bg=THEME["Card"])
        f.pack(side=side, expand=True, fill="both", padx=5)
        tk.Label(f, text=label, font=("bold"), bg=THEME["Card"], fg="gray").pack(pady=5)
        
        cmd = lambda v: self.set_volume(channel, v, target_type)
        s = tk.Scale(f, from_=max_v, to=min_v, orient="vertical", bg=THEME["Card"], fg="white", 
                     troughcolor="#1F232F", activebackground=color, highlightthickness=0, bd=0, 
                     command=cmd)
        
        default_val = 80 if target_type == "stream" else 50
        s.set(default_val)
        s.pack(expand=True, fill="y", pady=5)
        threading.Thread(target=lambda: self.set_volume(channel, default_val, target_type)).start()

    def open_setup_dialog(self):
        output = self.run_cmd("pactl list short sinks")
        hw_sinks = {}
        for line in output.split('\n'):
            parts = line.split('\t')
            if len(parts) > 1 and "Sonar" not in parts[1] and "Stream" not in parts[1]:
                 hw_sinks[parts[1]] = parts[1]

        d = tk.Toplevel(self.root)
        d.title("Setup")
        d.configure(bg=THEME["Card"])
        
        tk.Label(d, text="Select Headphones:", bg=THEME["Card"], fg="white").pack(pady=10)
        c = ttk.Combobox(d, values=list(hw_sinks.keys()), state="readonly")
        c.pack(pady=5, padx=20)
        if self.config["selected_output"]: c.set(self.config["selected_output"])

        def apply():
            if c.get():
                self.config["selected_output"] = c.get()
                self.save_config()
                # عند تغيير السماعة، نعيد البناء مع كتم الصوت
                threading.Thread(target=self.initial_setup, daemon=True).start()
                d.destroy()
        
        tk.Button(d, text="APPLY", bg=THEME["Accent"], command=apply).pack(pady=15)

if __name__ == "__main__":
    root = tk.Tk()
    app = SonarProtoApp(root)
    root.mainloop()
