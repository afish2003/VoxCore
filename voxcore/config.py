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
    wake_keyword: str       # e.g. "jarvis", "computer", "alexa"
    wake_sensitivity: float
    picovoice_access_key: str

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
    tts_provider: str       # "elevenlabs"
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_model_id: str
    elevenlabs_stability: float
    elevenlabs_similarity: float
    elevenlabs_style: float
    tts_max_chars: int

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

        # Search
        searx_instances=[
            u.strip()
            for u in os.getenv(
                "SEARX_INSTANCES",
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
