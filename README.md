# VoxCore

A modular, wake-word-driven voice assistant core built for real-time speech, LLM orchestration, and edge deployment.

---

## Platform Compatibility

| Component | Windows | macOS | Linux |
|---|---|---|---|
| Core pipeline (wake → STT → LLM → TTS → speak) | Fully supported | Supported (see notes) | Supported (see notes) |
| Wake word detection (Porcupine) | Supported | Supported | Supported |
| Custom `.ppn` wake word model | Windows model included | Requires macOS-specific `.ppn` | Requires Linux-specific `.ppn` |
| STT (faster-whisper, CUDA) | Supported with NVIDIA GPU | Not available (use `cpu`) | Supported with NVIDIA GPU |
| STT (faster-whisper, CPU) | Supported | Supported (including Apple Silicon) | Supported |
| TTS (ElevenLabs cloud API) | Supported | Supported | Supported |
| LLM backends (Ollama / vLLM / OpenAI) | Supported | Supported | Supported |
| `open_application` tool | Supported | Supported | Supported |
| Web search tool (SearXNG) | Supported | Supported | Supported |
| PyAudio installation | May require prebuilt wheel | Requires `portaudio` via Homebrew | Requires `portaudio19-dev` via apt |

**Key notes:**

- **macOS:** CUDA is not available. Set `WHISPER_DEVICE=cpu` and use a smaller Whisper model (e.g., `small`) for reasonable performance.
- **Custom wake word models:** Porcupine `.ppn` files are compiled for a specific platform. The included `harvest_windows.ppn` only works on Windows. Generate macOS or Linux models at [Picovoice Console](https://console.picovoice.ai/). Alternatively, leave `WAKE_KEYWORD_PATH` empty to use a built-in keyword (e.g., `jarvis`), which works on all platforms.
- **Apple Silicon:** faster-whisper runs on ARM64 via `int8` compute type (automatic when `WHISPER_DEVICE=cpu`).

---

## Overview

VoxCore is a single-process voice assistant that listens for a wake word, transcribes speech locally, sends the text to a configurable LLM with tool-calling capabilities, synthesizes the response via cloud TTS, and speaks it back. The full pipeline:

```
IDLE → (wake word detected) → LISTEN → STT → LLM (+tools) → TTS → SPEAK → IDLE
```

All provider choices (wake engine, STT, LLM backend, TTS) are configured entirely through a `.env` file — no code changes needed to swap providers. The LLM decides which tools to call at runtime based on user intent; there is no hardcoded command routing.

---

## Key Features

- **Wake word detection** — Picovoice Porcupine with built-in keywords or custom-trained models
- **Local speech-to-text** — faster-whisper (CTranslate2-optimized Whisper) with no API calls required
- **Multiple LLM backends** — Ollama (local CPU), vLLM (GPU server), or OpenAI (cloud API)
- **Adaptive TTS** — ElevenLabs with hybrid routing between Flash v2.5 (low latency) and v3 (expressive), emotion directives, and automatic fallback
- **LLM-driven tool calling** — multi-turn tool execution loop with deduplication and failure handling
- **Built-in tools** — date/time, application launcher, web search (SearXNG with health-aware instance selection)
- **Conversation memory** — rolling turn-based history with configurable depth
- **Zero disk I/O** — all audio stays in memory end-to-end (no temp files)
- **Factory pattern architecture** — every provider is swappable via abstract base classes and `.env` configuration

---

## Architecture

```
main.py                          Entry point — wires providers, starts loop
│
├── voxcore/config.py            Centralized config (loads .env once)
├── voxcore/orchestrator.py      Pipeline runner + multi-turn tool loop
│
├── voxcore/wake/                Wake word detection
│   ├── base.py                  WakeWordEngine ABC
│   ├── porcupine.py             Picovoice Porcupine implementation
│   └── factory.py               Selects engine from WAKE_ENGINE
│
├── voxcore/stt/                 Speech-to-text
│   ├── base.py                  STTProvider ABC
│   ├── whisper.py               faster-whisper implementation
│   └── factory.py               Selects provider from STT_PROVIDER
│
├── voxcore/llm/                 LLM backends
│   ├── base.py                  LLMClient ABC + ToolCall/LLMResponse dataclasses
│   ├── ollama.py                Ollama local server client
│   ├── openai.py                OpenAI Chat Completions client
│   ├── vllm.py                  vLLM GPU inference server client
│   └── factory.py               Selects backend from LLM_BACKEND
│
├── voxcore/tts/                 Text-to-speech
│   ├── base.py                  TTSProvider ABC
│   ├── elevenlabs.py            ElevenLabs Flash v2.5 single-model provider
│   ├── hybrid_elevenlabs.py     Adaptive Flash v2.5 / v3 with emotion routing
│   └── factory.py               Selects provider from TTS_PROVIDER
│
├── voxcore/tools/               LLM-callable tools
│   ├── base.py                  BaseTool ABC with OpenAI function spec builder
│   ├── registry.py              ToolRegistry (register / specs / execute)
│   ├── datetime_tool.py         get_current_datetime
│   ├── open_app.py              open_application (cross-platform)
│   └── web_search.py            web_search (SearXNG JSON API)
│
├── voxcore/audio/
│   └── recorder.py              PyAudio mic capture + WAV playback
│
└── docker/
    ├── docker-compose.yml       Local SearXNG search instance
    └── searxng/settings.yml     SearXNG configuration
```

Every subsystem follows the same pattern: an abstract base class defines the interface, one or more concrete implementations provide the behavior, and a factory function selects the active implementation from `Config`. The `Orchestrator` depends only on the ABCs, so new providers can be added without modifying any existing code.

---

## Requirements

### Python

- **Python 3.10+** (uses `str | None` union syntax and PEP 585 bare generics)

### Hardware

- **Microphone** — required for wake word detection and speech capture
- **Speaker/headphones** — required for audio playback
- **GPU (optional)** — NVIDIA GPU with CUDA for accelerated Whisper STT. CPU-only mode works on all platforms.

### API Keys

| Service | Variable | Required | Free tier |
|---|---|---|---|
| [Picovoice](https://console.picovoice.ai/) | `PICOVOICE_ACCESS_KEY` | Yes | Yes |
| [ElevenLabs](https://elevenlabs.io/app/settings/api-keys) | `ELEVENLABS_API_KEY` | Yes | Limited |
| [OpenAI](https://platform.openai.com/api-keys) | `OPENAI_API_KEY` | Only if `LLM_BACKEND=openai` | No |

### LLM Backend (one required)

| Backend | Requirement |
|---|---|
| **Ollama** (default) | [Ollama](https://ollama.ai/) running locally with a model pulled (default: `qwen2.5:7b-instruct`) |
| **vLLM** | vLLM server running with OpenAI-compatible API (default: `Qwen/Qwen2.5-7B-Instruct`) |
| **OpenAI** | Valid `OPENAI_API_KEY` |

---

## Installation

### macOS

```bash
# 1. Install system dependencies
brew install portaudio

# 2. Clone the repository
git clone https://github.com/afish2003/VoxCore.git
cd VoxCore

# 3. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 4. Install Python dependencies
pip install -r requirements.txt

# 5. Configure environment
cp .env.example .env
# Edit .env — set your API keys and adjust settings:
#   PICOVOICE_ACCESS_KEY=your_key
#   ELEVENLABS_API_KEY=your_key
#   ELEVENLABS_VOICE_ID=your_voice_id
#   WHISPER_DEVICE=cpu
#   WHISPER_MODEL=small
#   WAKE_KEYWORD_PATH=          (leave empty to use built-in keyword)

# 6. Install and start Ollama (default LLM backend)
brew install ollama
ollama serve &
ollama pull qwen2.5:7b-instruct

# 7. (Optional) Start local SearXNG for web search
docker compose -f docker/docker-compose.yml up -d

# 8. Run
python main.py
```

### Windows

```powershell
# 1. Clone the repository
git clone https://github.com/afish2003/VoxCore.git
cd VoxCore

# 2. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install Python dependencies
pip install -r requirements.txt
# If PyAudio fails, download the prebuilt wheel:
#   https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio
#   pip install PyAudio-0.2.14-cp311-cp311-win_amd64.whl

# 4. Configure environment
copy .env.example .env
# Edit .env — set your API keys:
#   PICOVOICE_ACCESS_KEY=your_key
#   ELEVENLABS_API_KEY=your_key
#   ELEVENLABS_VOICE_ID=your_voice_id
#   WHISPER_DEVICE=cuda  (or cpu if no NVIDIA GPU)

# 5. Install and start Ollama (default LLM backend)
# Download from https://ollama.ai/ and install
ollama serve
ollama pull qwen2.5:7b-instruct

# 6. (Optional) Start local SearXNG for web search
docker compose -f docker/docker-compose.yml up -d

# 7. Run
python main.py
```

### Linux (Ubuntu/Debian)

```bash
# 1. Install system dependencies
sudo apt update
sudo apt install -y python3-dev portaudio19-dev

# 2. Clone the repository
git clone https://github.com/afish2003/VoxCore.git
cd VoxCore

# 3. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 4. Install Python dependencies
pip install -r requirements.txt

# 5. Configure environment
cp .env.example .env
# Edit .env — set your API keys and adjust settings:
#   PICOVOICE_ACCESS_KEY=your_key
#   ELEVENLABS_API_KEY=your_key
#   ELEVENLABS_VOICE_ID=your_voice_id
#   WHISPER_DEVICE=cuda  (or cpu if no NVIDIA GPU)
#   WAKE_KEYWORD_PATH=          (leave empty to use built-in keyword)

# 6. Install and start Ollama (default LLM backend)
curl -fsSL https://ollama.ai/install.sh | sh
ollama serve &
ollama pull qwen2.5:7b-instruct

# 7. (Optional) Start local SearXNG for web search
docker compose -f docker/docker-compose.yml up -d

# 8. Run
python main.py
```

---

## Environment Variables

All configuration is managed through a `.env` file. Copy `.env.example` to `.env` and edit as needed. No code changes are required to swap providers or tune behavior.

### Wake Word

| Variable | Default | Description |
|---|---|---|
| `WAKE_ENGINE` | `porcupine` | Wake word engine (only `porcupine` currently supported) |
| `WAKE_KEYWORD` | `jarvis` | Built-in keyword (options: `jarvis`, `alexa`, `computer`, `hey google`, `hey siri`, `grasshopper`, `bumblebee`, `terminator`, `picovoice`, `porcupine`) |
| `WAKE_KEYWORD_PATH` | _(empty)_ | Path to custom `.ppn` model file (overrides `WAKE_KEYWORD` when set) |
| `WAKE_SENSITIVITY` | `0.5` | Detection threshold: `0.0` (strict) to `1.0` (permissive) |
| `PICOVOICE_ACCESS_KEY` | _(required)_ | Free key from [console.picovoice.ai](https://console.picovoice.ai/) |
| `WAKE_CONFIRM_GATE` | `false` | Post-wake RMS energy check to reduce false positives |
| `WAKE_CONFIRM_DURATION` | `0.8` | Seconds of audio to capture for confirmation gate |
| `WAKE_CONFIRM_RMS_THRESHOLD` | `200` | RMS floor for confirmation (0–32768) |

### Speech-to-Text

| Variable | Default | Description |
|---|---|---|
| `STT_PROVIDER` | `whisper` | STT provider (only `whisper` currently supported) |
| `WHISPER_MODEL` | `large-v3` | Model size: `tiny`, `base`, `small`, `medium`, `large-v3` |
| `WHISPER_DEVICE` | `cuda` | Compute device: `cpu` or `cuda` |
| `WHISPER_LANG` | `en` | Language code or `auto` for detection |
| `WHISPER_BEAM_SIZE` | `5` | Beam search width |
| `WHISPER_VAD_FILTER` | `true` | Enable Silero VAD inside faster-whisper |
| `WHISPER_INITIAL_PROMPT` | _(empty)_ | Vocabulary hint for proper nouns |

### LLM

| Variable | Default | Description |
|---|---|---|
| `LLM_BACKEND` | `ollama` | Backend: `ollama`, `vllm`, or `openai` |
| `LLM_SYSTEM_PROMPT` | _(Amy persona)_ | Full system prompt (multiline supported in double quotes) |
| `LLM_TEMPERATURE` | `0.6` | Sampling temperature |
| `LLM_TOP_P` | `0.9` | Top-p nucleus sampling |
| `LLM_MAX_TOKENS` | `200` | Maximum response tokens |
| `LLM_MAX_TOOL_ROUNDS` | `5` | Maximum tool-call iterations before fallback |
| `LLM_MAX_HISTORY` | `10` | Rolling conversation turns to keep |
| `OLLAMA_URL` | `http://127.0.0.1:11434/api/chat` | Ollama API endpoint |
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct` | Ollama model name |
| `OLLAMA_TIMEOUT` | `120` | Request timeout (seconds) |
| `VLLM_URL` | `http://127.0.0.1:8000/v1/chat/completions` | vLLM API endpoint |
| `VLLM_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | vLLM model name |
| `VLLM_TIMEOUT` | `60` | Request timeout (seconds) |
| `OPENAI_API_KEY` | _(empty)_ | OpenAI API key (required only for `openai` backend) |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name |
| `OPENAI_TIMEOUT` | `30` | Request timeout (seconds) |

### Text-to-Speech

| Variable | Default | Description |
|---|---|---|
| `TTS_PROVIDER` | `elevenlabs` | Provider: `elevenlabs` (Flash only) or `elevenlabs_hybrid` (adaptive routing) |
| `ELEVENLABS_API_KEY` | _(required)_ | ElevenLabs API key |
| `ELEVENLABS_VOICE_ID` | _(required)_ | ElevenLabs voice ID |
| `ELEVENLABS_MODEL_ID` | `eleven_flash_v2_5` | Model for single-model provider |
| `ELEVENLABS_STABILITY` | `0.45` | Flash voice stability (0.0–1.0) |
| `ELEVENLABS_SIMILARITY` | `0.85` | Flash voice similarity (0.0–1.0) |
| `ELEVENLABS_STYLE` | `0.3` | Flash voice style (0.0–1.0) |
| `TTS_MAX_CHARS` | `300` | Maximum characters per TTS call (cost control) |
| `TTS_FAST_MODEL` | `eleven_flash_v2_5` | Hybrid: model for short/utility responses |
| `TTS_EMOTE_MODEL` | `eleven_v3` | Hybrid: model for expressive responses |
| `TTS_MODE` | `hybrid` | Routing mode: `hybrid`, `flash_only`, or `v3_only` |
| `TTS_EMOTION_DEFAULT` | `neutral` | Default emotion when no `[emotion:tag]` prefix is present |
| `TTS_V3_STABILITY` | `0.70` | v3 voice stability (independent of Flash) |
| `TTS_V3_SIMILARITY` | `0.75` | v3 voice similarity |
| `TTS_V3_STYLE` | `0.05` | v3 voice style |
| `TTS_V3_TEXT_NORMALIZE` | `true` | Strip `!`/ALL-CAPS/emojis before v3 synthesis |
| `TTS_V3_SPEED` | `0.85` | v3 speaking rate (`< 1.0` = slower) |

### Web Search

| Variable | Default | Description |
|---|---|---|
| `SEARX_INSTANCES` | `http://127.0.0.1:8080,...` | Comma-separated SearXNG instance URLs (local first, public fallbacks) |

### Audio I/O

| Variable | Default | Description |
|---|---|---|
| `AUDIO_SAMPLE_RATE` | `16000` | Microphone sample rate (Hz) |
| `AUDIO_CHUNK_SIZE` | `1024` | PyAudio buffer size |
| `VAD_ENERGY_THRESHOLD` | `500` | Energy floor for speech detection |
| `VAD_SILENCE_DURATION` | `2.0` | Seconds of silence before recording stops |
| `RECORD_MAX_DURATION` | `15.0` | Hard cap on recording length (seconds) |

### Logging

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Running the Application

```bash
python main.py
```

On startup, VoxCore logs its configuration:

```
VoxCore Starting
  Wake engine : porcupine (JARVIS)
  STT         : whisper (large-v3)
  LLM         : ollama
  TTS         : elevenlabs_hybrid
  Tools       : 3 registered
Say 'JARVIS' to activate.  Ctrl+C to exit.
[IDLE]
```

Say the wake word to activate a pipeline cycle. Each cycle logs timing for every stage:

```
[IDLE] total=4.32s (listen=2.10, stt=0.45, llm=1.02, tts=0.60, speak=0.15)
```

Press **Ctrl+C** for graceful shutdown.

---

## Project Structure

```
VoxCore/
├── main.py                      # Entry point
├── requirements.txt             # Python dependencies
├── .env.example                 # Full configuration template
├── MIGRATION.md                 # Migration notes from predecessor project (ARVIS)
├── SMOKE_TEST.md                # Manual test plan (5 phases)
├── assets/
│   └── wakewords/
│       └── harvest_windows.ppn  # Custom Porcupine wake word model (Windows)
├── docker/
│   ├── docker-compose.yml       # Local SearXNG instance
│   └── searxng/
│       └── settings.yml         # SearXNG configuration
└── voxcore/                     # Core package
    ├── config.py                # Centralized configuration loader
    ├── orchestrator.py          # Pipeline runner + tool-call loop
    ├── audio/
    │   └── recorder.py          # Microphone capture + WAV playback
    ├── wake/                    # Wake word detection
    ├── stt/                     # Speech-to-text
    ├── llm/                     # LLM backends
    ├── tts/                     # Text-to-speech
    └── tools/                   # LLM-callable tools
```

---

## Troubleshooting

### PyAudio installation fails

**macOS:**
```bash
brew install portaudio
pip install pyaudio
```

**Linux:**
```bash
sudo apt install portaudio19-dev
pip install pyaudio
```

**Windows:** If `pip install pyaudio` fails, download a prebuilt wheel from [https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio) matching your Python version, then:
```powershell
pip install PyAudio-0.2.14-cp311-cp311-win_amd64.whl
```

### CUDA not found / Whisper fails to load

Set `WHISPER_DEVICE=cpu` in `.env`. Use a smaller model (`WHISPER_MODEL=small` or `base`) for faster CPU inference. CUDA requires an NVIDIA GPU with compatible drivers and the CUDA toolkit installed.

### Ollama connection refused

Ensure Ollama is running before starting VoxCore:
```bash
ollama serve
```
Then pull the model if not already downloaded:
```bash
ollama pull qwen2.5:7b-instruct
```

### No wake word detection

- Check that `PICOVOICE_ACCESS_KEY` is set correctly in `.env`
- If using a custom `.ppn` model, ensure the file exists at the path specified in `WAKE_KEYWORD_PATH` and matches your OS platform
- Try increasing `WAKE_SENSITIVITY` (e.g., `0.7`) if the keyword is not being detected
- Try decreasing `WAKE_SENSITIVITY` (e.g., `0.4`) if you get frequent false positives
- If `WAKE_CONFIRM_GATE=true`, try lowering `WAKE_CONFIRM_RMS_THRESHOLD` or disabling the gate

### ElevenLabs TTS errors

- Verify `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` are set correctly
- Check your ElevenLabs quota at [elevenlabs.io](https://elevenlabs.io/)
- If v3 synthesis fails, the hybrid provider automatically falls back to Flash v2.5

### Web search returns no results

- Start the local SearXNG instance: `docker compose -f docker/docker-compose.yml up -d`
- If all instances are on cooldown, wait for the cooldown to expire (1–15 minutes depending on failure type)
- Check public instance availability at [searx.space](https://searx.space/)

### Microphone not detected / `OSError: [Errno -9996]`

- Ensure your microphone is connected and set as the default input device in your OS sound settings
- On Windows, check that no other application is exclusively holding the audio device
- Try adjusting `AUDIO_SAMPLE_RATE` if your microphone does not support 16000 Hz

---

## Adding New Tools

1. Create `voxcore/tools/your_tool.py`
2. Subclass `BaseTool` and define `name`, `description`, `parameters`, and `execute()`
3. Import and register it in `main.py`:
   ```python
   from voxcore.tools.your_tool import YourTool
   tool_registry.register(YourTool())
   ```

No other files need to change. The LLM receives the tool definition automatically and decides when to call it.

---

## Future Improvements

- **Additional STT providers** — cloud-based alternatives (e.g., Google Speech, Azure Speech) for machines without GPU
- **Additional TTS providers** — local TTS options (e.g., Coqui, Piper) to reduce cloud dependency
- **Persistent conversation history** — save/load conversation turns to disk across sessions
- **Streaming TTS playback** — begin playback before the full TTS response is received to reduce perceived latency
- **Platform-specific wake word models** — include `.ppn` models for macOS and Linux alongside the Windows model
