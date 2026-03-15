# VoxCore — Technical Reference

Comprehensive technical documentation covering architecture, configuration, dependencies, and every module in the VoxCore voice assistant system.

---

## 1. Project Identity

- **Name:** VoxCore
- **Repository:** https://github.com/afish2003/VoxCore
- **Language:** Python 3.10+
- **Codebase size:** ~2,500 lines of Python across 24 source files
- **Predecessor:** ARVIS (voice-pipeline) — a client/server split voice assistant

---

## 2. Purpose

VoxCore is a **modular, wake-word-driven voice assistant core** designed for real-time speech interaction and edge deployment. It runs as a single process that continuously listens for a configurable wake word, captures the user's speech, transcribes it locally, sends the transcript to a large language model that can autonomously call tools, synthesizes the LLM's response into speech via a cloud TTS API, and plays it back through speakers.

The complete pipeline per activation cycle:

```
IDLE → (wake word detected) → LISTEN → STT → LLM (+tools) → TTS → SPEAK → IDLE
```

**Target users:** Developers building voice-controlled applications, robotics interfaces, smart home systems, or XR/VR companions that need a configurable voice pipeline with LLM tool-calling capabilities.

---

## 3. Architecture

### 3.1 Design Principles

1. **Zero hardcoded logic** — all provider selection happens in `.env` only
2. **All audio in memory** — no temporary files written to disk at any point
3. **Single process** — no client/server split (migrated from ARVIS's two-process design)
4. **Dependency injection** — all providers are created once in `main.py` and injected into the `Orchestrator`
5. **Factory pattern + ABCs** — every subsystem has an abstract base class, one or more implementations, and a factory function that reads config to select the active implementation
6. **LLM-driven tool calling** — the LLM decides at runtime which tools to invoke; there is no keyword routing or hardcoded command logic

### 3.2 Module Inventory

| File | Lines | Purpose |
|---|---|---|
| `main.py` | 93 | Entry point — instantiates all providers, registers tools, wires Orchestrator, starts wake loop |
| `voxcore/config.py` | 186 | Centralized config — `Config` dataclass with 40+ fields, all populated from `os.getenv()` via `python-dotenv` |
| `voxcore/orchestrator.py` | 266 | Pipeline runner — `run_pipeline()` callback; multi-turn LLM + tool execution loop; turn-based conversation memory |
| `voxcore/audio/recorder.py` | 107 | PyAudio mic capture with energy-based VAD; WAV playback; opens/closes streams per call to avoid device conflicts |
| `voxcore/wake/base.py` | 41 | `WakeWordEngine` ABC — `start()` blocks forever, calls `on_wake()` per detection, `stop()` signals exit |
| `voxcore/wake/porcupine.py` | 207 | Picovoice Porcupine implementation — supports built-in keywords and custom `.ppn` models; optional RMS confirmation gate |
| `voxcore/wake/factory.py` | 30 | Selects wake engine from `WAKE_ENGINE` env var |
| `voxcore/stt/base.py` | 30 | `STTProvider` ABC — `transcribe(audio_bytes) -> str` |
| `voxcore/stt/whisper.py` | 92 | faster-whisper (CTranslate2) — loads model once, transcribes in-memory WAV, strips hallucination artifacts |
| `voxcore/stt/factory.py` | 28 | Selects STT provider from `STT_PROVIDER` env var |
| `voxcore/llm/base.py` | 73 | `LLMClient` ABC + `ToolCall` and `LLMResponse` dataclasses |
| `voxcore/llm/ollama.py` | 73 | Ollama client — local CPU-friendly; handles Ollama's dict-style arguments and missing tool call IDs |
| `voxcore/llm/openai.py` | 85 | OpenAI SDK client — native tool calling, no message translation needed |
| `voxcore/llm/vllm.py` | 68 | vLLM client — OpenAI-compatible `/v1/chat/completions` endpoint for GPU inference |
| `voxcore/llm/factory.py` | 40 | Selects LLM backend from `LLM_BACKEND` env var |
| `voxcore/tts/base.py` | 31 | `TTSProvider` ABC — `synthesize(text) -> bytes` (WAV) |
| `voxcore/tts/elevenlabs.py` | 103 | ElevenLabs Flash v2.5 single-model provider — requests raw PCM, wraps in WAV container |
| `voxcore/tts/hybrid_elevenlabs.py` | 416 | Adaptive TTS — routes between Flash v2.5 (short/ACK) and v3 (expressive) based on text length, ACK patterns, and emotion directives; PCM format negotiation; automatic Flash fallback; v3 text normalizer |
| `voxcore/tts/factory.py` | 33 | Selects TTS provider from `TTS_PROVIDER` env var |
| `voxcore/tools/base.py` | 55 | `BaseTool` ABC — `name`, `description`, `parameters` (JSON Schema), `execute(**kwargs) -> str`, `to_openai_spec()` |
| `voxcore/tools/registry.py` | 66 | `ToolRegistry` — fluent `.register()` API, `specs()` returns OpenAI tool definitions, `execute()` runs tool with error handling |
| `voxcore/tools/datetime_tool.py` | 28 | `get_current_datetime` — returns local date/time string, no dependencies |
| `voxcore/tools/open_app.py` | 132 | `open_application` — cross-platform app launcher with per-OS aliases and launch commands |
| `voxcore/tools/web_search.py` | 251 | `web_search` — SearXNG JSON API with health-aware multi-instance selection, per-failure-type cooldowns, query normalization, structured JSON output |

### 3.3 Orchestrator Detail

The `Orchestrator` is the heart of the system (`voxcore/orchestrator.py`, 266 lines). Key behaviors:

- **Multi-turn tool loop:** Sends user text + tool definitions to LLM. If LLM returns tool calls, executes each tool, appends results, and sends back. Repeats up to `LLM_MAX_TOOL_ROUNDS` (default: 5) times until a text response is returned.
- **Per-pipeline dedup cache:** `(tool_name, canonical_args) -> result` dictionary prevents the LLM from hammering a failed tool with identical arguments within the same cycle.
- **Failure guard:** Detects `{"ok": false}` in structured JSON tool results and injects an ephemeral system hint telling the LLM to answer from its own knowledge instead of retrying.
- **Turn-based conversation memory:** Stores history as `list[list[dict]]` — each turn is an atomic list of messages (user + optional tool calls + assistant). Trimmed to `LLM_MAX_HISTORY` turns. Tool call/result pairs are never split during trimming.
- **Safety valve:** If max tool rounds are reached without a text response, returns a hardcoded fallback: "I'm sorry, I wasn't able to complete that request."
- **Timing logs:** Every pipeline stage is timed and logged: `total`, `listen`, `stt`, `llm`, `tts`, `speak`.

### 3.4 Data Flow (single pipeline cycle)

```
1. wake_engine detects keyword
   → closes its audio stream (frees mic)
   → calls orchestrator.run_pipeline()

2. recorder.record_utterance()
   → opens PyAudio input stream
   → captures 16-bit PCM @ 16kHz until silence (energy-based VAD)
   → closes stream, returns raw bytes

3. stt.transcribe(audio_bytes)
   → wraps PCM in WAV container (in memory)
   → feeds to faster-whisper model
   → strips hallucination artifacts ([...], (...), ♪, ...)
   → returns clean text string

4. orchestrator._llm_tool_loop(user_text)
   → builds messages: [system_prompt] + [flattened history] + [user message]
   → sends to LLM with tool specs
   → LOOP: if tool_calls returned → execute each → append results → re-send
   → until text response or max rounds
   → saves complete turn to history

5. tts.synthesize(final_text)
   → POST to ElevenLabs REST API
   → receives raw PCM (22050 Hz or 24000 Hz)
   → wraps in WAV container
   → returns WAV bytes

6. recorder.play_wav(wav_bytes)
   → opens PyAudio output stream
   → plays WAV to completion
   → closes stream

7. Returns to idle → wake_engine reopens its stream
```

All data stays in memory. No files are written to disk at any step.

---

## 4. Dependencies

### 4.1 Python Packages (6 total)

| Package | Version | Purpose | Required |
|---|---|---|---|
| `python-dotenv` | >= 1.0.0 | Load `.env` file into `os.environ` | Yes |
| `pvporcupine` | >= 3.0.0 | Picovoice Porcupine wake word detection | Yes |
| `pyaudio` | >= 0.2.11 | Microphone capture and audio playback (wraps PortAudio) | Yes |
| `faster-whisper` | >= 1.1.0 | Local speech-to-text (CTranslate2-optimized Whisper) | Yes |
| `requests` | >= 2.31.0 | HTTP for Ollama, vLLM, ElevenLabs, and SearXNG | Yes |
| `openai` | >= 1.0.0 | OpenAI Python SDK | Only if `LLM_BACKEND=openai` |

### 4.2 System-Level Dependencies

| Dependency | Platform | Purpose |
|---|---|---|
| PortAudio | macOS (`brew install portaudio`), Linux (`apt install portaudio19-dev`) | Required by PyAudio |
| Docker + Docker Compose | All (optional) | Local SearXNG search instance |
| CUDA toolkit + NVIDIA drivers | Windows/Linux with NVIDIA GPU (optional) | GPU-accelerated Whisper STT |

### 4.3 Standard Library Modules Used

`os`, `io`, `re`, `sys`, `wave`, `struct`, `math`, `json`, `time`, `logging`, `pathlib`, `subprocess`, `random`, `dataclasses`, `datetime`, `typing`, `abc`

---

## 5. External Services and APIs

| Service | Purpose | Required | Free Tier | API Key Variable |
|---|---|---|---|---|
| **Picovoice** | Wake word detection engine | Yes | Yes (free key) | `PICOVOICE_ACCESS_KEY` |
| **ElevenLabs** | Cloud text-to-speech | Yes | Limited free quota | `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` |
| **OpenAI** | Cloud LLM (Chat Completions) | Only if `LLM_BACKEND=openai` | No | `OPENAI_API_KEY` |
| **Ollama** (local) | Local LLM server | Default backend | Free (open source) | None (runs locally) |
| **vLLM** (local) | GPU LLM inference server | Optional backend | Free (open source) | None (runs locally) |
| **SearXNG** (local/public) | Web search for the `web_search` tool | Optional | Free (open source + public instances) | None |

---

## 6. Hardware Requirements

| Component | Required | Notes |
|---|---|---|
| Microphone | Yes | Default input device; 16kHz 16-bit mono |
| Speaker / headphones | Yes | Default output device |
| NVIDIA GPU + CUDA | No (optional) | Accelerates Whisper STT; `float16` compute type. Without GPU, uses `int8` on CPU. |
| RAM | 4GB minimum | Whisper `large-v3` model needs ~3GB VRAM (CUDA) or ~3GB RAM (CPU). `small` model needs ~500MB. |
| Internet | Yes (for TTS) | ElevenLabs API calls require internet. LLM can run fully local via Ollama. |

---

## 7. Platform Compatibility

| Component | Windows | macOS | Linux |
|---|---|---|---|
| Core pipeline | Fully supported | Supported | Supported |
| Wake word (Porcupine) | Supported | Supported | Supported |
| Custom `.ppn` model | Windows model included | Requires macOS `.ppn` | Requires Linux `.ppn` |
| STT CUDA acceleration | Yes (NVIDIA GPU) | No (use CPU) | Yes (NVIDIA GPU) |
| STT CPU mode | Yes | Yes (including Apple Silicon ARM64) | Yes |
| TTS (ElevenLabs) | Yes | Yes | Yes |
| LLM backends | All three | All three | All three |
| `open_application` tool | Yes (`start`) | Yes (`open -a`) | Yes (direct spawn) |
| Web search | Yes | Yes | Yes |
| Docker/SearXNG | Yes | Yes | Yes |

---

## 8. Configuration System

All 40+ runtime settings are centralized in `voxcore/config.py` as a `Config` dataclass. No module reads `os.getenv()` directly — they all receive a `Config` object. Configuration is loaded from a `.env` file via `python-dotenv`.

### 8.1 Wake Word (8 variables)

| Variable | Default | Description |
|---|---|---|
| `WAKE_ENGINE` | `porcupine` | Engine (only `porcupine` supported) |
| `WAKE_KEYWORD` | `jarvis` | Built-in keyword |
| `WAKE_KEYWORD_PATH` | _(empty)_ | Custom `.ppn` model path (overrides keyword) |
| `WAKE_SENSITIVITY` | `0.5` | Detection threshold 0.0-1.0 |
| `PICOVOICE_ACCESS_KEY` | _(required)_ | Free key from console.picovoice.ai |
| `WAKE_CONFIRM_GATE` | `false` | Post-wake RMS energy check |
| `WAKE_CONFIRM_DURATION` | `0.8` | Seconds for confirmation capture |
| `WAKE_CONFIRM_RMS_THRESHOLD` | `200` | RMS floor for gate (0-32768) |

### 8.2 Speech-to-Text (7 variables)

| Variable | Default | Description |
|---|---|---|
| `STT_PROVIDER` | `whisper` | Provider (only `whisper` supported) |
| `WHISPER_MODEL` | `large-v3` | Model size: `tiny`/`base`/`small`/`medium`/`large-v3` |
| `WHISPER_DEVICE` | `cuda` | `cpu` or `cuda` |
| `WHISPER_LANG` | `en` | Language code or `auto` |
| `WHISPER_BEAM_SIZE` | `5` | Beam search width |
| `WHISPER_VAD_FILTER` | `true` | Silero VAD inside faster-whisper |
| `WHISPER_INITIAL_PROMPT` | _(empty)_ | Vocabulary hint for proper nouns |

### 8.3 LLM (15 variables)

| Variable | Default | Description |
|---|---|---|
| `LLM_BACKEND` | `ollama` | `ollama` / `vllm` / `openai` |
| `LLM_SYSTEM_PROMPT` | _(Amy persona)_ | Full system prompt (multiline) |
| `LLM_TEMPERATURE` | `0.6` | Sampling temperature |
| `LLM_TOP_P` | `0.9` | Nucleus sampling |
| `LLM_MAX_TOKENS` | `200` | Max response tokens |
| `LLM_MAX_TOOL_ROUNDS` | `5` | Max tool-call iterations |
| `LLM_MAX_HISTORY` | `10` | Rolling conversation turns |
| `OLLAMA_URL` | `http://127.0.0.1:11434/api/chat` | Ollama endpoint |
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct` | Ollama model |
| `OLLAMA_TIMEOUT` | `120` | Seconds |
| `VLLM_URL` | `http://127.0.0.1:8000/v1/chat/completions` | vLLM endpoint |
| `VLLM_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | vLLM model |
| `VLLM_TIMEOUT` | `60` | Seconds |
| `OPENAI_API_KEY` | _(empty)_ | Required only for openai backend |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model |
| `OPENAI_TIMEOUT` | `30` | Seconds |

### 8.4 Text-to-Speech (17 variables)

| Variable | Default | Description |
|---|---|---|
| `TTS_PROVIDER` | `elevenlabs` | `elevenlabs` or `elevenlabs_hybrid` |
| `ELEVENLABS_API_KEY` | _(required)_ | ElevenLabs key |
| `ELEVENLABS_VOICE_ID` | _(required)_ | Voice ID |
| `ELEVENLABS_MODEL_ID` | `eleven_flash_v2_5` | Single-model provider model |
| `ELEVENLABS_STABILITY` | `0.45` | Flash stability |
| `ELEVENLABS_SIMILARITY` | `0.85` | Flash similarity |
| `ELEVENLABS_STYLE` | `0.3` | Flash style |
| `TTS_MAX_CHARS` | `300` | Max chars per call |
| `TTS_FAST_MODEL` | `eleven_flash_v2_5` | Hybrid: short response model |
| `TTS_EMOTE_MODEL` | `eleven_v3` | Hybrid: expressive model |
| `TTS_MODE` | `hybrid` | `hybrid`/`flash_only`/`v3_only` |
| `TTS_EMOTION_DEFAULT` | `neutral` | Default emotion tag |
| `TTS_V3_STABILITY` | `0.70` | v3 stability (independent) |
| `TTS_V3_SIMILARITY` | `0.75` | v3 similarity |
| `TTS_V3_STYLE` | `0.05` | v3 style |
| `TTS_V3_TEXT_NORMALIZE` | `true` | Strip !/CAPS/emoji for v3 |
| `TTS_V3_SPEED` | `0.85` | v3 speaking rate |

### 8.5 Search (1 variable)

| Variable | Default | Description |
|---|---|---|
| `SEARX_INSTANCES` | `http://127.0.0.1:8080` + 4 public | Comma-separated SearXNG URLs |

### 8.6 Audio I/O (5 variables)

| Variable | Default | Description |
|---|---|---|
| `AUDIO_SAMPLE_RATE` | `16000` | Mic sample rate Hz |
| `AUDIO_CHUNK_SIZE` | `1024` | PyAudio buffer |
| `VAD_ENERGY_THRESHOLD` | `500` | Speech detection floor |
| `VAD_SILENCE_DURATION` | `2.0` | Silence before stop (seconds) |
| `RECORD_MAX_DURATION` | `15.0` | Max recording length (seconds) |

### 8.7 Logging (1 variable)

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Python logging level |

---

## 9. Built-in Tools

### 9.1 `get_current_datetime`

- **File:** `voxcore/tools/datetime_tool.py` (28 lines)
- **Trigger:** "What time is it?", "What's today's date?"
- **Parameters:** None
- **Returns:** Formatted string like `"Wednesday, March 15, 2026 at 02:30 PM"`
- **Dependencies:** None (standard library `datetime`)

### 9.2 `open_application`

- **File:** `voxcore/tools/open_app.py` (132 lines)
- **Trigger:** "Open Spotify", "Launch calculator"
- **Parameters:** `name` (string) — natural app name
- **Behavior:** Normalizes spoken name via per-platform alias table, launches via platform-appropriate command
- **Platform launch commands:** `start` (Windows), `open -a` (macOS), direct `Popen` (Linux)
- **Alias examples:** `calculator` maps to `calc` (Win) / `Calculator` (macOS) / `gnome-calculator` (Linux)
- **Cross-platform apps:** chrome, firefox, spotify, discord, vlc, vscode resolve per-platform automatically
- **Dependencies:** `subprocess`, `sys` (standard library)

### 9.3 `web_search`

- **File:** `voxcore/tools/web_search.py` (251 lines)
- **Trigger:** "Search for recent news about...", "What's happening with..."
- **Parameters:** `query` (string), `max_results` (int, default 3)
- **Behavior:** Queries SearXNG JSON API with health-aware instance selection
- **Instance selection:** Healthy instances shuffled randomly; unhealthy ones placed on per-failure-type cooldowns (429 rate limit: 5-15 min, DNS error: 10 min, timeout: 1-2 min)
- **Output format:** Structured JSON: `{"ok": true, "query": "...", "results": [...]}` on success, `{"ok": false, ...}` on failure
- **Query normalization:** Small alias table corrects common speech-recognition mishears before sending query
- **Dependencies:** `requests`

### 9.4 Tool Extension Pattern

Adding a new tool requires exactly 3 steps:

1. Create `voxcore/tools/your_tool.py` — subclass `BaseTool`, define `name`, `description`, `parameters` (JSON Schema), `execute()`
2. Import and register in `main.py`: `tool_registry.register(YourTool())`
3. No other files change. The LLM receives the tool spec automatically.

---

## 10. Hybrid TTS System Detail

The `HybridElevenLabsTTS` provider (416 lines) is the most complex module. Key capabilities:

- **Adaptive routing** — routes between Flash v2.5 (low latency) and v3 (expressive) based on:
  - Text length: <= 80 chars maps to Flash
  - ACK phrase detection: "got it", "sure", "opening", "done", etc. maps to Flash
  - All other responses map to v3
- **Emotion directives** — LLM can prefix response with `[emotion:tag]` (e.g., `[emotion:cheerful]`). Tag maps to a subtle style offset (max +0.15) applied to v3. Supported tags: neutral, cheerful, empathetic, excited, serious, playful, apologetic. Tags are stripped before synthesis.
- **Independent voice presets** — Flash and v3 have separate stability/similarity/style settings so tuning one does not affect the other
- **v3 text normalizer** — strips `!!!` to `.`, `ALL-CAPS` to `Title Case`, removes emoji before v3 synthesis (v3 over-reacts to these)
- **PCM format negotiation** — tries `pcm_22050` first for v3; if HTTP 422, retries with `pcm_24000`
- **Automatic Flash fallback** — any v3 failure falls back to Flash transparently; error logged as warning
- **Three routing modes:** `hybrid` (default, adaptive), `flash_only`, `v3_only`

---

## 11. LLM Backend Comparison

| Backend | Transport | Tool Call Format | Best For |
|---|---|---|---|
| **Ollama** | `requests.post` to `/api/chat` | Args as dict (normalized), IDs may be missing (auto-generated) | Local development, CPU-only machines |
| **vLLM** | `requests.post` to `/v1/chat/completions` | OpenAI-compatible, args as JSON string | GPU inference servers, Lambda Labs |
| **OpenAI** | Official `openai` SDK | Native OpenAI format, most reliable tool calling | Production, stable tool calling |

All three backends implement the same `LLMClient` ABC and return the same `LLMResponse` dataclass. The orchestrator is completely backend-agnostic.

---

## 12. Project History (ARVIS to VoxCore Migration)

**What was kept:** LLM module (refactored to Config injection), Whisper STT (refactored to bytes-based), ElevenLabs TTS (refactored to class), Porcupine wake word (restructured stream management), energy-based VAD, PyAudio recording loop.

**What was deleted:** FastAPI server, client/server split architecture, hardcoded Jarvis personality, Unreal Engine bridge, keyboard fallback, audio temp files, global state, hardcoded IP addresses, scattered `os.getenv()` calls, split requirements files.

**Key architectural changes:**

- Two processes merged into one process
- File-based audio replaced with in-memory bytes end-to-end
- Per-module env reads centralized into `Config` dataclass
- Only LLM had an ABC; now all four subsystems have ABCs + factories

**Future expansion hooks documented in MIGRATION.md:** Robotics (Unitree Go2), local LLM servers (llama.cpp), local TTS (Coqui/Piper), XR/Unreal Engine hooks via pipeline state signals.

---

## 13. Testing

A comprehensive 5-phase manual smoke test plan exists in `SMOKE_TEST.md` (605 lines):

- **Phase 0** — Pre-flight: `.env` verification, dependency check, LLM reachability, mic/speaker access
- **Phase 1** — Core pipeline: startup logs, wake detection, STT capture, LLM baseline (no tools), round-trip timing (target: under 10s)
- **Phase 2** — Tool execution: datetime tool, open_application tool, web_search tool, multi-tool single request
- **Phase 3** — Personality: brevity verification, no process disclosure, no filler phrases, dry tone
- **Phase 4** — Regression: repeated queries, empty utterance recovery, max tool rounds safety valve, clean shutdown
- **Phase 5** — New features: harvest wake word, hybrid TTS routing, confirmation gate, v3 voice character tuning

No automated test suite exists. All testing is manual via the smoke test plan.

---

## 14. File Manifest

```
VoxCore/
├── main.py                           93 lines   Entry point
├── requirements.txt                  26 lines   Python dependencies
├── .env.example                     250 lines   Full configuration template
├── MIGRATION.md                     173 lines   ARVIS → VoxCore migration notes
├── SMOKE_TEST.md                    605 lines   5-phase manual test plan
├── README.md                        495 lines   Project documentation
├── .gitignore
├── assets/
│   └── wakewords/
│       ├── .gitkeep
│       └── harvest_windows.ppn               Custom Porcupine wake word model (Windows)
├── docker/
│   ├── docker-compose.yml            23 lines   Local SearXNG instance
│   └── searxng/
│       └── settings.yml              28 lines   SearXNG configuration
├── docs/
│   └── TECHNICAL_REFERENCE.md                This file
└── voxcore/                                  Core package (~2,500 lines total)
    ├── __init__.py                            Namespace package
    ├── config.py                    186 lines  Centralized configuration
    ├── orchestrator.py              266 lines  Pipeline runner + tool loop
    ├── audio/
    │   ├── __init__.py
    │   └── recorder.py              107 lines  Mic capture + WAV playback
    ├── wake/
    │   ├── __init__.py
    │   ├── base.py                   41 lines  WakeWordEngine ABC
    │   ├── porcupine.py             207 lines  Porcupine implementation
    │   └── factory.py                30 lines  Engine selector
    ├── stt/
    │   ├── __init__.py
    │   ├── base.py                   30 lines  STTProvider ABC
    │   ├── whisper.py                92 lines  faster-whisper implementation
    │   └── factory.py                28 lines  Provider selector
    ├── llm/
    │   ├── __init__.py
    │   ├── base.py                   73 lines  LLMClient ABC + dataclasses
    │   ├── ollama.py                 73 lines  Ollama client
    │   ├── openai.py                 85 lines  OpenAI SDK client
    │   ├── vllm.py                   68 lines  vLLM client
    │   └── factory.py                40 lines  Backend selector
    ├── tts/
    │   ├── __init__.py
    │   ├── base.py                   31 lines  TTSProvider ABC
    │   ├── elevenlabs.py            103 lines  Flash v2.5 single-model
    │   ├── hybrid_elevenlabs.py     416 lines  Adaptive Flash/v3 routing
    │   └── factory.py                33 lines  Provider selector
    └── tools/
        ├── __init__.py
        ├── base.py                   55 lines  BaseTool ABC
        ├── registry.py               66 lines  ToolRegistry
        ├── datetime_tool.py          28 lines  get_current_datetime
        ├── open_app.py              132 lines  open_application (cross-platform)
        └── web_search.py            251 lines  web_search (SearXNG)
```
