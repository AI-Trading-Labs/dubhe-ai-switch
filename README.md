# Dubhe AI Switch

OpenAI Codex model switcher — use any OpenAI-compatible LLM provider with Codex.

## Built-in Providers (6)

| Provider | Models | Get API Key |
|----------|--------|-------------|
| DeepSeek | deepseek-v4-pro, deepseek-v4-flash | platform.deepseek.com |
| Kimi | kimi-k2.6, kimi-k2.5 | platform.kimi.ai |
| Zhipu GLM | glm-4.7, glm-4.7-flash | open.bigmodel.cn |
| Qwen (Tongyi) | qwen-plus, qwen-flash | dashscope.console.aliyun.com |
| Xiaomi MiMo | mimo-v2.5, mimo-v2.5-pro | platform.xiaomimimo.com |
| MiniMax | MiniMax-M2.7, MiniMax-M2.5 | platform.minimax.io |

Add any other OpenAI-compatible provider via "Custom" button.

## Install

```bash
git clone https://github.com/AI-Trading-Labs/dubhe-ai-switch.git
cd dubhe-ai-switch
pip install -r requirements.txt
python main.py
```

## How to Use

1. Get API Key from your chosen provider
2. Select provider → model → paste API Key
3. Click start button
4. Open Codex App — it auto-uses the selected model
5. Click stop to restore OpenAI
6. Close window hides to system tray; right-click tray icon to quit

## Custom Provider

Click "custom" and fill in 3 fields:

| Field | Example |
|-------|---------|
| Model ID | gpt-4o |
| Base URL | https://api.openai.com/v1/chat/completions |
| API Key | sk-... |

## Requirements

- Python 3.11+
- customtkinter, tomlkit, pystray, Pillow

## License

MIT
