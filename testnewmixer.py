import tkinter as tk
from tkinter import ttk
import subprocess
import json
import os
import re
import time
import threading

# --- Config ---
CONFIG_FILE = os.path.expanduser("~/.sonar_v13_fixed.json")
THEME = {
    "Bg": "#0F1117", "Card": "#171A23", "Accent": "#5EE7FF",
    "Text": "#E9EEF7", "Game": "#5EE7FF", "Chat": "#B693FF", "Media": "#FF6B6B",
    "Mic": "#FFD700"
}

# أسماء المسارات (نظيفة)
AUDIO_SINKS = ["Game", "Chat", "Media"]
STREAM_MIX_NAME = "Stream_Mix" 

# اسم المايك الجديد
MIC_DISPLAY_NAME = "Sonar Mic"     # الاسم الذي يظهر في الديسكورد
MIC_INTERNAL_ID = "Sonar_Mic"      # المعرف البرمجي

class SonarFinalFixedApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SONAR - FINAL FIX V13")
        self.root.geometry("1100x700")
        self.root.configure(bg=THEME["Bg"])
        
        # تخزين معرفات التحكم
        self.active_inputs = {k: {} for k in AUDIO_SINKS + ["Mic"]}
        
        self.config = self.load_config()
        self.is_streamer_mode = tk.BooleanVar(value=self.config.get("streamer_mode", False))
        
        # 1. تهيئة
        self.init_infrastructure()
        # 2. تنظيف
        self.startup_cleanup()
        # 3. واجهة
        self.setup_ui()
        # 4. تشغيل
        self.root.after(500, lambda: threading.Thread(target=self.initial_setup, daemon=True).start())

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {"selected_output": None, "selected_input": None, "streamer_mode": False}

    def save_config(self):
        self.config["streamer_mode"] = self.is_streamer_mode.get()
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f)

    def run_cmd(self, cmd):
        try:
            return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
        except:
            return ""

    # =========================================================
    #  البنية التحتية
    # =========================================================
    def create_device(self, name, desc, is_source=False):
        """إنشاء جهاز وتسميته بشكل صحيح"""
        # الخصائص التي تجبر النظام على عرض الاسم الذي نريده
        props = (f"device.description='{desc}' "
                 f"node.nick='{desc}' "
                 f"media.name='{desc}' "
                 f"device.product.name='{desc}'")
        
        if is_source:
            # للمايك
            props += " device.icon_name='audio-input-microphone'"
            # نحتاج غرفة خلفية أولاً
            internal = "Internal_Mic_Processing"
            self.run_cmd(f"pactl load-module module-null-sink sink_name={internal} sink_properties=device.description='INTERNAL'")
            time.sleep(0.1)
            # ثم المايك
            cmd = f"pactl load-module module-remap-source master={internal}.monitor source_name={name} source_properties=\"{props}\""
        else:
            # للسماعات
            cmd = f"pactl load-module module-null-sink sink_name={name} sink_properties=\"{props}\""
            
        self.run_cmd(cmd)
        
        # تأكد من الصوت
        if not is_source:
            self.run_cmd(f"pactl set-sink-volume {name} 100%")
            self.run_cmd(f"pactl set-sink-mute {name} 0")

    def init_infrastructure(self):
        print("Initializing Infrastructure...")
        existing_sinks = self.run_cmd("pactl list short sinks")
        existing_sources = self.run_cmd("pactl list short sources")
        
        # 1. القنوات (Game, Chat, Media)
        for name in AUDIO_SINKS:
            # تحقق بسيط لتجنب التكرار
            if f"{name}\t" not in existing_sinks:
                self.create_device(name, name) # الاسم والوصف متطابقان

        # 2. المايك (Sonar Mic)
        if MIC_INTERNAL_ID not in existing_sources:
            self.create_device(MIC_INTERNAL_ID, MIC_DISPLAY_NAME, is_source=True)

    def startup_cleanup(self):
        print("Cleaning up old connections...")
        try:
            output = self.run_cmd("pactl list sink-inputs")
            # نحذف أي كابل يبدأ اسمه بـ Link_
            for block in output.split("Sink Input #"):
                if 'media.name = "Link_' in block:
                    match = re.search(r"Owner Module: (\d+)", block)
                    if match:
                        self.run_cmd(f"pactl unload-module {match.group(1)}")
        except:
            pass
        
        # تنظيف الستريمر مكس
        mods = self.run_cmd("pactl list short modules")
        for line in mods.split('\n'):
            if f"sink_name={STREAM_MIX_NAME}" in line:
                self.run_cmd(f"pactl unload-module {line.split()[0]}")

    def setup_ui(self):
        header = tk.Frame(self.root, bg=THEME["Bg"])
        header.pack(fill="x", padx=30, pady=30)
        
        tk.Label(header, text="SONAR FIXED", font=("Segoe UI", 24, "bold"), bg=THEME["Bg"], fg="white").pack(side="left")
        
        tk.Button(header, text="SETUP ⚙️", bg=THEME["Accent"], command=self.open_setup_dialog).pack(side="right", padx=10)
        
        tk.Checkbutton(header, text="STREAMER MODE", variable=self.is_streamer_mode,
                       bg=THEME["Bg"], fg="white", selectcolor=THEME["Card"], font=("bold"),
                       command=self.handle_mode_toggle).pack(side="right", padx=20)

        self.mixer_frame = tk.Frame(self.root, bg=THEME["Bg"])
        self.mixer_frame.pack(expand=True, fill="both", padx=30, pady=10)

    # --- Defaults ---
    def set_system_defaults(self):
        # Game و Sonar Mic
        self.run_cmd("pactl set-default-sink Game")
        self.run_cmd(f"pactl set-default-source {MIC_INTERNAL_ID}")

    # --- Logic ---
    def initial_setup(self):
        phy_out = self.config.get("selected_output")
        if phy_out: self.run_cmd(f"pactl set-sink-mute {phy_out} 1")

        self.rebuild_routing()
        self.set_system_defaults()
        self.refresh_ui()

        if phy_out:
            time.sleep(0.5)
            self.run_cmd(f"pactl set-sink-mute {phy_out} 0")

    def handle_mode_toggle(self):
        self.save_config()
        threading.Thread(target=self._toggle_process, daemon=True).start()

    def _toggle_process(self):
        phy_out = self.config.get("selected_output")
        if phy_out: self.run_cmd(f"pactl set-sink-mute {phy_out} 1")
        
        self.rebuild_routing()
        self.set_system_defaults()
        self.refresh_ui()
        
        if phy_out:
            time.sleep(0.3)
            self.run_cmd(f"pactl set-sink-mute {phy_out} 0")

    def rebuild_routing(self):
        phy_out = self.config.get("selected_output")
        phy_mic = self.config.get("selected_input")
        mode = self.is_streamer_mode.get()

        # تنظيف الكابلات فقط (التي تبدأ بـ Link_)
        self.remove_links()

        if not phy_out: return

        # 1. Stream Mix
        if mode:
            mods = self.run_cmd("pactl list short modules")
            if f"sink_name={STREAM_MIX_NAME}" not in mods:
                # إنشاء "Stream Mix"
                self.create_device(STREAM_MIX_NAME, "Stream Mix")
        else:
            mods = self.run_cmd("pactl list short modules")
            for line in mods.split('\n'):
                if f"sink_name={STREAM_MIX_NAME}" in line:
                    self.run_cmd(f"pactl unload-module {line.split()[0]}")

        # 2. Audio Routing (Connecting Sinks)
        for ch in AUDIO_SINKS:
            # هنا التسمية الدقيقة للكابلات: Link_User_Game
            # هذا الاسم هو ما سيبحث عنه السلايدر
            
            # User Link
            cmd = f"pactl load-module module-loopback source={ch}.monitor sink={phy_out} latency_msec=40 adjust_time=0 sink_input_properties=media.name=Link_User_{ch}"
            self.run_cmd(cmd)

            # Stream Link
            if mode:
                cmd = f"pactl load-module module-loopback source={ch}.monitor sink={STREAM_MIX_NAME} latency_msec=60 adjust_time=0 sink_input_properties=media.name=Link_Stream_{ch}"
                self.run_cmd(cmd)

        # 3. Mic Routing
        if phy_mic:
            # To Sonar Mic (Virtual)
            internal_mic = "Internal_Mic_Processing"
            cmd = f"pactl load-module module-loopback source={phy_mic} sink={internal_mic} latency_msec=40 adjust_time=0 sink_input_properties=media.name=Link_Mic_Chat"
            self.run_cmd(cmd)

            # To Stream Mix (Inject)
            if mode:
                cmd = f"pactl load-module module-loopback source={phy_mic} sink={STREAM_MIX_NAME} latency_msec=40 adjust_time=0 sink_input_properties=media.name=Link_Mic_Stream"
                self.run_cmd(cmd)

    def remove_links(self):
        try:
            output = self.run_cmd("pactl list sink-inputs")
            for block in output.split("Sink Input #"):
                # حذف أي كابل يبدأ بـ Link_
                if 'media.name = "Link_' in block:
                    match = re.search(r"Owner Module: (\d+)", block)
                    if match:
                        self.run_cmd(f"pactl unload-module {match.group(1)}")
        except:
            pass

    # --- UI & Volume (Fixed Logic) ---
    def refresh_ui(self):
        self.refresh_input_ids()
        self.root.after(0, self.render_mixer)

    def refresh_input_ids(self):
        # إعادة تعيين الذاكرة
        self.active_inputs = {k: {} for k in AUDIO_SINKS + ["Mic"]}
        try:
            output = self.run_cmd("pactl list sink-inputs")
            current_id = None
            for line in output.split('\n'):
                line = line.strip()
                if line.startswith("Sink Input #"):
                    current_id = line.split("#")[1]
                elif 'media.name = "' in line and current_id:
                    # استخراج الاسم: Link_User_Game أو Link_Mic_Chat
                    match = re.search(r'media.name = "(.*?)"', line)
                    if match:
                        name = match.group(1)
                        if name.startswith("Link_"):
                            parts = name.split("_")
                            # Link_User_Game -> parts[1]=User, parts[2]=Game
                            if len(parts) >= 3:
                                category = parts[1] # User, Stream, Mic
                                target = parts[2]   # Game, Chat...
                                
                                if category == "Mic":
                                    # Link_Mic_Chat -> Mic Slider (Chat/Apps)
                                    if target == "Chat":
                                        self.active_inputs["Mic"]["chat_input"] = current_id
                                    # Link_Mic_Stream -> Mic Slider (Stream)
                                    elif target == "Stream":
                                        self.active_inputs["Mic"]["stream_input"] = current_id
                                else:
                                    # Link_User_Game -> Game Slider (User)
                                    if target in self.active_inputs:
                                        self.active_inputs[target][f"{category.lower()}_input"] = current_id
        except:
            pass

    def set_volume(self, key, sub_key, val):
        input_id = self.active_inputs.get(key, {}).get(sub_key)
        if input_id:
            self.run_cmd(f"pactl set-sink-input-volume {input_id} {int(val)}%")
            self.run_cmd(f"pactl set-sink-input-mute {input_id} 0")
        else:
            # إذا لم نجد الـ ID، نحاول تحديث القائمة
            self.refresh_input_ids()

    def render_mixer(self):
        for widget in self.mixer_frame.winfo_children():
            widget.destroy()
        mode = self.is_streamer_mode.get()

        for name in AUDIO_SINKS:
            color = THEME.get(name, "white")
            self.create_channel_strip(name, color, mode, is_mic=False)

        ttk.Separator(self.mixer_frame, orient="vertical").pack(side="left", fill="y", padx=20, pady=20)
        self.create_channel_strip("Mic", THEME["Mic"], mode, is_mic=True)

    def create_channel_strip(self, name, color, mode, is_mic):
        card = tk.Frame(self.mixer_frame, bg=THEME["Card"])
        card.pack(side="left", expand=True, fill="both", padx=10)
        
        title = name.upper() if not is_mic else "MICROPHONE"
        tk.Label(card, text=title, font=("Segoe UI", 14, "bold"), bg=THEME["Card"], fg=color).pack(pady=20)
        
        controls = tk.Frame(card, bg=THEME["Card"])
        controls.pack(expand=True, fill="both", padx=10)

        if not is_mic:
            self.create_slider(controls, name, "user_input", "YOU" if mode else "VOL", color, side="left" if mode else "top")
            if mode:
                ttk.Separator(controls, orient="vertical").pack(side="left", fill="y", padx=10, pady=30)
                self.create_slider(controls, name, "stream_input", "STREAM", "#FFFFFF", side="right")
        else:
            self.create_slider(controls, name, "chat_input", "CHAT/APPS", color, side="left")
            if mode:
                ttk.Separator(controls, orient="vertical").pack(side="left", fill="y", padx=10, pady=30)
                self.create_slider(controls, name, "stream_input", "STREAM", "#FFFFFF", side="right")

    def create_slider(self, parent, main_key, sub_key, label, color, side="top"):
        f = tk.Frame(parent, bg=THEME["Card"])
        f.pack(side=side, expand=True, fill="both", padx=5)
        tk.Label(f, text=label, font=("bold", 8), bg=THEME["Card"], fg="gray").pack(pady=5)
        
        cmd = lambda v: self.set_volume(main_key, sub_key, v)
        s = tk.Scale(f, from_=100, to=0, orient="vertical", bg=THEME["Card"], fg="white", 
                     troughcolor="#1F232F", activebackground=color, highlightthickness=0, bd=0, 
                     command=cmd)
        
        default_val = 100 if "chat" in sub_key else (80 if "stream" in sub_key else 50)
        s.set(default_val)
        s.pack(expand=True, fill="y", pady=5)
        threading.Thread(target=lambda: self.set_volume(main_key, sub_key, default_val)).start()

    # --- Setup ---
    def open_setup_dialog(self):
        sinks_raw = self.run_cmd("pactl list sinks")
        hw_sinks = {}
        current_name = None
        current_desc = None
        
        for line in sinks_raw.split('\n'):
            line = line.strip()
            if line.startswith("Name:"):
                current_name = line.split(":", 1)[1].strip()
            elif line.startswith("Description:"):
                current_desc = line.split(":", 1)[1].strip()
                # نستبعد أجهزتنا الافتراضية من قائمة السماعات الحقيقية
                is_virtual = any(x in current_name for x in AUDIO_SINKS + [STREAM_MIX_NAME, "Internal"])
                if current_name and not is_virtual:
                    hw_sinks[current_desc] = current_name
                    current_name = None

        sources_raw = self.run_cmd("pactl list sources")
        hw_sources = {}
        
        for line in sources_raw.split('\n'):
            line = line.strip()
            if line.startswith("Name:"):
                current_name = line.split(":", 1)[1].strip()
            elif line.startswith("Description:"):
                current_desc = line.split(":", 1)[1].strip()
                # نستبعد المايكات الافتراضية
                is_virtual = MIC_INTERNAL_ID in current_name or ".monitor" in current_name
                if current_name and not is_virtual:
                    hw_sources[current_desc] = current_name
                    current_name = None

        d = tk.Toplevel(self.root)
        d.title("Audio Setup")
        d.geometry("450x300")
        d.configure(bg=THEME["Card"])
        
        tk.Label(d, text="Headphones (Output):", bg=THEME["Card"], fg="white", font=("bold")).pack(pady=(20, 5))
        c_out = ttk.Combobox(d, values=list(hw_sinks.keys()), state="readonly", width=40)
        c_out.pack(pady=5, padx=20)
        
        saved_out = self.config.get("selected_output")
        if saved_out:
            for desc, name in hw_sinks.items():
                if name == saved_out: c_out.set(desc); break

        tk.Label(d, text="Microphone (Input):", bg=THEME["Card"], fg="white", font=("bold")).pack(pady=(20, 5))
        c_in = ttk.Combobox(d, values=list(hw_sources.keys()), state="readonly", width=40)
        c_in.pack(pady=5, padx=20)
        
        saved_in = self.config.get("selected_input")
        if saved_in:
            for desc, name in hw_sources.items():
                if name == saved_in: c_in.set(desc); break

        def apply():
            if c_out.get() in hw_sinks: self.config["selected_output"] = hw_sinks[c_out.get()]
            if c_in.get() in hw_sources: self.config["selected_input"] = hw_sources[c_in.get()]
            self.save_config()
            threading.Thread(target=self.initial_setup, daemon=True).start()
            d.destroy()
        
        tk.Button(d, text="SAVE & APPLY", bg=THEME["Accent"], font=("bold"), command=apply).pack(pady=25)

if __name__ == "__main__":
    root = tk.Tk()
    app = SonarFinalFixedApp(root)
    root.mainloop()
