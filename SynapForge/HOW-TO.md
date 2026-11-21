# Synap-Forge — HOW-TO
**v1.0.0-beta "Foundry"** · VibeTech

---

## What is this?

Synap-Forge is a local-first AI workspace that runs entirely on your machine.
No account. No cloud dependency by default. You bring the model, you run the forge.

The system boots a full AI personality (SynapCore) backed by your local LLM,
with a web dashboard, memory system (Redis + ChromaDB), and an MCP gateway
that lets you extend capabilities via plugins.

---

## Requirements

| Component | Min Version |
|-----------|-------------|
| Python | 3.11+ |
| Redis | 7.x (optional — falls back to JSON) |
| llama.cpp server | any recent build |
| GGUF model | any Q4+ 7B–13B instruction model |

> **Windows**: tested on Windows 10/11 x64  
> **Linux**: tested on Arch / Ubuntu 22+. The `yay` packages in `mcp/` are for Arch — ignore on other distros.

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

Voice/audio support (optional):
```bash
pip install -r requirements-voice.txt
# also requires: ffmpeg on PATH
```

### 2. Configure your model

Edit `synap_config.json` — set the model endpoint to your llama-server address:

```json
{
  "model_provider": {
    "primary": "local",
    "local": { "endpoint": "http://localhost:11437/v1" }
  }
}
```

Or set via environment variable:
```
LLM_ENDPOINT=http://localhost:11437/v1
```

> No `.env` file ships with this release.  
> Keys and config are injected via Discord/community boards or the future VibeTech identity system.

### 3. Start llama-server with your model

```bash
# Example — adjust path, context, GPU layers to your hardware
llama-server -m /path/to/your-model.gguf --port 11437 --alias Gemma -c 4096 --n-gpu-layers 35
```

The server must be running before you launch the Forge.

### 4. Launch the Forge

**Windows:**
```
launcher.bat
```
Then click **INITIATE BOOT SEQUENCE** in the launcher window.

**Linux:**
```bash
python synap_server.py
```

Dashboard opens at `http://localhost:11436`

---

## Ports used

| Port | Service |
|------|---------|
| 11435 | Ollama fallback (optional) |
| 11436 | Synap-Forge dashboard + API |
| 11437 | llama-server (your LLM) |
| 11438 | MCP socket |
| 11439 | Interceptor |
| 11440 | MCP HTTP gateway (synaplite-plugin) |
| 11441 | MCP WebSocket |

---

## Plugins (MCP Gateway)

The MCP gateway (`synaplite-plugin`) lets you extend Forge capabilities:

```bash
cd synaplite-plugin
drew_start.bat          # Windows
# or
python mcp_server.py    # Linux
```

Plugins connect at `http://localhost:11440`.

> Download plugins from VibeTech Discord / community boards.  
> **Synap-Smithy** (API-max tier) uses the same gateway with cloud model escalation.

---

## Linux notes

- Replace `llama\bin\llama-server.exe` with the Linux llama-server binary
- `mcp/yay/` packages are for Arch Linux AUR — skip on Debian/Ubuntu
- Redis: `sudo apt install redis-server` or `sudo pacman -S redis`
- Voice deps require `portaudio`: `sudo apt install portaudio19-dev`

---

## Troubleshooting

**Chat not responding:**  
Make sure llama-server is running on port 11437 before launching the Forge.

**Redis connection warning:**  
Normal if Redis isn't installed. Forge falls back to JSON memory automatically.

**MCP Gateway timeout in launcher:**  
Expected if synaplite-plugin isn't set up yet. Forge boots without it.

---

## Community

- Discord: *link via VibeTech*
- Forum: *link via VibeTech*
- GitHub: https://github.com/vibetechxoffice-bit/Synap-Forge

---

*They gave you a forge. Go make the plugins.*
