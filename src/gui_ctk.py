"""Dubhe AI Switch — OpenAI-compatible provider switcher."""
import platform
import queue
import threading
import webbrowser
from tkinter import messagebox

import customtkinter as ctk
import pystray
from PIL import Image, ImageDraw

import core

APP_TITLE = "Dubhe AI Switch"

_SYSTEM = platform.system()
MONO_FONT = "Menlo" if _SYSTEM == "Darwin" else ("Consolas" if _SYSTEM == "Windows" else "Monospace")

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Dubhe brand
ACCENT = "#3b82f6"
ACCENT_HOVER = "#1d4ed8"
DANGER = "#ef4444"
DANGER_HOVER = "#dc2626"
MUTED = "#94a3b8"
LINK = "#93c5fd"
BG = "#080c18"
SURFACE = "#0f172a"

# 托盘图标尺寸
ICON_SIZE = 64


def _create_tray_image():
    """加载托盘图标（优先真实图标，回退蓝色方块）。"""
    import os, sys
    for base_dir in [
        getattr(sys, '_MEIPASS', ''),
        os.path.dirname(os.path.abspath(__file__)),
    ]:
        for sub in ['assets', '..']:
            path = os.path.join(base_dir, sub, 'icon.png')
            if os.path.exists(path):
                try:
                    from PIL import Image as PILImage
                    return PILImage.open(path).resize((ICON_SIZE, ICON_SIZE), PILImage.LANCZOS)
                except Exception:
                    pass
    # 回退：纯色方块
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([4, 4, 60, 60], radius=14, fill=ACCENT)
    return img


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("640x720")
        self.minsize(560, 520)
        self.protocol("WM_DELETE_WINDOW", self._on_close_window)
        self._set_window_icon()

        self.runner = core.AdapterRunner(log_fn=self._enqueue_log)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.tray_queue: queue.Queue[str] = queue.Queue()
        self.show_key_var = ctk.BooleanVar(value=False)
        self.log_expanded = True
        self._busy = False
        self._quitting = False
        self._tray_icon: pystray.Icon | None = None

        self.flat: list[tuple[str, str, str]] = []
        self.label_to_meta: dict[str, tuple[str, str]] = {}
        self.labels: list[str] = []

        self.model_label_var = ctk.StringVar()
        self.key_var = ctk.StringVar()
        self._current_route: str = ""
        self._key_url: str = ""

        self._build_ui()
        self._reload_providers()
        self._pump_log()
        self._pump_tray()
        self._refresh_status()

    def _set_window_icon(self):
        """设置窗口图标（任务栏 + 标题栏）。"""
        import os, sys
        for base_dir in [
            getattr(sys, '_MEIPASS', ''),
            os.path.dirname(os.path.abspath(__file__)),
        ]:
            for sub in ['assets', '..']:
                path = os.path.join(base_dir, sub, 'icon.ico')
                if os.path.exists(path):
                    try:
                        self.iconbitmap(path)
                        return
                    except Exception:
                        pass

    # ---------- UI ----------

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # ===== row 0: 顶部标题 =====
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 6))
        top.grid_columnconfigure(0, weight=1)
        # Brand: Dubhe icon + title
        img_frame = ctk.CTkFrame(top, fg_color="transparent")
        img_frame.grid(row=0, column=0, sticky="w")
        try:
            import os, sys
            png = None
            base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
            for candidate in [
                os.path.join(base, 'assets', 'icon.png'),
                os.path.join(base, '..', 'assets', 'icon.png'),
            ]:
                if os.path.exists(candidate):
                    png = candidate
                    break
            if png:
                from PIL import Image as PILImage
                from customtkinter import CTkImage
                img = CTkImage(light_image=PILImage.open(png), dark_image=PILImage.open(png), size=(26, 26))
                ctk.CTkLabel(img_frame, image=img, text="").pack(side="left", padx=(0, 8))
        except Exception:
            pass
        ctk.CTkLabel(img_frame, text="Dubhe", font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#ffffff").pack(side="left")
        ctk.CTkLabel(img_frame, text=" AI", font=ctk.CTkFont(size=20, weight="bold"),
            text_color=ACCENT).pack(side="left")
        ctk.CTkLabel(top, text="v1.3", font=ctk.CTkFont(size=11),
            text_color=MUTED).grid(row=0, column=1, sticky="e")

        # ===== row 1: 状态卡 =====
        status = ctk.CTkFrame(self, corner_radius=10)
        status.grid(row=1, column=0, sticky="ew", padx=20, pady=4)
        status.grid_columnconfigure(2, weight=1)
        self.adapter_dot = ctk.CTkLabel(
            status, text="●", font=ctk.CTkFont(size=20),
            text_color="#999999", width=24,
        )
        self.adapter_dot.grid(row=0, column=0, padx=(14, 4), pady=12)
        self.adapter_status_label = ctk.CTkLabel(
            status, text="未启动",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.adapter_status_label.grid(row=0, column=1, sticky="w", pady=12)
        self.codex_status_label = ctk.CTkLabel(
            status, text="Codex: ?",
            font=ctk.CTkFont(size=12), text_color=MUTED,
        )
        self.codex_status_label.grid(row=0, column=2, sticky="e", padx=(0, 14), pady=12)

        # ===== row 2: 配置卡(提供商 + 模型 + Key) =====
        cfg = ctk.CTkFrame(self, corner_radius=10)
        cfg.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        cfg.grid_columnconfigure(0, weight=1)

        # 提供商选择行
        self.providers = []
        self.provider_models = {}
        self.provider_var = ctk.StringVar()
        row_prov = ctk.CTkFrame(cfg, fg_color="transparent")
        row_prov.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(row_prov, text="提供商", width=56, anchor="w").pack(side="left")
        self.provider_menu = ctk.CTkOptionMenu(
            row_prov, variable=self.provider_var, values=[],
            command=self._on_provider_change, dynamic_resizing=False,
        )
        self.provider_menu.pack(side="left", fill="x", expand=True)

        # 模型选择行
        row_model = ctk.CTkFrame(cfg, fg_color="transparent")
        row_model.pack(fill="x", padx=14, pady=2)
        ctk.CTkLabel(row_model, text="模型", width=56, anchor="w").pack(side="left")
        self.model_menu = ctk.CTkOptionMenu(
            row_model, variable=self.model_label_var, values=[],
            command=self._on_model_change, dynamic_resizing=False,
        )
        self.model_menu.pack(side="left", padx=(0, 6), fill="x", expand=True)
        ctk.CTkButton(
            row_model, text="自定义", width=60, height=28,
            command=self._open_custom_dialog,
        ).pack(side="left", padx=2)

        # 拿 Key 链接
        self.key_url_link = ctk.CTkLabel(
            cfg, text="", text_color=LINK,
            font=ctk.CTkFont(size=11, underline=True), cursor="hand2",
        )
        self.key_url_link.pack(anchor="w", padx=(78, 14), pady=(0, 2))
        self.key_url_link.bind("<Button-1>", self._open_key_url)

        # 自定义 Key 输入行
        row_key = ctk.CTkFrame(cfg, fg_color="transparent")
        row_key.pack(fill="x", padx=14, pady=(4, 14))
        ctk.CTkLabel(row_key, text="自定义", width=56, anchor="w").pack(side="left")
        self.key_entry = ctk.CTkEntry(
            row_key, textvariable=self.key_var, show="●",
            placeholder_text="粘贴 sk-... 字符串",
        )
        self.key_entry.pack(side="left", padx=(0, 8), fill="x", expand=True)
        ctk.CTkCheckBox(
            row_key, text="记住 Key", variable=self.show_key_var,
            command=self._toggle_key, width=20,
        ).pack(side="left")

        # ===== row 3: 主按钮 =====
        self.main_btn = ctk.CTkButton(
            self, text="▶  启动",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=48, corner_radius=10,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._on_main_button,
        )
        self.main_btn.grid(row=3, column=0, sticky="ew", padx=20, pady=(10, 2))

        # ===== row 5: 日志头 =====
        self.log_header = ctk.CTkButton(
            self, text="▼  日志", anchor="w",
            font=ctk.CTkFont(size=12),
            fg_color="transparent", text_color=MUTED,
            hover_color=("#eee", "#2a2a2a"), height=28,
            command=self._toggle_log,
        )
        self.log_header.grid(row=5, column=0, sticky="ew", padx=20, pady=(2, 0))

        # ===== row 6: 日志卡 =====
        self.log_card = ctk.CTkFrame(self, corner_radius=10)
        self.log_card.grid_columnconfigure(0, weight=1)
        self.log_card.grid_rowconfigure(0, weight=1)
        self.log_card.grid(row=6, column=0, sticky="nsew", padx=20, pady=(4, 14))
        self.grid_rowconfigure(6, weight=1)
        self.log = ctk.CTkTextbox(
            self.log_card, wrap="word",
            font=ctk.CTkFont(family=MONO_FONT, size=11),
            state="disabled", corner_radius=6,
        )
        self.log.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        self._log("准备就绪。选提供商 → 选模型 → 输入 Key → 点蓝色按钮。关闭窗口隐藏到托盘。")

    def _toggle_key(self):
        self.key_entry.configure(show="" if self.show_key_var.get() else "●")

    def _toggle_log(self):
        if self.log_expanded:
            self.log_card.grid_remove()
            self.log_header.configure(text="▶  日志")
            self.grid_rowconfigure(6, weight=0)
            self.log_expanded = False
            w = self.winfo_width()
            self.geometry(f"{w}x500")
        else:
            self.log_card.grid(row=6, column=0, sticky="nsew", padx=20, pady=(4, 14))
            self.log_header.configure(text="▼  日志")
            self.grid_rowconfigure(6, weight=1)
            self.log_expanded = True
            w = self.winfo_width()
            self.geometry(f"{w}x720")

    # ---------- 提供商 / 模型数据 ----------

    def _reload_providers(self):
        prov_map = {}
        for pid, info in core.PROVIDERS.items():
            label = info["label"]
            prov_map[label] = [(f"{m}", m, pid) for m in info["models"]]
        # 自定义条目不覆盖内置提供商（只展示独一无二的标签）
        for idx, it in enumerate(core.load_custom()):
            label = it["label"]
            if label not in prov_map:
                prov_map[label] = [(it["model"], it["model"], f"custom:{idx}")]
        self.providers = list(prov_map.keys())
        self.provider_models = prov_map
        self.provider_menu.configure(values=self.providers)
        cur_model = core.current_model()
        target = None
        for p, models in prov_map.items():
            for _, mk, _ in models:
                if mk == cur_model:
                    target = p
        if not target and self.providers:
            target = self.providers[0]
        if target:
            self.provider_var.set(target)
            self._on_provider_change(target, initial=True)

    def _on_provider_change(self, provider_label, initial=False):
        models = self.provider_models.get(provider_label, [])
        if not models:
            return
        labels = [lab for lab, _, _ in models]
        self.model_menu.configure(values=labels)
        self.model_label_var.set(labels[0])
        self.label_to_meta = {lab: (m, rt) for lab, m, rt in models}
        if not initial:
            self._on_model_change(labels[0])

    def _route_of_label(self, label: str) -> str:
        return self.label_to_meta[label][1]

    def _model_of_label(self, label: str) -> str:
        return self.label_to_meta[label][0]

    def _on_model_change(self, _selected: str | None = None):
        old_key = self.key_var.get().strip()
        if old_key and self._current_route:
            self._save_current_key(old_key)
        self._refresh_provider_ui()

    def _save_current_key(self, key: str):
        if self._current_route.startswith("custom:"):
            idx = int(self._current_route[7:])
            core.update_custom_key(idx, key)
        else:
            core.save_key(self._current_route, key)

    def _refresh_provider_ui(self, initial: bool = False):
        label = self.model_label_var.get()
        if not label:
            return
        route = self._route_of_label(label)
        self._current_route = route
        try:
            info = core.resolve_route(route, self._model_of_label(label))
        except Exception as e:
            self._log(f"路由错误: {e}")
            return
        url = info["key_url"] or ""
        self._key_url = url
        self.key_url_link.configure(text=f"拿 Key: {url}" if url else "")
        self.key_var.set(info["api_key"])
        if not initial:
            self._log(f"已切到 {label}。Key 已从本地加载。")
        if hasattr(self, "main_btn"):
            self._refresh_main_button()

    def _open_key_url(self, _evt=None):
        if self._key_url and self._key_url.startswith("http"):
            webbrowser.open(self._key_url)

    # ---------- 弹窗 ----------

    def _open_custom_dialog(self):
        CustomDialog(self, on_saved=self._on_custom_saved)

    def _on_custom_saved(self):
        self._reload_providers()
        self._log("自定义条目已保存。")

    # ---------- 主按钮（后台线程，不卡 UI）----------

    def _on_main_button(self):
        if self._busy:
            return
        if core.adapter_running():
            self._stop_adapter()
        else:
            self._start_adapter()

    def _set_busy(self, text: str):
        self._busy = True
        self.main_btn.configure(text=text, state="disabled")

    def _start_adapter(self):
        label = self.model_label_var.get()
        if not label:
            return
        key = self.key_var.get().strip()
        if not key:
            messagebox.showwarning(APP_TITLE, "请先输入 Key。")
            return
        self._save_current_key(key)
        self._set_busy("⏳  启动中…")
        model = self._model_of_label(label)
        route = self._route_of_label(label)
        # 后台线程执行，不阻塞 UI
        threading.Thread(
            target=self._bg_start, args=(model, route, label),
            daemon=True,
        ).start()

    def _bg_start(self, model: str, route: str, label: str):
        """后台线程执行启动流程。"""
        try:
            core.write_adapter_json(model, route)
            self._bg_log(f"已写入翻译官配置（{label}）。")
            if core.backup_config_toml_if_needed():
                self._bg_log(f"已备份原 Codex 配置 → {core.BACKUP_TOML.name}")
            core.apply_codex_config(model)
            self._bg_log("已合并配置到 config.toml。")
        except Exception as e:
            self._bg_log(f"配置写入失败：{e}")
            self._bg_error("配置写入失败", str(e))
            self._bg_done()
            return

        if not self.runner.start():
            self._bg_error("翻译官启动失败", "翻译官启动失败，看日志。")
            self._bg_done()
            return

        self._bg_log("✅ 全部就绪。打开 Codex App 即可使用。")
        self._bg_done()

    def _stop_adapter(self):
        self._set_busy("⏳  停止并切回中…")
        threading.Thread(target=self._bg_stop, daemon=True).start()

    def _bg_stop(self):
        """后台线程执行停止流程。"""
        self.runner.stop()
        try:
            msg = core.restore_openai_config()
            self._bg_log(msg)
        except Exception as e:
            self._bg_log(f"还原 Codex 配置失败：{e}")
            self._bg_error("还原配置失败", str(e))
            self._bg_done()
            return
        self._bg_log("✅ 已停翻译官 + 切回 OpenAI 原版。重启 Codex App 生效。")
        self._bg_done()

    # ---------- 后台线程→主线程安全回调 ----------

    def _bg_log(self, msg: str):
        self.after(0, lambda: self._log(msg))

    def _bg_error(self, title: str, msg: str):
        self.after(0, lambda: messagebox.showerror(title, msg))

    def _bg_done(self):
        def _done():
            self._busy = False
            self._refresh_status()
        self.after(0, _done)

    def _refresh_main_button(self):
        if self._busy:
            return
        running = core.adapter_running()
        label = self.model_label_var.get()
        target = self._model_of_label(label) if label else "?"
        if running:
            self.main_btn.configure(
                text=f"⏹  停止并切回 OpenAI  (当前 {target})",
                fg_color="transparent",
                border_width=2,
                border_color="#2ecc71",
                text_color="#2ecc71",
                hover_color=("#e8f5e9", "#1a3320"),
                state="normal",
            )
        else:
            self.main_btn.configure(
                text=f"▶  启动 + 切到 {target}",
                fg_color=ACCENT,
                border_width=0,
                text_color="white",
                hover_color=ACCENT_HOVER,
                state="normal",
            )

    # ---------- 状态轮询 ----------

    def _refresh_status(self):
        if self._busy:
            self.after(800, self._refresh_status)
            return
        running = core.adapter_running()
        cur_model = core.current_model()
        codex_in_adapter = core.codex_in_adapter_mode()

        if running:
            self.adapter_dot.configure(text_color="#2ecc71")
            self.adapter_status_label.configure(text="运行中")
        else:
            self.adapter_dot.configure(text_color="#999999")
            self.adapter_status_label.configure(text="未启动")
        if codex_in_adapter and cur_model:
            self.codex_status_label.configure(text=f"Codex: {cur_model}")
        elif cur_model:
            self.codex_status_label.configure(text=f"Codex: OpenAI 原版")
        else:
            self.codex_status_label.configure(text="Codex: 未初始化")

        self._refresh_main_button()
        self.after(2000, self._refresh_status)

    # ---------- 日志 ----------

    def _enqueue_log(self, msg: str):
        self.log_queue.put(msg)

    def _log(self, msg: str):
        self.log_queue.put(msg)

    def _pump_log(self):
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log.configure(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.after(150, self._pump_log)

    # ---------- 托盘队列轮询 ----------

    def _pump_tray(self):
        while True:
            try:
                msg = self.tray_queue.get_nowait()
            except queue.Empty:
                break
            if msg == "show":
                self.deiconify()
                self.lift()
                self.focus_force()
            elif msg == "quit":
                self._do_full_quit()
        self.after(200, self._pump_tray)

    # ---------- 关闭 → 隐藏到托盘 ----------

    def _on_close_window(self):
        """点 X → 隐藏到系统托盘。"""
        try:
            k = self.key_var.get().strip()
            if k and self._current_route:
                self._save_current_key(k)
        except Exception:
            pass
        self.withdraw()
        self._start_tray()

    def _start_tray(self):
        if self._tray_icon is not None:
            return
        image = _create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("显示 Dubhe AI Switch", self._on_tray_show, default=True),
            pystray.MenuItem("退出", self._on_tray_quit),
        )
        self._tray_icon = pystray.Icon(
            "dubhe-ai-switch", image, "Dubhe AI Switch", menu,
        )
        threading.Thread(target=self._tray_icon.run, daemon=True).start()
        self._log("已隐藏到系统托盘。双击或右键托盘图标可显示/退出。")

    def _on_tray_show(self, icon: pystray.Icon):
        icon.stop()
        self._tray_icon = None
        self.tray_queue.put("show")

    def _on_tray_quit(self, icon: pystray.Icon):
        icon.stop()
        self._tray_icon = None
        self.tray_queue.put("quit")

    def _do_full_quit(self):
        self._quitting = True
        try:
            k = self.key_var.get().strip()
            if k and self._current_route:
                self._save_current_key(k)
        except Exception:
            pass
        def _stop_and_destroy():
            try:
                self.runner.stop()
            except Exception:
                pass
        threading.Thread(target=_stop_and_destroy, daemon=True).start()
        self.destroy()


# ====================================================================

class CustomDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_saved):
        super().__init__(parent)
        self.parent = parent
        self.on_saved = on_saved
        self.title("添加自定义模型")
        self.geometry("460x300")
        self.resizable(False, False)
        self.transient(parent)
        self.after(50, self.grab_set)

        self.model_var = ctk.StringVar()
        self.upstream_var = ctk.StringVar()
        self.api_key_var = ctk.StringVar()

        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="添加自定义模型提供商",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(
            self, text="填入模型 ID、API 端点地址和你的 API Key 即可。",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(0, 10))

        self._field("模型 ID", self.model_var, 2, "例：glm-4.7 / kimi-k2.6（发给 API 的字符串）")
        self._field("Base URL", self.upstream_var, 3, "完整端点，必须含 /chat/completions")
        self._field("API Key", self.api_key_var, 4, "sk-... 类型", show="●")

        btnf = ctk.CTkFrame(self, fg_color="transparent")
        btnf.grid(row=5, column=0, sticky="ew", padx=20, pady=(16, 16))
        btnf.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            btnf, text="取消", command=self.destroy,
            fg_color="transparent", border_width=1,
            text_color=("#333", "#ccc"), hover_color=("#eee", "#333"),
            width=100,
        ).grid(row=0, column=1, padx=4)
        ctk.CTkButton(
            btnf, text="保存", command=self._save,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, width=100,
        ).grid(row=0, column=2, padx=4)

    def _field(self, label, var, row, hint, show=None):
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.grid(row=row, column=0, sticky="ew", padx=20, pady=2)
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f, text=label, width=80, anchor="w").grid(row=0, column=0)
        entry = ctk.CTkEntry(f, textvariable=var, placeholder_text=hint)
        if show:
            entry.configure(show=show)
        entry.grid(row=0, column=1, sticky="ew")

    def _save(self):
        model = self.model_var.get().strip()
        upstream = self.upstream_var.get().strip()
        api_key = self.api_key_var.get().strip()
        missing = [n for n, v in (("模型 ID", model), ("Base URL", upstream), ("API Key", api_key))
                   if not v]
        if missing:
            messagebox.showwarning("缺字段", "以下字段必填：\n  " + "\n  ".join(missing))
            return
        if not upstream.startswith(("http://", "https://")):
            messagebox.showwarning("Base URL 格式", "Base URL 必须以 http:// 或 https:// 开头")
            return
        try:
            core.add_custom(model, upstream, api_key)
            self.on_saved()
            self.destroy()
        except Exception as e:
            messagebox.showerror("保存失败", str(e))


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
