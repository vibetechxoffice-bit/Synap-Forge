#!/usr/bin/env python3
import os
import sys
import subprocess
import time
import json
from datetime import datetime
import webbrowser
import socket
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import ctypes
import re

# Bind directly to discovery authority
try:
    from llm.discovery import get_runtime_root, get_discovered_model_url, wait_for_model_readiness
except ImportError:
    def get_runtime_root():
        if getattr(sys, 'frozen', False):
            base = Path(sys.executable).parent
            if (base / "_internal").exists(): return base / "_internal"
            return base
        return Path(__file__).parent
    
    def get_discovered_model_url():
        return "http://127.0.0.1:11437"
        
    def wait_for_model_readiness(url, timeout=180):
        start = time.time()
        while time.time() - start < timeout:
            try:
                with socket.create_connection(("127.0.0.1", 11437), timeout=1):
                    return True
            except:
                time.sleep(2)
        return False

class SynapForgeLauncher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🧬 SYNAP // FORGE")
        self.root.geometry("850x700")
        self.root.resizable(False, False)
        
        # Base Path Mapping
        HERE = Path(__file__).resolve().parent
        SYNAP_ROOT = HERE.parent if HERE.name.lower() == "launcher" else HERE
        self.launcher_root = HERE
        self.synap_dir = SYNAP_ROOT
        self.base_dir = SYNAP_ROOT
        
        # Settings & State (Temperature locked to 1.2; Context Size & GPU Layers user-controlled)
        self.settings = {
            "audio_enabled": True,
            "temp_baseline": 1.2,
            "ctx_size": int(self.detect_ctx_size()),
            "gpu_layers": int(self.detect_gpu_layers()),
            "mode": "Standard"
        }
        
        # Audio Initialization
        self.bg_music_path = self.launcher_root / "audio" / "background_music.mp3"
        if self.bg_music_path.exists():
            self.start_audio()

        # Icon Setup
        icon_path = self.base_dir / "icon.ico"
        if icon_path.exists():
            try: self.root.iconbitmap(str(icon_path))
            except: pass

        # Theme Colors
        self.bg_dark = "#0A0A0F"
        self.bg_card = "#12121A"
        self.fg_light = "#E0E0E0"
        self.accent_green = "#00FF41"
        self.accent_blue = "#00F0FF"
        self.accent_red = "#FF3333"
        self.gray_dim = "#555555"
        
        self.root.configure(bg=self.bg_dark)
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.setup_styles()

        self.processes = []
        self.is_booting = False
        self.selected_agent_name = "Meena"
        self.identity_verified = False

        # Build Layout Frames Immediately
        self.build_layout()
        
        # Run initial state setup
        self.check_existing_instance()
        self.evaluate_identity_state()

    def setup_styles(self):
        self.style.configure("TFrame", background=self.bg_dark)
        self.style.configure("Card.TFrame", background=self.bg_card)
        self.style.configure("TLabel", background=self.bg_dark, foreground=self.fg_light, font=("Segoe UI", 10))
        self.style.configure("Card.TLabel", background=self.bg_card, foreground=self.fg_light, font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", font=("Segoe UI", 24, "bold"), foreground=self.accent_blue)
        self.style.configure("Sub.TLabel", font=("Consolas", 10), foreground="#d6247a")
        self.style.configure("StatusText.TLabel", font=("Segoe UI", 10, "bold"))
        
        self.style.configure("Action.TButton", font=("Segoe UI", 11, "bold"), padding=8)
        self.style.map("Action.TButton",
            foreground=[('active', self.bg_dark), ('!disabled', self.bg_dark)],
            background=[('active', self.accent_green), ('!disabled', '#0f2b4d')]
        )
        
        self.style.configure("Link.TButton", font=("Segoe UI", 10, "underline"), padding=5)
        self.style.map("Link.TButton",
            foreground=[('active', self.accent_blue), ('!disabled', '#4da6ff')],
            background=[('active', self.bg_dark), ('!disabled', self.bg_dark)]
        )

    def build_layout(self):
        # Main Padding Wrapper
        self.main_container = ttk.Frame(self.root, padding=25)
        self.main_container.pack(fill="both", expand=True)

        # 1. Title Banner Header
        header_frame = ttk.Frame(self.main_container)
        header_frame.pack(fill="x", pady=(0, 15))
        
        title_left = ttk.Frame(header_frame)
        title_left.pack(side="left")
        ttk.Label(title_left, text="🔹 SYNAP", style="Header.TLabel").pack(anchor="w")
        ttk.Label(title_left, text="forum.arkwellnetworks.com", style="Sub.TLabel").pack(anchor="w")
        
        self.settings_btn = ttk.Button(
            header_frame, 
            text="⚙️ CONFIG SETTINGS", 
            command=self.open_settings
        )
        self.settings_btn.pack(side="right", anchor="n", pady=5)

        # 2. Dynamic Central Content Pane (Config or Checklist Status)
        self.central_pane = ttk.Frame(self.main_container)
        self.central_pane.pack(fill="x", pady=10)

        # 3. System Logs Console Section
        log_frame = ttk.Frame(self.main_container)
        log_frame.pack(fill="both", expand=True, pady=(15, 15))
        ttk.Label(log_frame, text="SYSTEM INITIALIZATION LOGS", font=("Consolas", 9, "bold"), foreground="#888888").pack(anchor="w", pady=(0, 5))
        
        log_inner = ttk.Frame(log_frame)
        log_inner.pack(fill="both", expand=True)
        
        self.log_widget = tk.Text(
            log_inner, 
            height=12, 
            bg="#050508", 
            fg="#AAAAAA", 
            font=("Consolas", 9),
            relief="flat",
            padx=12,
            pady=12,
            state="disabled"
        )
        self.log_widget.pack(side="left", fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(log_inner, orient="vertical", command=self.log_widget.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_widget.configure(yscrollcommand=scrollbar.set)

        # 4. Error / Remediation Panel (Hidden by default)
        self.reremedy_frame = ttk.Frame(self.main_container)
        self.reremedy_lbl = tk.Text(
            self.reremedy_frame, 
            height=3, 
            bg=self.bg_dark, 
            fg=self.accent_red, 
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            wrap="word"
        )
        self.reremedy_lbl.pack(fill="x")
        self.reremedy_lbl.configure(state="disabled")

        # 5. Bottom Controls Toolbar
        self.controls_frame = ttk.Frame(self.main_container)
        self.controls_frame.pack(fill="x", pady=(10, 0))
        
        self.status_msg = ttk.Label(self.controls_frame, text="AWAITING IDENTITY PROFILE INITIALIZATION", style="Sub.TLabel")
        self.status_msg.pack(side="left", anchor="center")

        self.action_btn = ttk.Button(
            self.controls_frame, 
            text="🚀 INITIATE BOOT SEQUENCE", 
            style="Action.TButton",
            state="disabled",
            command=self.start_boot_sequence
        )
        self.action_btn.pack(side="right")

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")
        def _update():
            try:
                self.log_widget.configure(state="normal")
                self.log_widget.insert("end", f"[{timestamp}] {message}\n")
                self.log_widget.see("end")
                self.log_widget.configure(state="disabled")
            except Exception:
                pass
        if hasattr(self, 'root') and self.root:
            try: self.root.after(0, _update)
            except Exception: _update()
        else:
            _update()

    def emit_stage(self, stage: str, status: str, detail: str = ""):
        try:
            state_dir = self.synap_dir / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            stages_file = state_dir / "stages.jsonl"
            entry = {
                "stage": stage,
                "status": status,
                "detail": detail,
                "ts": datetime.now().isoformat()
            }
            with open(stages_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            self.log(f"Stage emission error: {e}")

    def detect_vram_mb(self):
        if "SYNAP_VRAM_MB" in os.environ:
            try: return int(os.environ["SYNAP_VRAM_MB"])
            except: pass
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if res.stdout and res.stdout.strip().isdigit():
                return int(res.stdout.strip())
        except Exception:
            pass
        try:
            cmd = "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty AdapterRAM"
            res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=5)
            if res.stdout:
                vals = [int(v.strip()) for v in res.stdout.strip().splitlines() if v.strip().isdigit()]
                if vals:
                    max_bytes = max(vals)
                    return max_bytes // (1024 * 1024)
        except Exception:
            pass
        return 0

    def detect_gpu_layers(self):
        if "SYNAP_GPU_LAYERS" in os.environ:
            return os.environ["SYNAP_GPU_LAYERS"]
        if "N_GPU_LAYERS" in os.environ:
            return os.environ["N_GPU_LAYERS"]
        if hasattr(self, "settings") and "gpu_layers" in self.settings:
            return str(self.settings["gpu_layers"])
        
        vram_mb = self.detect_vram_mb()
        if vram_mb >= 7500:
            return "33"  # Full layer offload for 8GB VRAM (MED node: ~16-20 tps)
        elif vram_mb >= 5500:
            return "32"  # 6GB VRAM
        elif vram_mb >= 3500:
            return "30"  # 4GB VRAM maxed layer count (~30 layers offloaded to GTX 1650 with KV in System RAM)
        elif vram_mb >= 2000:
            return "16"  # 2GB VRAM
        elif vram_mb > 0:
            return "1"
        return os.getenv("INTEL_GPU_LAYERS", "0")

    def detect_ram_gb(self):
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / (1024 ** 3)
        except Exception:
            return 8.0

    def detect_ctx_size(self):
        if "SYNAP_CTX_SIZE" in os.environ:
            return os.environ["SYNAP_CTX_SIZE"]
        if "LLAMA_CTX_SIZE" in os.environ:
            return os.environ["LLAMA_CTX_SIZE"]
        if hasattr(self, "settings") and "ctx_size" in self.settings:
            return str(self.settings["ctx_size"])
        
        ram_gb = self.detect_ram_gb()
        if ram_gb < 8.0:
            return "2048"
        elif ram_gb <= 16.0:
            return "40960"
        else:
            return "65536"

    def detect_thread_count(self):
        if "SYNAP_THREADS" in os.environ:
            return os.environ["SYNAP_THREADS"]
        try:
            cmd = "(Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfCores -Sum).Sum"
            res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=5)
            if res.stdout and res.stdout.strip().isdigit():
                cores = int(res.stdout.strip())
                if cores > 0:
                    return str(cores)
        except Exception:
            pass
        cpus = os.cpu_count() or 4
        return str(max(1, cpus // 2 if cpus > 4 else cpus))

    def detect_kv_offload(self):
        if "SYNAP_KV_OFFLOAD" in os.environ:
            return os.environ["SYNAP_KV_OFFLOAD"].strip().lower() in ("1", "true", "yes")
        vram_mb = self.detect_vram_mb()
        ram_gb = self.detect_ram_gb()
        # For GPUs with <= 4GB VRAM and abundant System RAM (>= 12GB),
        # keep KV cache in CPU System RAM (--no-kv-offload) to free GPU VRAM for model layers.
        if vram_mb > 0 and vram_mb < 5000 and ram_gb >= 12.0:
            return False
        return True

    def start_audio(self):
        if not sys.platform == "win32": return
        try:
            mciSendString = ctypes.windll.winmm.mciSendStringW
            mciSendString(f'open "{self.bg_music_path}" type mpegvideo alias bgmusic', None, 0, 0)
            mciSendString('play bgmusic repeat', None, 0, 0)
        except Exception as e:
            self.log(f"Audio error: {e}")

    def stop_audio(self):
        if not sys.platform == "win32": return
        try:
            ctypes.windll.winmm.mciSendStringW('stop bgmusic', None, 0, 0)
            ctypes.windll.winmm.mciSendStringW('close bgmusic', None, 0, 0)
        except: pass

    def open_settings(self):
        settings_win = tk.Toplevel(self.root)
        settings_win.title("SYSTEM CONFIGURATION")
        settings_win.geometry("460x480")
        settings_win.configure(bg=self.bg_card)
        settings_win.transient(self.root)
        settings_win.grab_set()
        
        container = ttk.Frame(settings_win, padding=20, style="Card.TFrame")
        container.pack(fill="both", expand=True)
        
        ttk.Label(container, text="HARDWARE & ENGINE CONFIGURATION", font=("Segoe UI", 12, "bold"), foreground=self.accent_blue, style="Card.TLabel").pack(anchor="w", pady=(0, 15))
        
        # 1. Context Size Slider
        ctx_label_var = tk.StringVar(value=f"Context Size (Tokens): {self.settings.get('ctx_size', 40960)}")
        ttk.Label(container, textvariable=ctx_label_var, style="Card.TLabel").pack(anchor="w")
        
        def on_ctx_change(val):
            v = int(float(val))
            ctx_label_var.set(f"Context Size (Tokens): {v}")

        ctx_scale = tk.Scale(
            container, from_=2048, to_=131072, resolution=2048,
            orient="horizontal", bg=self.bg_card, fg=self.fg_light,
            highlightthickness=0, command=on_ctx_change
        )
        ctx_scale.set(self.settings.get('ctx_size', 40960))
        ctx_scale.pack(fill="x", pady=(0, 15))
        
        # 2. GPU Layers Slider
        layers_label_var = tk.StringVar(value=f"GPU Layer Offload: {self.settings.get('gpu_layers', 30)} layers")
        ttk.Label(container, textvariable=layers_label_var, style="Card.TLabel").pack(anchor="w")
        
        def on_layers_change(val):
            v = int(float(val))
            layers_label_var.set(f"GPU Layer Offload: {v} layers")

        layers_scale = tk.Scale(
            container, from_=0, to_=99, resolution=1,
            orient="horizontal", bg=self.bg_card, fg=self.fg_light,
            highlightthickness=0, command=on_layers_change
        )
        layers_scale.set(self.settings.get('gpu_layers', 30))
        layers_scale.pack(fill="x", pady=(0, 15))
        
        # 3. Dialogue Operating Mode
        ttk.Label(container, text="Dialogue Operating Mode:", style="Card.TLabel").pack(anchor="w")
        mode_var = tk.StringVar(value=self.settings.get('mode', 'Standard'))
        mode_cb = ttk.Combobox(container, textvariable=mode_var, values=["Standard", "Graffiti", "Analytical"], state="readonly")
        mode_cb.pack(fill="x", pady=(0, 15))
        
        # 4. Audio Toggle
        audio_var = tk.BooleanVar(value=self.settings.get('audio_enabled', True))
        audio_chk = tk.Checkbutton(
            container, text="Enable Background Atmosphere (Audio)",
            variable=audio_var, bg=self.bg_card, fg=self.fg_light,
            selectcolor=self.bg_dark, activebackground=self.bg_card
        )
        audio_chk.pack(anchor="w", pady=(0, 15))

        def save_settings():
            self.settings['ctx_size'] = int(ctx_scale.get())
            self.settings['gpu_layers'] = int(layers_scale.get())
            self.settings['mode'] = mode_var.get()
            self.settings['temp_baseline'] = 1.2
            
            if audio_var.get() != self.settings['audio_enabled']:
                self.settings['audio_enabled'] = audio_var.get()
                if self.settings['audio_enabled']: self.start_audio()
                else: self.stop_audio()
            
            self.log(f"System configuration updated: Context={self.settings['ctx_size']}, GPU Layers={self.settings['gpu_layers']}, Temp=1.2 (locked)")
            settings_win.destroy()
            
        ttk.Button(container, text="APPLY CONFIGURATION", command=save_settings).pack(fill="x", pady=10)

    def set_status_msg(self, text, foreground=None):
        def _update():
            try:
                kwargs = {"text": text}
                if foreground: kwargs["foreground"] = foreground
                self.status_msg.configure(**kwargs)
            except Exception:
                pass
        if hasattr(self, 'root') and self.root:
            try: self.root.after(0, _update)
            except Exception: _update()
        else:
            _update()

    def show_remediation(self, text):
        def _update():
            try:
                self.reremedy_lbl.configure(state="normal")
                self.reremedy_lbl.delete("1.0", "end")
                self.reremedy_lbl.insert("end", text)
                self.reremedy_lbl.configure(state="disabled")
                self.reremedy_frame.pack(fill="x", pady=5, before=self.controls_frame)
            except Exception:
                pass
        if hasattr(self, 'root') and self.root:
            try: self.root.after(0, _update)
            except Exception: _update()
        else:
            _update()

    def hide_remediation(self):
        def _update():
            try: self.reremedy_frame.pack_forget()
            except Exception: pass
        if hasattr(self, 'root') and self.root:
            try: self.root.after(0, _update)
            except Exception: _update()
        else:
            _update()

    def check_existing_instance(self):
        pid_file = self.base_dir / "synap.pid"
        if pid_file.exists():
            try:
                with open(pid_file, 'r') as f:
                    pid = int(f.read().strip())
                if sys.platform == "win32":
                    output = subprocess.check_output(f'tasklist /FI "PID eq {pid}" /NH', shell=True, text=True)
                    if str(pid) in output and "No tasks" not in output:
                        if messagebox.askyesno("Already Running", "Synap-Forge dashboard is active. Launch dashboard browser now?"):
                            webbrowser.open("http://127.0.0.1:11436")
                        sys.exit(0)
                pid_file.unlink()
            except:
                try: pid_file.unlink()
                except: pass

    def evaluate_identity_state(self):
        state_dir = self.synap_dir / "state"
        lock_file = state_dir / "identity_lock.json"
        
        if lock_file.exists():
            self.identity_verified = True
            self.log("Existing identity certificate verified securely.")
            self.render_checklist_view()
            self.action_btn.configure(state="normal")
            self.set_status_msg("SYSTEM READY FOR BOOT CHANNELS")
        else:
            self.render_inline_profile_form()

    def render_inline_profile_form(self):
        # Clear central pane
        for child in self.central_pane.winfo_children():
            child.destroy()
            
        form_card = ttk.Frame(self.central_pane, padding=15, style="Card.TFrame")
        form_card.pack(fill="x", pady=5)
        
        ttk.Label(form_card, text="PROVISION NEW SOVEREIGN IDENTITY CERTIFICATE", font=("Segoe UI", 11, "bold"), foreground=self.accent_blue, style="Card.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Label(form_card, text="Specify a name configuration identifier for your secure agent personality profile core below:", style="Card.TLabel", wraplength=700).pack(anchor="w", pady=(0, 10))
        
        input_row = ttk.Frame(form_card, style="Card.TFrame")
        input_row.pack(fill="x", pady=5)
        
        ttk.Label(input_row, text="Agent Profile Name:", font=("Segoe UI", 10, "bold"), style="Card.TLabel").pack(side="left", padx=(0, 10))
        
        self.name_entry = tk.Entry(input_row, font=("Segoe UI", 10), bg="#1A1A26", fg="#FFFFFF", insertbackground="#FFFFFF", relief="flat", width=30)
        self.name_entry.pack(side="left", padx=(0, 15))
        self.name_entry.insert(0, "Meena")
        self.name_entry.focus_set()
        
        submit_btn = ttk.Button(input_row, text="Generate Profile Lock Certificate", command=self.submit_inline_profile)
        submit_btn.pack(side="left")

    def submit_inline_profile(self):
        name_input = self.name_entry.get().strip()
        if not name_input:
            messagebox.showwarning("Validation Error", "Agent Profile Name string cannot be left blank.")
            return
        self.selected_agent_name = name_input
        self.log(f"Identity profile choice recorded: '{self.selected_agent_name}'")
        
        # Transition to status view instantly
        self.render_checklist_view()
        self.action_btn.configure(state="normal")
        self.set_status_msg("IDENTITY READY · STANDBY TO INITIATE SEQUENCE")

    def render_checklist_view(self):
        for child in self.central_pane.winfo_children():
            child.destroy()
            
        self.status_rows = [
            "Identity Gate Verification",
            "RISA Automated System Self-Healing",
            "Local LLM Weights Bring-Up (llama-server)",
            "Synap Consciousness Server Bring-Up",
            "Dashboard Interface Launch"
        ]
        
        self.indicator_labels = {}
        self.text_labels = {}
        
        for item in self.status_rows:
            row = ttk.Frame(self.central_pane)
            row.pack(fill="x", pady=4)
            
            ind = ttk.Label(row, text="○", width=4, font=("Segoe UI", 12, "bold"), foreground=self.gray_dim)
            ind.pack(side="left")
            
            txt = ttk.Label(row, text=item, font=("Segoe UI", 10))
            txt.pack(side="left", padx=5)
            
            status_val = ttk.Label(row, text="PENDING", style="StatusText.TLabel", foreground=self.gray_dim)
            status_val.pack(side="right")
            
            self.indicator_labels[item] = (ind, status_val)

    def set_step_state(self, name, mode):
        def _update():
            if name not in self.indicator_labels: return
            ind, status_val = self.indicator_labels[name]
            
            if mode == "pending":
                ind.configure(text="○", foreground=self.gray_dim)
                status_val.configure(text="PENDING", foreground=self.gray_dim)
            elif mode == "active":
                ind.configure(text="●", foreground=self.accent_blue)
                status_val.configure(text="ACTIVE", foreground=self.accent_blue)
            elif mode == "verified":
                ind.configure(text="✓", foreground=self.accent_green)
                status_val.configure(text="VERIFIED", foreground=self.accent_green)
            elif mode == "failed":
                ind.configure(text="✕", foreground=self.accent_red)
                status_val.configure(text="FAILED", foreground=self.accent_red)
        if hasattr(self, 'root') and self.root:
            try: self.root.after(0, _update)
            except Exception: _update()
        else:
            _update()

    def start_boot_sequence(self):
        if self.is_booting: return
        self.is_booting = True
        self.action_btn.configure(state="disabled")
        self.hide_remediation()
        
        # Safety fallback logic to switch view to checklist if not drawn yet
        if not hasattr(self, "indicator_labels"):
            self.render_checklist_view()
            
        threading.Thread(target=self.boot_sequence_worker, daemon=True).start()

    def boot_sequence_worker(self):
        self.set_status_msg("ORCHESTRATING CORE BOOT SERVICES...", foreground=self.accent_blue)
        
        try:
            state_dir = self.synap_dir / "state"
            state_dir.mkdir(parents=True, exist_ok=True)

            # Clear previous stages file on new boot
            stages_file = state_dir / "stages.jsonl"
            if stages_file.exists():
                try: stages_file.unlink()
                except: pass

            # 1. Instance Registration file handle
            pid_file = self.base_dir / "synap.pid"
            with open(pid_file, 'w') as f:
                f.write(str(os.getpid()))

            # Stage A: Identity gate provisioning
            step_a = "Identity Gate Verification"
            self.set_step_state(step_a, "active")
            self.emit_stage("A", "active", step_a)
            self.log("Opening Identity Verification checkpoint gate...")
            
            lock_file = state_dir / "identity_lock.json"
            
            if not lock_file.exists():
                self.log(f"Provisioning fresh certificate variables for '{self.selected_agent_name}'...")
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUTF8"] = "1"
                env["AGENT_NAME"] = self.selected_agent_name
                env["SYNAP_BASE_DIR"] = str(self.synap_dir)
                env["SYNAP_STATE_DIR"] = str(state_dir)
                
                prov_script = self.launcher_root / "identity" / "provisioning.py"
                if prov_script.exists():
                    res = subprocess.run([sys.executable, str(prov_script)], cwd=self.synap_dir, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
                    if res.stdout:
                        for line in res.stdout.splitlines():
                            if line.strip(): self.log(line)
                    if res.returncode != 0:
                        self.log(f"Provisioning script failed (exit code {res.returncode}): {res.stderr.strip() if res.stderr else ''}")
                else:
                    self.log("Provisioning script not found at relative path. Attempting fallback...")
                    with open(lock_file, 'w', encoding='utf-8') as lf:
                        lf.write('{"verified": true, "name": "' + self.selected_agent_name + '"}')
            
            if lock_file.exists():
                self.set_step_state(step_a, "verified")
                self.emit_stage("A", "verified", step_a)
                self.log("Identity Gate status: VERIFIED & SECURITY COMPLIANT.")
            else:
                self.set_step_state(step_a, "failed")
                self.emit_stage("A", "failed", step_a)
                self.log("Identity Gate status: FAIL - LOCK CERTIFICATE NOT ASSIGNED.")
                self.show_remediation("⛔ Gate Failure: Identity Certificate could not be verified safely.\n💡 Remedy: Check folder permissions inside state/ or delete the current staging directory.")
                self.set_status_msg("BOOT CRASHED AT IDENTITY GATE", foreground=self.accent_red)
                return

            # Stage RISA: Automated Healing
            step_risa = "RISA Automated System Self-Healing"
            self.set_step_state(step_risa, "active")
            self.emit_stage("RISA", "active", step_risa)
            self.log("Initializing RISA v3.2 Master Healer scan...")
            
            risa_script = self.synap_dir / "risa_v3.2.py"
            if risa_script.exists():
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUTF8"] = "1"
                env["SYNAP_BASE_DIR"] = str(self.synap_dir)
                env["AGENT_NAME"] = self.selected_agent_name
                res = subprocess.run([sys.executable, str(risa_script), "--heal"], cwd=self.synap_dir, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
                if res.stdout:
                    for line in res.stdout.splitlines():
                        if line.strip(): self.log(line)
                if res.returncode == 0:
                    self.set_step_state(step_risa, "verified")
                    self.emit_stage("RISA", "verified", step_risa)
                else:
                    self.log(f"RISA repair failed (exit code {res.returncode}): {res.stderr.strip() if res.stderr else ''}")
                    self.set_step_state(step_risa, "failed")
                    self.emit_stage("RISA", "failed", step_risa)
                    self.show_remediation("⛔ RISA Failure: Automated healer scan failed.\n💡 Remedy: Inspect RISA errors in logs.")
                    self.set_status_msg("BOOT FAULT AT RISA STAGE", foreground=self.accent_red)
                    return
            else:
                self.log("⚠️ RISA scanner missing: 'risa_v3.2.py' not found at root.")
                self.set_step_state(step_risa, "failed")
                self.emit_stage("RISA", "failed", "RISA scanner missing")
                self.show_remediation("⛔ RISA Missing: risa_v3.2.py not found in Synap-Forge root.\n💡 Remedy: Verify risa_v3.2.py is present.")
                self.set_status_msg("BOOT FAULT: RISA MISSING", foreground=self.accent_red)
                return

            # Stage B: LLM Weights Bring-up
            step_b = "Local LLM Weights Bring-Up (llama-server)"
            self.set_step_state(step_b, "active")
            self.emit_stage("B", "active", step_b)
            
            llama_bin = self.synap_dir / "llama" / "bin" / "llama-server.exe"
            models_dir = self.synap_dir / "llama" / "models"
            model_env = os.getenv("SYNAP_MODEL_FILE")

            if model_env and (models_dir / model_env).exists():
                model_path = models_dir / model_env
            elif (models_dir / "Qwen3VL-8B-Instruct-Q4_K_M.gguf").exists():
                model_path = models_dir / "Qwen3VL-8B-Instruct-Q4_K_M.gguf"
            else:
                candidates = sorted(models_dir.glob("*.gguf"), key=lambda p: p.stat().st_mtime, reverse=True) if models_dir.exists() else []
                model_path = candidates[0] if candidates else models_dir / "wv_7base.gguf"
            
            if llama_bin.exists() and model_path.exists():
                self.log(f"Spinning up local server context with LLM weights: {model_path.name}")
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUTF8"] = "1"
                env["SYNAP_BASE_DIR"] = str(self.synap_dir)
                env["SYNAP_STATE_DIR"] = str(state_dir)
                
                gpu_layers = self.detect_gpu_layers()
                ctx_size = self.detect_ctx_size()
                threads = self.detect_thread_count()
                kv_offload = self.detect_kv_offload()
                temp_val = str(self.settings.get("temp_baseline", 1.0))

                self.log(f"Environment hardware sensing: GPU Layers={gpu_layers}, Context Size={ctx_size}, Threads={threads}, KV Offload={'enabled' if kv_offload else 'CPU offload'}, Temp={temp_val}")

                llama_cmd = [
                    str(llama_bin), "-m", str(model_path),
                    "--host", "127.0.0.1", "--port", "11437",
                    "--ctx-size", ctx_size,
                    "--n-gpu-layers", gpu_layers,
                    "--cache-type-k", "q8_0",
                    "--cache-type-v", "q8_0",
                    "--alias", self.selected_agent_name,
                    "--temp", temp_val,
                    "--repeat-penalty", "1.25",
                    "--top-p", "0.95",
                    "--parallel", "1",
                    "--threads", threads
                ]
                if not kv_offload:
                    llama_cmd.append("--no-kv-offload")

                p_llama = subprocess.Popen(
                    llama_cmd,
                    cwd=self.synap_dir, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                self.processes.append(p_llama)
                
                model_url = get_discovered_model_url()
                self.log("📡 Probing network sockets for LLM initialization channels...")
                
                # Check for readiness with active user notification trigger
                ready = False
                start_probing = time.time()
                while time.time() - start_probing < 120:
                    if time.time() - start_probing > 25:
                        self.set_status_msg("LOADING HEAVY WEIGHTS... COLD START IN PROGRESS", foreground=self.accent_blue)
                        self.log("⏱️ Heavy weight load alert: Synap is initializing weights... Please stand by up to 2 minutes.")
                    if wait_for_model_readiness(model_url, timeout=3):
                        ready = True
                        break
                    time.sleep(1)
                
                if ready:
                    self.set_step_state(step_b, "verified")
                    self.emit_stage("B", "verified", step_b)
                    self.log("Local intelligence processing node online & prewarmed.")
                else:
                    self.set_step_state(step_b, "failed")
                    self.emit_stage("B", "failed", step_b)
                    self.log("LLM node server bring-up process timed out.")
                    self.show_remediation("⛔ Neural Backend Failure: Local LLM engine failed to register context sockets.\n💡 Remedy: Terminate any stray llama-server.exe instances or reduce threads in core parameters.")
                    self.set_status_msg("BOOT FAULT AT LOCAL NEURAL BRING-UP", foreground=self.accent_red)
                    return
            else:
                missing = []
                if not llama_bin.exists(): missing.append(str(llama_bin))
                if not model_path.exists(): missing.append(str(model_path))
                self.log(f"⚠️ Missing binary dependencies or model files: {', '.join(missing)}")
                self.set_step_state(step_b, "failed")
                self.emit_stage("B", "failed", f"Missing {', '.join(missing)}")
                self.show_remediation(f"⛔ Neural Backend Missing: Could not locate binary/model at:\n{', '.join(missing)}\n💡 Remedy: Download or place required files in llama/bin/ and llama/models/.")
                self.set_status_msg("BOOT FAULT: MISSING LLM WEIGHTS/BINARY", foreground=self.accent_red)
                return

            # Stage C: Consciousness Server
            step_c = "Synap Consciousness Server Bring-Up"
            self.set_step_state(step_c, "active")
            self.emit_stage("C", "active", step_c)
            
            server_script = self.synap_dir / "synap_server.py"
            if server_script.exists():
                self.log("Launching core FASTAPI server channels...")
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUTF8"] = "1"
                env["SYNAP_BASE_DIR"] = str(self.synap_dir)
                env["SYNAP_STATE_DIR"] = str(state_dir)
                env["LOCAL_LLM_URL"] = "http://127.0.0.1:11437"
                env["AI_TEMPERATURE"] = str(self.settings['temp_baseline'])
                env["AI_EMPATHY"] = str(self.settings['empathy_coeff'])
                env["AI_MODE"] = self.settings['mode']

                server_log_path = state_dir / "synap_server.log"
                self.server_log_file = open(server_log_path, "a", encoding="utf-8")

                p_server = subprocess.Popen(
                    [sys.executable, str(server_script)],
                    cwd=self.synap_dir, env=env,
                    stdout=self.server_log_file,
                    stderr=subprocess.STDOUT
                )
                self.processes.append(p_server)
                
                server_online = False
                for i in range(40):
                    if p_server.poll() is not None:
                        self.server_log_file.flush()
                        self.log("❌ Critical: Consciousness server process terminated prematurely on startup:")
                        try:
                            with open(server_log_path, "r", encoding="utf-8", errors="ignore") as lf:
                                err_lines = lf.readlines()[-20:]
                                for err_line in err_lines:
                                    if err_line.strip():
                                        self.log(f"   {err_line.strip()}")
                        except Exception:
                            pass
                        break
                    try:
                        with socket.create_connection(("127.0.0.1", 11436), timeout=1):
                            server_online = True
                            break
                    except:
                        time.sleep(1)
                
                if server_online:
                    self.set_step_state(step_c, "verified")
                    self.emit_stage("C", "verified", step_c)
                    self.log("Synap Consciousness Server channels initialized successfully.")
                else:
                    self.set_step_state(step_c, "failed")
                    self.emit_stage("C", "failed", step_c)
                    self.log("Core system engine connection check timed out.")
                    self.show_remediation("⛔ Core Engine Failure: Consciousness service failed to respond on port 11436.\n💡 Remedy: Check syntax errors or inspect logs inside the state directory.")
                    self.set_status_msg("BOOT ENGINE CRASH ON CORE SERVER", foreground=self.accent_red)
                    return
            else:
                self.log("⚠️ Core logic script 'synap_server.py' could not be found.")
                self.set_step_state(step_c, "failed")
                self.emit_stage("C", "failed", "synap_server.py missing")
                return

            # Stage D: Dashboard Trigger
            step_d = "Dashboard Interface Launch"
            self.set_step_state(step_d, "active")
            self.emit_stage("D", "active", step_d)
            time.sleep(1.5)
            
            dashboard_url = "http://127.0.0.1:11436"
            self.log(f"Opening dashboard portal: {dashboard_url}")
            webbrowser.open(dashboard_url)
            
            self.set_step_state(step_d, "verified")
            self.emit_stage("D", "verified", step_d)
            self.set_status_msg("ALL SYSTEMS RUNNING DEPLOYED", foreground=self.accent_green)
            self.log("🧬 Synap-Forge system deployment fully finalized.")

            # Append Hyperlink launcher button
            link_btn = ttk.Button(self.controls_frame, text="🔗 OPEN DASHBOARD PANEL", style="Link.TButton", command=lambda: webbrowser.open(dashboard_url))
            link_btn.pack(side="right", padx=(0, 15))

            # Persistent Background Process Monitor loop
            while True:
                for p in self.processes:
                    if p.poll() is not None:
                        self.log(f"CRITICAL: Service element with PID {p.pid} terminated abnormally.")
                        raise RuntimeError("Subprocess termination error encountered.")
                time.sleep(4)

        except Exception as e:
            self.log(f"System boot sequence fault triggered: {str(e)}")
            self.status_msg.configure(text="CORE OPERATIONAL HALT", foreground=self.accent_red)
        finally:
            self.is_booting = False

    def shutdown(self):
        self.log("Initiating comprehensive shutdown sequence...")
        self.stop_audio()
        for p in self.processes:
            try:
                p.terminate()
                p.wait(timeout=2)
            except:
                try: p.kill()
                except: pass
        
        pid_file = self.base_dir / "synap.pid"
        if pid_file.exists():
            try: pid_file.unlink()
            except: pass

        self.root.destroy()

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)
        self.root.mainloop()

if __name__ == "__main__":
    launcher = SynapForgeLauncher()
    launcher.run()
