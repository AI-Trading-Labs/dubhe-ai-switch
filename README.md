# Dubhe AI Switch

<p align="center">
  <img src="assets/icon.png" width="128" alt="Dubhe AI Switch Logo"/>
</p>

<p align="center">
  <strong>Put any LLM behind Codex CLI.</strong><br>
  OpenAI-compatible proxy with system tray. For DeepSeek, Kimi, Zhipu, Qwen, OpenRouter and more.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows-blue" alt="Platform"/>
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License"/>
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Status"/>
</p>

---

## What is this?

**Dubhe AI Switch** is a lightweight desktop proxy that runs in your system tray. It translates Codex CLI's request format into any OpenAI-compatible API, so you can use:

- DeepSeek (V4 Flash / V4 Pro)
- Kimi (K2 / Moonshot)
- Zhipu (GLM-4)
- Tongyi (Qwen)
- OpenRouter
- Or any custom OpenAI-compatible endpoint

## Features

- **One-click switch** — Select provider, paste API key, click Start
- **System tray** — Close to tray, stays out of your way
- **One-click restore** — Instantly revert to original OpenAI config
- **Custom providers** — Add any OpenAI-compatible API
- **Key isolation** — Keys stored per provider, auto-loaded next time
- **Auto backup** — Original Codex config saved before first switch
- **Dubhe Dark UI** — Starry night theme by Dubhe AI

## Usage

```bash
pip install -r requirements.txt
python src/main.py
```

### Build .exe

```powershell
pip install pyinstaller
pyinstaller --onefile --windowed --icon assets/icon.ico --name "DubheAISwitch" src/main.py
```

## How it works

```
Codex CLI → Dubhe AI Switch (port 18667) → Your chosen LLM API
```

The app starts a local proxy server that speaks OpenAI chat/completions format, and updates your Codex config.toml to point to it.

## Credits

Based on [codex-switch](https://github.com/aliang2052/codex-switch) by [@aliang2052](https://github.com/aliang2052) (MIT). Adapter module originally from [stepfun-codex-adapter](https://github.com/LearnPrompt/stepfun-codex-adapter) (MIT).

## License

MIT
