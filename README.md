# Dubhe AI Switch

> Put any LLM behind Codex CLI. OpenAI-compatible proxy with system tray.

## Features
- Switch between DeepSeek, Kimi, Zhipu (GLM), Tongyi (Qwen), OpenRouter and more
- Minimize to system tray - stays out of your way
- Custom providers: add any OpenAI-compatible API
- One-click restore to original OpenAI config

## Usage
```bash
pip install -r requirements.txt
python src/main.py
```

## Build .exe
```powershell
pip install pyinstaller
pyinstaller --onefile --windowed --icon assets/icon.ico src/main.py
```
