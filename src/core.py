"""核心逻辑：配置管理 + 翻译官启停 + 多 provider 路由。改自 codex-switch。"""
import json
import os
import shutil
import socket
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import tomlkit

import adapter

HOME = Path(os.path.expanduser("~"))
SWITCH_DIR = HOME / ".cc-switch"
CODEX_DIR = HOME / ".codex"
CONFIG_TOML = CODEX_DIR / "config.toml"
BACKUP_TOML = CODEX_DIR / "config.toml.openai-backup"

ADAPTER_JSON = SWITCH_DIR / "stepfun-codex-adapter-config.json"
KEYS_JSON = SWITCH_DIR / "switcher-keys.json"
CUSTOM_JSON = SWITCH_DIR / "switcher-custom-providers.json"

ADAPTER_HOST = "127.0.0.1"
ADAPTER_PORT = 18667
HEALTH_URL = f"http://{ADAPTER_HOST}:{ADAPTER_PORT}"

# Codex config.toml 固定字段
CODEX_TOML_FIELDS = {
    "proxy": "",
    "model": "stepfun_codex_adapter",
    "verbose": "false",
    "max_output": "256000",
    "allowed_tools": ["Bash", "Read", "Edit", "glob", "Grep", "FileEdit"],
    "model_providers": {
        "stepfun_codex_adapter": {
            "name": "deepseek-v4-flash",
            "provider": "openai",
            "api_base": f"http://{ADAPTER_HOST}:{ADAPTER_PORT}/v1",
        }
    },
}

# ---------- Provider 注册表 ----------
PROVIDERS: dict[str, dict] = {}

PRESETS = [
    {"label": "DeepSeek", "model": "deepseek-v4-flash",
     "upstream": "https://api.deepseek.com/chat/completions",
     "key_url": "https://platform.deepseek.com"},
    {"label": "智谱 (GLM)", "model": "glm-4-plus",
     "upstream": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
     "key_url": "https://open.bigmodel.cn"},
    {"label": "通义千问 (Qwen)", "model": "qwen-max",
     "upstream": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
     "key_url": "https://dashscope.console.aliyun.com"},
    {"label": "MiniMax", "model": "MiniMax-M3",
     "upstream": "https://api.minimax.chat/v1/chat/completions",
     "key_url": "https://platform.minimax.com"},
    {"label": "Kimi (Moonshot)", "model": "kimi-k2-0711-preview",
     "upstream": "https://api.moonshot.cn/v1/chat/completions",
     "key_url": "https://platform.kimi.com"},
    {"label": "DeepInfra", "model": "meta-llama/Llama-4-Maverick-17B-128E-Instruct",
     "upstream": "https://api.deepinfra.com/v1/openai/chat/completions",
     "key_url": "https://deepinfra.com"},
    {"label": "OpenRouter", "model": "openai/gpt-4o",
     "upstream": "https://openrouter.ai/api/v1/chat/completions",
     "key_url": "https://openrouter.ai/keys"},
    {"label": "Groq", "model": "llama-3.3-70b-versatile",
     "upstream": "https://api.groq.com/openai/v1/chat/completions",
     "key_url": "https://console.groq.com"},
    {"label": "Mistral AI", "model": "mistral-large-latest",
     "upstream": "https://api.mistral.ai/v1/chat/completions",
     "key_url": "https://console.mistral.ai"},
    {"label": "火山引擎 (豆包)", "model": "doubao-1-5-pro-32k",
     "upstream": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
     "key_url": "https://console.volcengine.com"},
    {"label": "零一万物 (Yi)", "model": "yi-large",
     "upstream": "https://api.lingyiwanwu.com/v1/chat/completions",
     "key_url": "https://platform.lingyiwanwu.com"},
    {"label": "百川智能", "model": "Baichuan4",
     "upstream": "https://api.baichuan-ai.com/v1/chat/completions",
     "key_url": "https://platform.baichuan-ai.com"},
    {"label": "阶跃星辰", "model": "step-2-16k",
     "upstream": "https://api.stepfun.com/v1/chat/completions",
     "key_url": "https://platform.stepfun.com"},
    {"label": "NVIDIA NIM", "model": "deepseek-ai/deepseek-v4-flash",
     "upstream": "https://integrate.api.nvidia.com/v1/chat/completions",
     "key_url": "https://build.nvidia.com"},
    {"label": "Together AI", "model": "mistralai/Mixtral-8x22B-Instruct-v0.1",
     "upstream": "https://api.together.xyz/v1/chat/completions",
     "key_url": "https://together.ai"},
    {"label": "自定义", "model": "", "upstream": "", "key_url": ""},
]

# ---------- 工具函数 ----------

def ensure_dirs():
    SWITCH_DIR.mkdir(parents=True, exist_ok=True)

def adapter_running() -> bool:
    try:
        s = socket.create_connection((ADAPTER_HOST, ADAPTER_PORT), timeout=1)
        s.close()
        return True
    except (OSError, socket.error):
        return False

def get_codex_model() -> str | None:
    if not CONFIG_TOML.exists():
        return None
    try:
        doc = tomlkit.parse(CONFIG_TOML.read_text(encoding="utf-8"))
        m = doc.get("model")
        return str(m) if m else None
    except Exception:
        return None

# ---------- 自定义提供商 ----------
def load_custom() -> list[dict]:
    if not CUSTOM_JSON.exists():
        return []
    try:
        data = json.loads(CUSTOM_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []

def save_custom_list(items: list[dict]):
    ensure_dirs()
    CUSTOM_JSON.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

def add_custom(label, model, upstream, key_url, api_key):
    items = load_custom()
    items.append({
        "label": label.strip(), "model": model.strip(),
        "upstream": upstream.strip(), "key_url": key_url.strip(),
        "api_key": api_key.strip(),
    })
    save_custom_list(items)

def remove_custom(index: int):
    items = load_custom()
    if 0 <= index < len(items):
        items.pop(index)
        save_custom_list(items)

# ---------- Key 管理 ----------
def get_saved_providers() -> dict[str, str]:
    """返回 {provider_id: api_key}"""
    ensure_dirs()
    if not KEYS_JSON.exists():
        # 兼容旧版迁移
        if ADAPTER_JSON.exists():
            try:
                old = json.loads(ADAPTER_JSON.read_text(encoding="utf-8"))
                k = old.get("api_key", "")
                if k:
                    save_provider_key("deepseek", k)
                    return {"deepseek": k}
            except Exception:
                pass
        return {}
    try:
        return json.loads(KEYS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_provider_key(provider_id: str, api_key: str):
    ensure_dirs()
    d = get_saved_providers()
    d[provider_id] = api_key
    KEYS_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def delete_provider_key(provider_id: str):
    d = get_saved_providers()
    d.pop(provider_id, None)
    KEYS_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------- Provider 注册（运行时加载）----------
def register_provider(pid: str, label: str, upstream: str, key_url: str, models: list[str]):
    PROVIDERS[pid] = {"label": label, "upstream": upstream, "key_url": key_url, "models": models}

def register_defaults():
    register_provider("deepseek", "DeepSeek", "https://api.deepseek.com/chat/completions",
                      "https://platform.deepseek.com",
                      ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v3.2", "deepseek-r1-distill-qwen-32b"])
    register_provider("zhipu", "智谱 (GLM)", "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                      "https://open.bigmodel.cn",
                      ["glm-4-plus", "glm-4-air", "glm-4-flash", "glm-4.7-flash", "glm-5.1"])
    register_provider("tongyi", "通义千问 (Qwen)", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                      "https://dashscope.console.aliyun.com",
                      ["qwen-max", "qwen-plus", "qwen-turbo", "qwen3-235b", "qwen3-30b-a3b"])
    register_provider("minimax", "MiniMax", "https://api.minimax.chat/v1/chat/completions",
                      "https://platform.minimax.com",
                      ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M1"])
    register_provider("kimi", "Kimi (Moonshot)", "https://api.moonshot.cn/v1/chat/completions",
                      "https://platform.kimi.com",
                      ["kimi-k2-0711-preview", "moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-8k"])
    register_provider("deepinfra", "DeepInfra", "https://api.deepinfra.com/v1/openai/chat/completions",
                      "https://deepinfra.com",
                      ["meta-llama/Llama-4-Maverick-17B-128E-Instruct", "mistralai/Mixtral-8x22B-Instruct-v0.1"])
    register_provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1/chat/completions",
                      "https://openrouter.ai/keys",
                      ["openai/gpt-4o", "anthropic/claude-sonnet-4", "google/gemini-2.5-pro", "deepseek/deepseek-v4-flash", "qwen/qwen-max", "meta-llama/llama-4-maverick"])
    register_provider("groq", "Groq", "https://api.groq.com/openai/v1/chat/completions",
                      "https://console.groq.com",
                      ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen-2.5-32b"])
    register_provider("mistral", "Mistral AI", "https://api.mistral.ai/v1/chat/completions",
                      "https://console.mistral.ai",
                      ["mistral-large-latest", "mistral-small-latest", "codestral-latest"])
    register_provider("volcengine", "火山引擎 (豆包)", "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
                      "https://console.volcengine.com",
                      ["doubao-1-5-pro-32k", "doubao-1-5-lite-32k"])
    register_provider("lingyi", "零一万物 (Yi)", "https://api.lingyiwanwu.com/v1/chat/completions",
                      "https://platform.lingyiwanwu.com",
                      ["yi-large", "yi-medium", "yi-lightning"])
    register_provider("baichuan", "百川智能", "https://api.baichuan-ai.com/v1/chat/completions",
                      "https://platform.baichuan-ai.com",
                      ["Baichuan4", "Baichuan3-Turbo"])
    register_provider("stepfun", "阶跃星辰", "https://api.stepfun.com/v1/chat/completions",
                      "https://platform.stepfun.com",
                      ["step-2-16k", "step-1v-32k"])
    register_provider("nvidia", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1/chat/completions",
                      "https://build.nvidia.com",
                      ["deepseek-ai/deepseek-v4-flash", "nvidia/nemotron-3-super-120b-a12b", "meta/llama-4-maverick-17b-128e-instruct"])
    register_provider("together", "Together AI", "https://api.together.xyz/v1/chat/completions",
                      "https://together.ai",
                      ["mistralai/Mixtral-8x22B-Instruct-v0.1", "meta-llama/Llama-3.3-70B-Instruct-Turbo"])

register_defaults()

# ---------- 配置写入 ----------
def write_adapter_config(upstream: str, model: str, api_key: str):
    ensure_dirs()
    ADAPTER_JSON.write_text(
        json.dumps({
            "subscription": "normal",
            "model": model,
            "upstream": upstream,
            "api_key": api_key,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def backup_config_toml():
    if CONFIG_TOML.exists() and not BACKUP_TOML.exists():
        shutil.copy2(CONFIG_TOML, BACKUP_TOML)

def apply_codex_config(model_label: str):
    ensure_dirs()
    if CONFIG_TOML.exists():
        doc = tomlkit.parse(CONFIG_TOML.read_text(encoding="utf-8"))
    else:
        doc = tomlkit.document()
    doc["model"] = "stepfun_codex_adapter"
    doc["proxy"] = ""
    doc["verbose"] = "false"
    doc["max_output"] = "256000"
    doc["allowed_tools"] = ["Bash", "Read", "Edit", "glob", "Grep", "FileEdit"]
    if "model_providers" not in doc:
        doc["model_providers"] = tomlkit.table()
    prov = doc["model_providers"]
    if "stepfun_codex_adapter" not in prov:
        prov["stepfun_codex_adapter"] = tomlkit.table()
    block = prov["stepfun_codex_adapter"]
    block["name"] = model_label
    block["provider"] = "openai"
    block["api_base"] = f"http://{ADAPTER_HOST}:{ADAPTER_PORT}/v1"
    CONFIG_TOML.write_text(tomlkit.dumps(doc), encoding="utf-8")

def restore_openai():
    if not BACKUP_TOML.exists():
        return "未发现备份，配置未被修改过。"
    shutil.copy2(BACKUP_TOML, CONFIG_TOML)
    return "已从备份还原 config.toml（回到 OpenAI 原始配置）。"

# ---------- 翻译官启停 ----------
class AdapterRunner:
    def __init__(self, log_fn=None):
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self._log = log_fn or (lambda msg: None)

    def log(self, msg):
        self._log(msg)

    def start(self) -> bool:
        if self.httpd:
            self.log("翻译官已经在运行")
            return True
        try:
            self.httpd = ThreadingHTTPServer((adapter.HOST, adapter.PORT), adapter.Handler)
        except OSError as e:
            self.log(f"端口 {adapter.PORT} 被占用：{e}")
            # 可能已经有个实例在跑
            if adapter_running():
                self.log("检测到已有实例在运行")
                self.httpd = None
                return True
            return False
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        for _ in range(30):
            if adapter_running():
                self.log(f"翻译官已启动：http://{ADAPTER_HOST}:{ADAPTER_PORT}")
                return True
            time.sleep(0.1)
        self.log("翻译官启动超时")
        return False

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception as e:
                self.log(f"停止出错：{e}")
            self.httpd = None
        self.log("翻译官已停止")

    def is_running(self) -> bool:
        return self.httpd is not None or adapter_running()
