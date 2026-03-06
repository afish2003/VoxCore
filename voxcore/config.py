"""
VoxCore Configuration

All runtime settings are loaded from environment variables (via .env).
Centralized here so no individual module reads os.getenv() directly.

To swap any provider, change the corresponding value in .env.
No orchestration code ever needs to change.
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # --- Wake Word ---
    wake_engine: str        # "porcupine"
    wake_keyword: str       # e.g. "jarvis", "computer", "alexa" (built-in)
    wake_sensitivity: float
    picovoice_access_key: str
    # Custom .ppn model — overrides wake_keyword when set
    wake_keyword_path: str  # path to .ppn file; empty = use built-in keyword
    wake_confirm_gate: bool     # post-wake energy gate; default False
    wake_confirm_duration: float  # seconds to capture for gate; default 0.8
    wake_confirm_rms_threshold: int  # RMS floor for gate (mic-dependent); default 200

    # --- Speech-to-Text ---
    stt_provider: str       # "whisper"
    whisper_model: str      # tiny / base / small / medium / large-v3
    whisper_device: str     # cpu / cuda
    whisper_lang: str       # e.g. "en", or "auto"
    whisper_beam_size: int
    whisper_vad_filter: bool
    whisper_initial_prompt: str

    # --- LLM ---
    llm_backend: str        # "ollama" / "vllm" / "openai"
    llm_system_prompt: str
    llm_temperature: float
    llm_top_p: float
    llm_max_tokens: int
    llm_max_tool_rounds: int  # max tool-call iterations before giving up
    llm_max_history: int      # max conversation turns to keep

    vllm_url: str
    vllm_model: str
    vllm_timeout: int

    ollama_url: str
    ollama_model: str
    ollama_timeout: int

    openai_api_key: str
    openai_model: str
    openai_timeout: int

    # --- Text-to-Speech ---
    tts_provider: str       # "elevenlabs" | "elevenlabs_hybrid"
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_model_id: str
    elevenlabs_stability: float
    elevenlabs_similarity: float
    elevenlabs_style: float
    tts_max_chars: int
    # Hybrid TTS routing (used by elevenlabs_hybrid provider)
    tts_fast_model: str     # model for short/utility responses
    tts_emote_model: str    # model for expressive/narrative responses
    tts_mode: str           # "hybrid" | "flash_only" | "v3_only"
    tts_emotion_default: str  # default emotion when no [emotion:tag] present
    # v3-specific voice settings — independent of Flash (ELEVENLABS_*) settings.
    # v3 reacts much more strongly to low stability; keep it high for calm delivery.
    tts_v3_stability: float      # default 0.80 (vs Flash's 0.45)
    tts_v3_similarity: float     # default 0.75
    tts_v3_style: float          # default 0.0 (expressiveness off by default)
    tts_v3_text_normalize: bool  # strip !/ALL-CAPS/emojis before v3 synthesis

    # --- Search ---
    searx_instances: list   # ordered list of SearX base URLs

    # --- Audio I/O ---
    sample_rate: int
    channels: int
    chunk_size: int
    vad_energy_threshold: int
    vad_silence_duration: float
    record_max_duration: float

    # --- Logging ---
    log_level: str


def load_config() -> Config:
    """Load all configuration from environment variables."""
    return Config(
        # Wake word
        wake_engine=os.getenv("WAKE_ENGINE", "porcupine"),
        wake_keyword=os.getenv("WAKE_KEYWORD", "jarvis"),
        wake_sensitivity=float(os.getenv("WAKE_SENSITIVITY", "0.5")),
        picovoice_access_key=os.getenv("PICOVOICE_ACCESS_KEY", ""),
        wake_keyword_path=os.getenv("WAKE_KEYWORD_PATH", ""),
        wake_confirm_gate=os.getenv("WAKE_CONFIRM_GATE", "false").lower() == "true",
        wake_confirm_duration=float(os.getenv("WAKE_CONFIRM_DURATION", "0.8")),
        wake_confirm_rms_threshold=int(os.getenv("WAKE_CONFIRM_RMS_THRESHOLD", "200")),

        # STT
        stt_provider=os.getenv("STT_PROVIDER", "whisper"),
        whisper_model=os.getenv("WHISPER_MODEL", "large-v3"),
        whisper_device=os.getenv("WHISPER_DEVICE", "cuda"),
        whisper_lang=os.getenv("WHISPER_LANG", "en"),
        whisper_beam_size=int(os.getenv("WHISPER_BEAM_SIZE", "5")),
        whisper_vad_filter=os.getenv("WHISPER_VAD_FILTER", "true").lower() == "true",
        whisper_initial_prompt=os.getenv("WHISPER_INITIAL_PROMPT", ""),

        # LLM
        llm_backend=os.getenv("LLM_BACKEND", "ollama"),
        llm_system_prompt=os.getenv(
            "LLM_SYSTEM_PROMPT",
            "You are a concise, helpful voice assistant. Keep responses under three sentences.",
        ),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.6")),
        llm_top_p=float(os.getenv("LLM_TOP_P", "0.9")),
        llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "200")),
        llm_max_tool_rounds=int(os.getenv("LLM_MAX_TOOL_ROUNDS", "5")),
        llm_max_history=int(os.getenv("LLM_MAX_HISTORY", "10")),

        vllm_url=os.getenv("VLLM_URL", "http://127.0.0.1:8000/v1/chat/completions"),
        vllm_model=os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
        vllm_timeout=int(os.getenv("VLLM_TIMEOUT", "60")),

        ollama_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct"),
        ollama_timeout=int(os.getenv("OLLAMA_TIMEOUT", "120")),

        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        openai_timeout=int(os.getenv("OPENAI_TIMEOUT", "30")),

        # TTS
        tts_provider=os.getenv("TTS_PROVIDER", "elevenlabs"),
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", ""),
        elevenlabs_model_id=os.getenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5"),
        elevenlabs_stability=float(os.getenv("ELEVENLABS_STABILITY", "0.45")),
        elevenlabs_similarity=float(os.getenv("ELEVENLABS_SIMILARITY", "0.85")),
        elevenlabs_style=float(os.getenv("ELEVENLABS_STYLE", "0.3")),
        tts_max_chars=int(os.getenv("TTS_MAX_CHARS", "300")),
        # Hybrid TTS routing
        tts_fast_model=os.getenv("TTS_FAST_MODEL", "eleven_flash_v2_5"),
        tts_emote_model=os.getenv("TTS_EMOTE_MODEL", "eleven_v3"),
        tts_mode=os.getenv("TTS_MODE", "hybrid"),
        tts_emotion_default=os.getenv("TTS_EMOTION_DEFAULT", "neutral"),
        # v3 voice preset
        tts_v3_stability=float(os.getenv("TTS_V3_STABILITY", "0.70")),
        tts_v3_similarity=float(os.getenv("TTS_V3_SIMILARITY", "0.75")),
        tts_v3_style=float(os.getenv("TTS_V3_STYLE", "0.05")),
        tts_v3_text_normalize=os.getenv("TTS_V3_TEXT_NORMALIZE", "true").lower() == "true",

        # Search — local Docker instance first, public fallbacks after
        searx_instances=[
            u.strip()
            for u in os.getenv(
                "SEARX_INSTANCES",
                "http://127.0.0.1:8080,"
                "https://searx.tiekoetter.com,https://search.sapti.me,"
                "https://searx.bndkt.io,https://searx.fmac.xyz",
            ).split(",")
            if u.strip()
        ],

        # Audio I/O
        sample_rate=int(os.getenv("AUDIO_SAMPLE_RATE", "16000")),
        channels=1,
        chunk_size=int(os.getenv("AUDIO_CHUNK_SIZE", "1024")),
        vad_energy_threshold=int(os.getenv("VAD_ENERGY_THRESHOLD", "500")),
        vad_silence_duration=float(os.getenv("VAD_SILENCE_DURATION", "2.0")),
        record_max_duration=float(os.getenv("RECORD_MAX_DURATION", "15.0")),

        # Logging
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
