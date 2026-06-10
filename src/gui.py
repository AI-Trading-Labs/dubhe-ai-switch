# Dubhe AI Switch GUI - with i18n support
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

# i18n strings
I18N = {
    "title": {"zh": "Dubhe AI Switch", "en": "Dubhe AI Switch"},
    "disconnected": {"zh": "\u672a\u8fde\u63a5", "en": "Disconnected"},
    "connected": {"zh": "\u5df2\u8fde\u63a5", "en": "Connected"},
    "adapter_running": {"zh": "\u8fd0\u884c\u4e2d", "en": "Adapter Running"},
    "provider": {"zh": "\u63d0\u4f9b\u5546", "en": "Provider"},
    "model": {"zh": "\u6a21\u578b", "en": "Model"},
    "api_key": {"zh": "API Key", "en": "API Key"},
    "get_key": {"zh": "\u83b7\u53d6 API Key", "en": "Get API Key"},
    "paste_key": {"zh": "\u7c98\u8d34 API Key...", "en": "Paste your API Key..."},
    "show": {"zh": "\u663e\u793a", "en": "Show"},
    "hide": {"zh": "\u9690\u85cf", "en": "Hide"},
    "start": {"zh": "\u542f\u52a8\u4ee3\u7406", "en": "Start Proxy"},
    "stop": {"zh": "\u505c\u6b62\u5e76\u8fd8\u539f", "en": "Stop & Restore"},
    "log": {"zh": "\u65e5\u5fd7", "en": "Log"},
    "started": {"zh": "\u5df2\u542f\u52a8", "en": "Started"},
    "stopped": {"zh": "\u5df2\u505c\u6b62 - \u5df2\u8fd8\u539f OpenAI", "en": "Stopped - restored OpenAI config"},
    "minimized": {"zh": "\u5df2\u6700\u5c0f\u5316\u5230\u7cfb\u7edf\u6258\u76d8", "en": "Minimized to system tray"},
    "tray_show": {"zh": "\u663e\u793a\u7a97\u53e3", "en": "Show Window"},
    "tray_exit": {"zh": "\u505c\u6b62\u5e76\u9000\u51fa", "en": "Stop Proxy & Exit"},
    "err_key_required": {"zh": "\u9519\u8bef\uff1a\u8bf7\u586b\u5199 API Key", "en": "Error: API Key is required"},
    "err_unknown_provider": {"zh": "\u9519\u8bef\uff1a\u672a\u77e5\u63d0\u4f9b\u5546", "en": "Error: Unknown provider"},
    "err_start_failed": {"zh": "\u9519\u8bef\uff1a\u542f\u52a8\u5931\u8d25", "en": "Error: Failed to start proxy"},
}

def t(key, lang):
    return I18N.get(key, {}).get(lang, key)

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("520x680")
        self.minsize(440, 520)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.runner = core.AdapterRunner(log_fn=self._log)
        self.log_queue = queue.Queue()
        self._show_key = False
        self._lang = "zh"
        self._current_model = ""
        self._current_upstream = ""
        self._build_ui()
        self._load_providers()
        self._pump_log()
        self.after(500, self._check_adapter_status)

    def _L(self, key):
        return t(key, self._lang)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(6, weight=1)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=20, pady=(16,2))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="Dubhe AI Switch", font=ctk.CTkFont(size=20,weight="bold"), text_color=ACCENT2).grid(row=0,column=0,sticky="w")
        ctk.CTkLabel(top, text="v"+VERSION, font=ctk.CTkFont(size=11), text_color=MUTED).grid(row=0,column=1,sticky="e")
        self.lang_btn = ctk.CTkButton(top, text="EN", width=36, height=24, command=self._toggle_lang,
            fg_color="transparent", border_width=1, text_color=("#333","#ccc"), font=ctk.CTkFont(size=11))
        self.lang_btn.grid(row=0, column=2, padx=(4,0))
        sc = ctk.CTkFrame(self, corner_radius=10, fg_color=CARD_BG, border_width=1)
        sc.grid(row=1, column=0, sticky="ew", padx=20, pady=4)
        sc.grid_columnconfigure(2, weight=1)
        self.dot = ctk.CTkLabel(sc, text="\u25cf", font=ctk.CTkFont(size=18), text_color="#666", width=20)
        self.dot.grid(row=0, column=0, padx=(14,4), pady=10)
        self.status_lbl = ctk.CTkLabel(sc, text=self._L("disconnected"), font=ctk.CTkFont(size=13,weight="bold"))
        self.status_lbl.grid(row=0, column=1, sticky="w", pady=10)
        self.model_lbl = ctk.CTkLabel(sc, text="", font=ctk.CTkFont(size=11), text_color=MUTED)
        self.model_lbl.grid(row=0, column=2, sticky="e", padx=(0,14), pady=10)
        cfg = ctk.CTkFrame(self, corner_radius=10, fg_color=CARD_BG, border_width=1)
        cfg.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        cfg.grid_columnconfigure(0, weight=1)
        r0 = ctk.CTkFrame(cfg, fg_color="transparent")
        r0.pack(fill="x", padx=14, pady=(12,4))
        self.l_provider = ctk.CTkLabel(r0, text=self._L("provider"), width=60, anchor="w", text_color=MUTED)
        self.l_provider.pack(side="left")
        self.provider_menu = ctk.CTkOptionMenu(r0, values=[], command=self._on_provider_change, dynamic_resizing=False)
        self.provider_menu.pack(side="left", padx=(0,6), fill="x", expand=True)
        r1 = ctk.CTkFrame(cfg, fg_color="transparent")
        r1.pack(fill="x", padx=14, pady=4)
        self.l_model = ctk.CTkLabel(r1, text=self._L("model"), width=60, anchor="w", text_color=MUTED)
        self.l_model.pack(side="left")
        self.model_menu = ctk.CTkOptionMenu(r1, values=[], dynamic_resizing=False)
        self.model_menu.pack(side="left", padx=(0,6), fill="x", expand=True)
        r2 = ctk.CTkFrame(cfg, fg_color="transparent")
        r2.pack(fill="x", padx=14, pady=4)
        self.l_apikey = ctk.CTkLabel(r2, text=self._L("api_key"), width=60, anchor="w", text_color=MUTED)
        self.l_apikey.pack(side="left")
        self.key_var = ctk.StringVar()
        self.key_entry = ctk.CTkEntry(r2, textvariable=self.key_var, placeholder_text=self._L("paste_key"), show="*")
        self.key_entry.pack(side="left", fill="x", expand=True)
        self.show_btn = ctk.CTkButton(r2, text=self._L("show"), width=52, height=28, command=self._toggle_key,
            fg_color="transparent", border_width=1, text_color=("#333","#ccc"))
        self.show_btn.pack(side="left", padx=(4,0))
        r3 = ctk.CTkFrame(cfg, fg_color="transparent")
        r3.pack(fill="x", padx=14, pady=(4,12))
        self.key_url_lbl = ctk.CTkLabel(r3, text=self._L("get_key"), text_color=ACCENT, font=ctk.CTkFont(size=11,underline=True), cursor="hand2")
        self.key_url_lbl.pack(side="left")
        self.key_url_lbl.bind("<Button-1>", lambda e: self._open_key_url())
        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.grid(row=3, column=0, sticky="ew", padx=20, pady=4)
        bf.grid_columnconfigure((0,1), weight=1)
        self.start_btn = ctk.CTkButton(bf, text=self._L("start"), command=self._start, fg_color=ACCENT,
            hover_color="#2563eb", height=36, font=ctk.CTkFont(size=14,weight="bold"))
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0,4))
        self.stop_btn = ctk.CTkButton(bf, text=self._L("stop"), command=self._stop, fg_color=RED,
            hover_color="#c43838", height=36, font=ctk.CTkFont(size=14,weight="bold"), state="disabled")
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(4,0))
        lc = ctk.CTkFrame(self, corner_radius=10, fg_color=CARD_BG, border_width=1)
        lc.grid(row=4, rowspan=2, column=0, sticky="nsew", padx=20, pady=4)
        lc.grid_columnconfigure(0, weight=1)
        lc.grid_rowconfigure(1, weight=1)
        lh = ctk.CTkFrame(lc, fg_color="transparent")
        lh.grid(row=0, column=0, sticky="ew", padx=14, pady=(10,4))
        lh.grid_columnconfigure(0, weight=1)
        self.l_log = ctk.CTkLabel(lh, text=self._L("log"), font=ctk.CTkFont(size=12,weight="bold"), text_color=MUTED)
        self.l_log.grid(row=0, column=0, sticky="w")
        self.log_text = ctk.CTkTextbox(lc, font=ctk.CTkFont(size=11), fg_color="#060a14", text_color="#8a93b0", state="disabled")
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0,10))
    def _toggle_lang(self):
        self._lang = "en" if self._lang == "zh" else "zh"
        self._apply_lang()
    def _apply_lang(self):
        self.status_lbl.configure(text=self._L("disconnected"))
        self.l_provider.configure(text=self._L("provider"))
        self.l_model.configure(text=self._L("model"))
        self.l_apikey.configure(text=self._L("api_key"))
        self.key_url_lbl.configure(text=self._L("get_key"))
        self.key_entry.configure(placeholder_text=self._L("paste_key"))
        self.show_btn.configure(text=self._L("show"))
        self.start_btn.configure(text=self._L("start"))
        self.stop_btn.configure(text=self._L("stop"))
        self.l_log.configure(text=self._L("log"))
        self.lang_btn.configure(text="EN" if self._lang == "zh" else "中")
    def _toggle_key(self):
        self._show_key = not self._show_key
        self.key_entry.configure(show="" if self._show_key else "*")
        self.show_btn.configure(text=self._L("hide") if self._show_key else self._L("show"))
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
            self.key_url_lbl.configure(text=self._L("get_key") + " (" + prov["label"] + ")")
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
            self._log(self._L("err_key_required"))
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
                self._log(self._L("err_unknown_provider"))
                return
            self._current_upstream = prov["upstream"]
            core.save_provider_key(pid, api_key)
        self._current_model = model
        try:
            core.write_adapter_config(self._current_upstream, model, api_key)
            core.backup_config_toml()
            core.apply_codex_config(model)
            if self.runner.start():
                self._running = True
                self.start_btn.configure(state="disabled")
                self.stop_btn.configure(state="normal")
                self._update_status(True, model + " via " + label)
                self._log(self._L("started") + ": " + model + " via " + label)
            else:
                self._log(self._L("err_start_failed"))
        except Exception as e:
            self._log(self._L("err_start_failed") + ": " + str(e))
    def _stop(self):
        try:
            msg = core.restore_openai()
            self._log(msg)
        except Exception as e:
            self._log("Restore warning: " + str(e))
        self.runner.stop()
        self._running = False
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self._update_status(False)
        self._log(self._L("stopped"))
    def _on_close(self):
        if self._running:
            self.minimize_to_tray()
        else:
            self._do_quit()
    def minimize_to_tray(self):
        self.withdraw()
        self._create_tray()
        self._log(self._L("minimized"))
    def _create_tray(self):
        try:
            import pystray
            from PIL import Image
            icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.png")
            if os.path.exists(icon_path):
                img = Image.open(icon_path)
            else:
                from PIL import ImageDraw
                img = Image.new("RGBA", (64, 64), (8, 12, 24, 255))
                draw = ImageDraw.Draw(img)
                draw.ellipse([8, 8, 56, 56], fill=(59, 130, 246, 255))
                draw.text((20, 18), "D", fill=(147, 197, 253, 255))
            menu = pystray.Menu(
                pystray.MenuItem(self._L("tray_show"), self._show_window, default=True),
                pystray.MenuItem(self._L("tray_exit"), self._quit_app),
            )
            self._tray_icon = pystray.Icon("dubhe-switch", img, "Dubhe AI Switch", menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
        except ImportError:
            self._log("pystray not installed - tray icon unavailable")
    def _show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()
        try:
            if self._tray_icon:
                self._tray_icon.stop()
                self._tray_icon = None
        except: pass
    def _quit_app(self):
        try:
            if self._running:
                self.runner.stop()
        except: pass
        try:
            if self._tray_icon:
                self._tray_icon.stop()
                self._tray_icon = None
        except: pass
        self.after(50, self._do_quit)
    def _do_quit(self):
        try:
            self.withdraw()
            self.destroy()
        except: pass
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
            self.status_lbl.configure(text=self._L("connected"))
            self.model_lbl.configure(text=info)
        else:
            self.dot.configure(text_color="#666")
            self.status_lbl.configure(text=self._L("disconnected"))
            self.model_lbl.configure(text="")
    def _check_adapter_status(self):
        if core.adapter_running():
            self._update_status(True, self._L("adapter_running"))
        self.after(5000, self._check_adapter_status)
