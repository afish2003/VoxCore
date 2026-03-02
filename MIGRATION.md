MIGRATION NOTES: ARVIS -> VoxCore
==================================

Source repo: ARVIS / voice-pipeline
Target repo: VoxCore


WHAT WAS KEPT
-------------

LLM module (server/llm/)
  - base.py     -> voxcore/llm/base.py    (kept as-is; already had clean ABC)
  - vllm.py     -> voxcore/llm/vllm.py    (refactored: reads Config instead of os.getenv)
  - ollama.py   -> voxcore/llm/ollama.py  (refactored: reads Config instead of os.getenv)
  - factory.py  -> voxcore/llm/factory.py (refactored: accepts Config argument)

Whisper STT (server/stt/whisper.py)
  - Core transcription logic kept.
  - Global _model variable removed; model now owned by WhisperSTT class instance.
  - File-path-based interface replaced with bytes-based interface (no disk writes).

ElevenLabs TTS (server/tts/elevenlabs.py)
  - Core API call kept.
  - Refactored from a standalone function to a class (ElevenLabsTTS).
  - Returns bytes instead of saving to disk (no temp files in single-process mode).
  - Credit-safety logic retained (MAX_TTS_CHARS).

Porcupine wake word (client/wake_word.py)
  - WakeWordDetector core logic kept.
  - Restructured so the audio stream is closed before calling the pipeline callback
    and reopened after, preventing device conflicts on Windows.

SimpleVAD energy-based detection (client/wake_word.py -> audio/recorder.py)
  - Energy calculation and threshold logic kept unchanged.

PyAudio recording loop (client/arvis_client.py)
  - record_audio() logic kept (VAD-driven stop, max_duration cap).
  - Added WAV playback (play_wav()) using the same PyAudio approach.


WHAT WAS DELETED
----------------

FastAPI server (server/main.py)
  - Entire HTTP server removed. VoxCore is a single-process system.
  - No /voice_chat, /stt, /voice_text, /audio endpoints.
  - Rate limiting deque removed (not needed without HTTP API).

Client/server split architecture
  - ARVIS ran as two separate processes (server + client).
  - VoxCore is one process: wake -> record -> process -> speak -> idle.

Hardcoded Jarvis personality (VOICE_SYSTEM_PROMPT in server/main.py)
  - The Jarvis persona is gone. System prompt is now a .env variable
    (LLM_SYSTEM_PROMPT) with no hardcoded default personality.

Unreal Engine bridge (client/unreal_bridge.py)
  - Flask HTTP state server removed.
  - XR/Unreal-specific callback wiring removed from core.
  - The architecture allows re-adding an XR hook later as an external
    observer without changing the orchestrator.

KeyboardFallback class (client/wake_word.py)
  - Removed from core. Can be added back as a WakeWordEngine subclass
    if needed for testing without a microphone.

Audio temp files
  - ARVIS wrote temp_input.wav and temp_output.wav to disk.
  - VoxCore keeps all audio in memory (bytes) end-to-end.

Global state
  - global _model in server/stt/whisper.py -> removed.
  - global app_state in client/unreal_bridge.py -> removed.
  - global llm_client in server/main.py -> removed.
  - global voice_call_times deque -> removed.

Hardcoded IP address
  - ARVISClient defaulted to server_url="http://192.168.1.100:8001".
  - Removed entirely (no HTTP server in VoxCore).

Environment variable reads scattered across modules
  - Each ARVIS module called os.getenv() directly.
  - VoxCore centralizes all env reads in voxcore/config.py.

Requirements split (requirements-server.txt + requirements-client.txt)
  - Merged into a single requirements.txt.
  - FastAPI, uvicorn, flask, flask-cors removed (no HTTP server).
  - keyboard package removed (KeyboardFallback not included in core).


WHAT WAS REFACTORED
-------------------

Architecture: client/server -> single process
  ARVIS: two Python processes communicating over HTTP.
  VoxCore: one Python process; providers are imported directly.

Dependency injection
  ARVIS: providers instantiated inside the HTTP handler functions.
  VoxCore: providers created once in main.py and injected into Orchestrator.

Configuration
  ARVIS: each module read os.getenv() independently.
  VoxCore: all env reads happen in load_config(). Modules accept a Config object.

STT interface
  ARVIS: transcribe_audio(path: str) -> (text, language)  [file on disk]
  VoxCore: STTProvider.transcribe(audio_bytes: bytes) -> str  [in memory]

TTS interface
  ARVIS: synthesize_speech(text, out_dir) -> filename  [file on disk]
  VoxCore: TTSProvider.synthesize(text) -> bytes  [in memory]

Wake word interface
  ARVIS: WakeWordDetector kept its audio stream open during callback.
  VoxCore: PorcupineEngine closes and recreates its stream around each
           callback so the Recorder can use the mic without conflict.

Provider abstraction
  ARVIS: only LLM had a base class (LLMClient ABC).
  VoxCore: all four providers have ABCs: WakeWordEngine, STTProvider,
           LLMClient, TTSProvider. Each factory reads config to select
           the implementation at startup.


HOW TO SWAP PROVIDERS
---------------------

All provider selection happens in .env. No Python code changes are needed
to swap any provider, as long as the new implementation exists and is
registered in the corresponding factory.

To swap the LLM backend:
  1. Set LLM_BACKEND=vllm (or ollama) in .env
  2. Set the matching connection variables (VLLM_URL, VLLM_MODEL, etc.)
  3. Restart. Done.

To add a new LLM backend (e.g. OpenAI, Anthropic, local llama.cpp):
  1. Create voxcore/llm/openai.py
  2. class OpenAIClient(LLMClient): implement generate()
  3. Add the case to voxcore/llm/factory.py
  4. Set LLM_BACKEND=openai in .env

Same pattern applies to STT, TTS, and wake word:
  - New file in the matching subdirectory
  - Subclass the base class
  - Add one case to the factory
  - Set the provider variable in .env

The Orchestrator and main.py never change when swapping providers.


FUTURE EXPANSION HOOKS
----------------------

Robotics (e.g. Unitree Go2)
  After orchestrator.run_pipeline() returns, main.py can forward the
  transcript and response to a robotics controller. The Orchestrator
  could be extended to emit structured output (JSON) alongside audio.

Local LLM servers (llama.cpp, LM Studio, Ollama)
  Ollama is already supported. For llama.cpp server, add a new LLMClient
  subclass that calls its OpenAI-compatible endpoint (same pattern as vllm.py).

Local TTS (Coqui, Piper, Bark)
  Create voxcore/tts/coqui.py, subclass TTSProvider, return WAV bytes.

XR / Unreal Engine hooks
  The pipeline state transitions ([LISTENING], [STT], etc.) are logged.
  An XR bridge can subscribe to a lightweight state signal emitted by
  Orchestrator._run() without modifying core logic. The old unreal_bridge.py
  pattern (Flask + polling) can be revived as a side-car if needed.
