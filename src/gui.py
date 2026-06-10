# Dubhe AI Switch GUI - Dubhe AI ????????????
import sys, os, json, threading, time, queue, socket, webbrowser
from pathlib import Path
import customtkinter as ctk
import core

APP_TITLE = "Dubhe AI Switch"
VERSION = "1.0.0"
BG = "#080c18"
FG = "#e0e6f0"
ACCENT = "#3b82f6"
ACCENT2 = "#93c5fd"
CARD_BG = "#0f172a"
MUTED = "#64748b"
GREEN = "#34c759"
RED = "#e55353"
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("520x680")
        self.minsize(440, 520)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        self.runner = core.AdapterRunner(log_fn=self._log)
        self.log_queue = queue.Queue()
        self._show_key = False
        self._current_model = ""
        self._current_upstream = ""
        self._build_ui()
        self._load_providers()
        self._pump_log()
        self.after(500, self._check_adapter_status)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(6, weight=1)
        # Title
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=20, pady=(16,2))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="Dubhe AI Switch", font=ctk.CTkFont(size=20,weight="bold"), text_color=ACCENT2).grid(row=0,column=0,sticky="w")
        ctk.CTkLabel(top, text="v"+VERSION, font=ctk.CTkFont(size=11), text_color=MUTED).grid(row=0,column=1,sticky="e")
    # Status bar
    status = ctk.CTkFrame(self, corner_radius=10, fg_color=CARD_BG, border_width=1)
    status.grid(row=1, column=0, sticky="ew", padx=20, pady=4)
    status.grid_columnconfigure(2, weight=1)
    self.dot = ctk.CTkLabel(status, text="\u25cf", font=ctk.CTkFont(size=18), text_color="#666", width=20)
    self.dot.grid(row=0, column=0, padx=(14,4), pady=10)
    self.status_label = ctk.CTkLabel(status, text="Disconnected", font=ctk.CTkFont(size=13,weight="bold"))
    self.status_label.grid(row=0, column=1, sticky="w", pady=10)
    self.model_label = ctk.CTkLabel(status, text="", font=ctk.CTkFont(size=11), text_color=MUTED)
    self.model_label.grid(row=0, column=2, sticky="e", padx=(0,14), pady=10)
    # Config card
    cfg = ctk.CTkFrame(self, corner_radius=10, fg_color=CARD_BG, border_width=1)
    cfg.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
    cfg.grid_columnconfigure(0, weight=1)
    # Provider row
    r0 = ctk.CTkFrame(cfg, fg_color="transparent")
    r0.pack(fill="x", padx=14, pady=(12,4))
    ctk.CTkLabel(r0, text="Provider", width=60, anchor="w", text_color=MUTED).pack(side="left")
    self.provider_menu = ctk.CTkOptionMenu(r0, values=[], command=self._on_provider_change, dynamic_resizing=False)
    self.provider_menu.pack(side="left", padx=(0,6), fill="x", expand=True)
    # Model row
    r1 = ctk.CTkFrame(cfg, fg_color="transparent")
    r1.pack(fill="x", padx=14, pady=4)
    ctk.CTkLabel(r1, text="Model", width=60, anchor="w", text_color=MUTED).pack(side="left")
    self.model_menu = ctk.CTkOptionMenu(r1, values=[], dynamic_resizing=False)
    self.model_menu.pack(side="left", padx=(0,6), fill="x", expand=True)
    # API Key row
    r2 = ctk.CTkFrame(cfg, fg_color="transparent")
    r2.pack(fill="x", padx=14, pady=4)
    ctk.CTkLabel(r2, text="API Key", width=60, anchor="w", text_color=MUTED).pack(side="left")
    self.key_var = ctk.StringVar()
    self.key_entry = ctk.CTkEntry(r2, textvariable=self.key_var, placeholder_text="Paste your API Key...", show="*")
    self.key_entry.pack(side="left", fill="x", expand=True)
    self.show_btn = ctk.CTkButton(r2, text="Show", width=52, height=28, command=self._toggle_key, fg_color="transparent", border_width=1, text_color=("#333","#ccc"))
    self.show_btn.pack(side="left", padx=(4,0))
    # Key URL
    r3 = ctk.CTkFrame(cfg, fg_color="transparent")
    r3.pack(fill="x", padx=14, pady=(4,12))
    self.key_url_label = ctk.CTkLabel(r3, text="Get API Key", text_color=ACCENT, font=ctk.CTkFont(size=11,underline=True), cursor="hand2")
    self.key_url_label.pack(side="left")
    self.key_url_label.bind("<Button-1>", lambda e: self._open_key_url())
    # Buttons
    bf = ctk.CTkFrame(self, fg_color="transparent")
    bf.grid(row=3, column=0, sticky="ew", padx=20, pady=4)
    bf.grid_columnconfigure((0,1), weight=1)
    self.start_btn = ctk.CTkButton(bf, text="Start Proxy", command=self._start, fg_color=ACCENT, hover_color="#2563eb", height=36, font=ctk.CTkFont(size=14,weight="bold"))
    self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0,4))
    self.stop_btn = ctk.CTkButton(bf, text="Stop & Restore", command=self._stop, fg_color=RED, hover_color="#c43838", height=36, font=ctk.CTkFont(size=14,weight="bold"), state="disabled")
    self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(4,0))
    # Log card
    lc = ctk.CTkFrame(self, corner_radius=10, fg_color=CARD_BG, border_width=1)
    lc.grid(row=4, rowspan=2, column=0, sticky="nsew", padx=20, pady=4)
    lc.grid_columnconfigure(0, weight=1)
    lc.grid_rowconfigure(1, weight=1)
    lh = ctk.CTkFrame(lc, fg_color="transparent")
    lh.grid(row=0, column=0, sticky="ew", padx=14, pady=(10,4))
    lh.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(lh, text="Log", font=ctk.CTkFont(size=12,weight="bold"), text_color=MUTED).grid(row=0, column=0, sticky="w")
    self.log_text = ctk.CTkTextbox(lc, font=ctk.CTkFont(size=11), fg_color="#060a14", text_color="#8a93b0", state="disabled")
    self.log_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0,10))

    def _toggle_key(self):
        self._show_key = not self._show_key
        self.key_entry.configure(show="" if self._show_key else "*")
        self.show_btn.configure(text="Hide" if self._show_key else "Show")
    def _open_key_url(self):
        url = getattr(self, "_key_url", "")
        if url:
            webbrowser.open(url)
    def _on_provider_change(self, label):
        pid = self._pid_for_label.get(label, "")
        prov = core.PROVIDERS.get(pid)
        if prov:
            self.model_menu.configure(values=prov["models"])
            if prov["models"]:
                self.model_menu.set(prov["models"][0])
            self._key_url = prov["key_url"]
            self.key_url_label.configure(text="Get " + prov["label"] + " API Key")
            saved = core.get_saved_providers().get(pid, "")
            self.key_var.set(saved)
    def _load_providers(self):
        self._pid_for_label = {}
        labels = []
        for pid, prov in core.PROVIDERS.items():
            labels.append(prov["label"])
            self._pid_for_label[prov["label"]] = pid
        for i, cp in enumerate(core.load_custom()):
            lbl = cp["label"] + " (custom)"
            labels.append(lbl)
            self._pid_for_label[lbl] = "custom:" + str(i)
        if labels:
            self.provider_menu.configure(values=labels)
            self.provider_menu.set(labels[0])
            self._on_provider_change(labels[0])
    def _start(self):
        label = self.provider_menu.get()
        pid = self._pid_for_label.get(label, "")
        model = self.model_menu.get()
        api_key = self.key_var.get().strip()
        if not api_key:
            self._log("Error: API Key is required")
            return
        if pid.startswith("custom:"):
            idx = int(pid[7:])
            items = core.load_custom()
            if idx < len(items):
                self._current_upstream = items[idx]["upstream"]
                core.save_provider_key("custom:" + str(idx), api_key)
        else:
            prov = core.PROVIDERS.get(pid)
            if not prov:
                self._log("Error: Unknown provider"); return
            self._current_upstream = prov["upstream"]
            core.save_provider_key(pid, api_key)
        self._current_model = model
        try:
            core.write_adapter_config(self._current_upstream, model, api_key)
            core.backup_config_toml()
            core.apply_codex_config(model)
            if self.runner.start():
                self.start_btn.configure(state="disabled")
                self.stop_btn.configure(state="normal")
                self._update_status(True, model + " via " + label)
                self._log("Started: " + model + " via " + label)
            else:
                self._log("Error: Failed to start proxy")
        except Exception as e:
            self._log("Error: " + str(e))
    def _stop(self):
        try:
            msg = core.restore_openai()
            self._log(msg)
        except Exception as e:
            self._log("Restore warning: " + str(e))
        self.runner.stop()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self._running = False
        self._update_status(False)
        self._log("Stopped - restored OpenAI config")

    def minimize_to_tray(self):
        self.withdraw()
        self._create_tray()
        self._log("Minimized to system tray")
    def _create_tray(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
            icon_size = 64
            img = Image.new("RGBA", (icon_size, icon_size), (8, 12, 24, 255))
            draw = ImageDraw.Draw(img)
            draw.ellipse([8, 8, 56, 56], fill=(59, 130, 246, 255))
            draw.text((20, 18), "D", fill=(147, 197, 253, 255))
            menu = pystray.Menu(
                pystray.MenuItem("Show Window", self._show_window, default=True),
                pystray.MenuItem("Stop Proxy & Exit", self._quit_app),
            )
            self._tray_icon = pystray.Icon("dubhe-switch", img, "Dubhe AI Switch", menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
        except ImportError:
            self._log("pystray not installed - tray icon unavailable")
    def _show_window(self):
        self.deiconify()
        self.lift()
        if self._tray_icon:
            self._tray_icon.stop()
            self._tray_icon = None
    def _quit_app(self):
        if self._running:
            self.runner.stop()
        if self._tray_icon:
            self._tray_icon.stop()
        self.quit()
        os._exit(0)
    def _log(self, msg):
        self.log_queue.put(str(msg))
    def _pump_log(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(100, self._pump_log)
    def _update_status(self, running=False, info=""):
        if running:
            self.dot.configure(text_color=GREEN)
            self.status_label.configure(text="Connected")
            self.model_label.configure(text=info)
        else:
            self.dot.configure(text_color="#666")
            self.status_label.configure(text="Disconnected")
            self.model_label.configure(text="")
    def _check_adapter_status(self):
        if core.adapter_running():
            self.dot.configure(text_color=GREEN)
            self.status_label.configure(text="Adapter Running")
            self._running = True
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
        self.after(5000, self._check_adapter_status)
