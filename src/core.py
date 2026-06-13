"""core logic: config + adapter + multi-provider routing."""
import json, os, shutil, socket, threading, time, urllib.request, urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
import tomlkit
import adapter

HOME = Path(os.path.expanduser("~"))
CC_SWITCH_DIR = HOME / ".cc-switch"
CODEX_DIR = HOME / ".codex"
CONFIG_TOML = CODEX_DIR / "config.toml"
BACKUP_TOML = CODEX_DIR / "config.toml.openai-backup"
ADAPTER_JSON = CC_SWITCH_DIR / "dubhe-switch-config.json"
KEYS_JSON = CC_SWITCH_DIR / "dubhe-switch-keys.json"
CUSTOM_JSON = CC_SWITCH_DIR / "dubhe-switch-providers.json"

ADAPTER_HOST = "127.0.0.1"
ADAPTER_PORT = 18667
HEALTH_URL = f"http://{ADAPTER_HOST}:{ADAPTER_PORT}/health"

PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek",
        "upstream": "https://api.deepseek.com/chat/completions",
        "key_url": "https://platform.deepseek.com",
        "models": ["deepseek-v4-pro", "deepseek-v4-flash"],
    },
    "kimi": {
        "label": "Kimi",
        "upstream": "https://api.moonshot.ai/v1/chat/completions",
        "key_url": "https://platform.kimi.ai",
        "models": ["kimi-k2.6", "kimi-k2.5"],
    },
    "zhipu": {
        "label": "Zhipu GLM",
        "upstream": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "key_url": "https://open.bigmodel.cn",
        "models": ["glm-4.7", "glm-4.7-flash"],
    },
    "qwen": {
        "label": "Qwen (Tongyi)",
        "upstream": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "key_url": "https://dashscope.console.aliyun.com",
        "models": ["qwen-plus", "qwen-flash"],
    },
    "xiaomi": {
        "label": "Xiaomi MiMo",
        "upstream": "https://api.xiaomimimo.com/v1/chat/completions",
        "key_url": "https://platform.xiaomimimo.com",
        "models": ["mimo-v2.5", "mimo-v2.5-pro"],
    },
    "minimax": {
        "label": "MiniMax",
        "upstream": "https://api.minimax.io/v1/chat/completions",
        "key_url": "https://platform.minimax.io",
        "models": ["MiniMax-M2.7", "MiniMax-M2.5"],
    },
}

def load_custom() -> list:
    if not CUSTOM_JSON.exists(): return []
    try:
        data = json.loads(CUSTOM_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception: return []

def save_custom_list(items: list):
    ensure_dirs()
    CUSTOM_JSON.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

def add_custom(model: str, upstream: str, api_key: str):
    items = load_custom()
    items.append({"label": model.strip(), "model": model.strip(),
                  "upstream": upstream.strip(), "key_url": "", "api_key": api_key.strip()})
    save_custom_list(items)

def remove_custom(index: int):
    items = load_custom()
    if 0 <= index < len(items): items.pop(index); save_custom_list(items)

def update_custom_key(index: int, api_key: str):
    items = load_custom()
    if 0 <= index < len(items): items[index]["api_key"] = api_key.strip(); save_custom_list(items)

def resolve_route(route_type: str, model: str) -> dict:
    if route_type.startswith("custom:"):
        idx = int(route_type[7:])
        items = load_custom()
        if idx >= len(items): raise ValueError(f"custom entry {idx} not found")
        it = items[idx]
        return {"label": it["label"], "upstream": it["upstream"], "key_url": it.get("key_url", ""), "api_key": it.get("api_key", "")}
    if route_type not in PROVIDERS: raise ValueError(f"unknown provider: {route_type}")
    info = PROVIDERS[route_type]
    return {"label": info["label"], "upstream": info["upstream"], "key_url": info["key_url"], "api_key": load_key(route_type)}

def flat_models() -> list:
    out = []
    for pid, info in PROVIDERS.items():
        for m in info["models"]:
            out.append((f"{info['label']} / {m}", m, pid))
    for idx, it in enumerate(load_custom()):
        out.append((f"{it['label']} / {it['model']} +", it["model"], f"custom:{idx}"))
    return out

def adapter_running() -> bool:
    try:
        with socket.create_connection((ADAPTER_HOST, ADAPTER_PORT), timeout=0.1): return True
    except OSError: return False

def codex_in_adapter_mode() -> bool:
    if not CONFIG_TOML.exists(): return False
    try:
        doc = tomlkit.parse(CONFIG_TOML.read_text(encoding="utf-8"))
    except Exception: return False
    return doc.get("model_provider") == "stepfun_codex_adapter"

def current_model() -> str | None:
    if not CONFIG_TOML.exists(): return None
    try:
        doc = tomlkit.parse(CONFIG_TOML.read_text(encoding="utf-8"))
    except Exception: return None
    m = doc.get("model")
    return str(m) if m else None

def ensure_dirs():
    CC_SWITCH_DIR.mkdir(parents=True, exist_ok=True)
    CODEX_DIR.mkdir(parents=True, exist_ok=True)

def _load_keys_dict() -> dict:
    if KEYS_JSON.exists():
        try: return json.loads(KEYS_JSON.read_text(encoding="utf-8"))
        except Exception: pass
    # Migrate from old config filenames
    for old_name in ("switcher-keys.json", "stepfun-codex-adapter-config.json"):
        old_file = CC_SWITCH_DIR / old_name
        if old_file.exists():
            try:
                data = json.loads(old_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data:
                    KEYS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    return data
            except Exception: pass
    return {}

def load_key(provider: str) -> str:
    return _load_keys_dict().get(provider, "")

def save_key(provider: str, key: str):
    ensure_dirs()
    d = _load_keys_dict()
    d[provider] = key
    KEYS_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

CODEX_TOML_FIELDS = {"model_provider": "stepfun_codex_adapter", "model_reasoning_effort": "high", "disable_response_storage": True}

PROVIDER_BLOCK = {"name": "StepFun Codex Adapter", "base_url": f"http://{ADAPTER_HOST}:{ADAPTER_PORT}/v1",
                  "wire_api": "responses", "requires_openai_auth": False,
                  "request_max_retries": 2, "stream_max_retries": 2, "stream_idle_timeout_ms": 300000}

def write_adapter_json(model: str, route_type: str):
    ensure_dirs()
    route = resolve_route(route_type, model)
    if not route["api_key"]: raise ValueError(f"API Key not set for {route['label']}")
    if not route["upstream"]: raise ValueError(f"Base URL not set for {route['label']}")
    ADAPTER_JSON.write_text(json.dumps({"subscription": "normal", "model": model,
        "upstream": route["upstream"], "api_key": route["api_key"]}, ensure_ascii=False, indent=2), encoding="utf-8")

def backup_config_toml_if_needed() -> bool:
    if not CONFIG_TOML.exists() or BACKUP_TOML.exists(): return False
    shutil.copy2(CONFIG_TOML, BACKUP_TOML)
    return True

def apply_codex_config(model: str):
    ensure_dirs()
    doc = tomlkit.parse(CONFIG_TOML.read_text(encoding="utf-8")) if CONFIG_TOML.exists() else tomlkit.document()
    doc["model"] = model
    for k, v in CODEX_TOML_FIELDS.items(): doc[k] = v
    if "model_providers" not in doc: doc["model_providers"] = tomlkit.table()
    providers = doc["model_providers"]
    if "stepfun_codex_adapter" not in providers: providers["stepfun_codex_adapter"] = tomlkit.table()
    block = providers["stepfun_codex_adapter"]
    for k, v in PROVIDER_BLOCK.items(): block[k] = v
    block["name"] = model
    CONFIG_TOML.write_text(tomlkit.dumps(doc), encoding="utf-8")

def restore_openai_config() -> str:
    if not BACKUP_TOML.exists(): return "no backup found."
    shutil.copy2(BACKUP_TOML, CONFIG_TOML)
    return f"restored from {BACKUP_TOML.name}"

class AdapterRunner:
    def __init__(self, log_fn=None):
        self.httpd = None
        self.thread = None
        self.log = log_fn or (lambda msg: None)

    def start(self) -> bool:
        if self.thread and self.thread.is_alive():
            self.log("adapter already running.")
            return True
        try:
            self.httpd = ThreadingHTTPServer((adapter.HOST, adapter.PORT), adapter.Handler)
        except OSError as e:
            self.log(f"port {adapter.PORT} error: {e}")
            return False
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="adapter", daemon=True)
        self.thread.start()
        for _ in range(15):
            if adapter_running():
                self.log(f"adapter started: http://{adapter.HOST}:{adapter.PORT}")
                return True
            time.sleep(0.02)
        self.log("adapter start timeout.")
        return False

    def stop(self):
        if not self.httpd: return
        # Windows 上 shutdown() 可能阻塞。独立线程 + 超时防卡死。
        stopped = threading.Event()
        def _do_shutdown():
            try:
                self.httpd.socket.close()     # force-wake serve_forever
                self.httpd.shutdown()
            except Exception:
                pass
            try:
                self.httpd.server_close()
            except Exception:
                pass
            stopped.set()
        t = threading.Thread(target=_do_shutdown, daemon=True)
        t.start()
        if not stopped.wait(timeout=1.0):
            self.log("adapter stop timed out (skipping).")
        self.httpd = None
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None
        self.log("adapter stopped.")
