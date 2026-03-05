"""
VoxCore Pipeline Orchestrator

Full pipeline per wake-word detection:

    LISTEN -> STT -> LLM (+tools) -> TTS -> SPEAK

The LLM step is a multi-turn loop:

    1. Send user text + tool definitions to the LLM.
    2. If the LLM returns tool calls: execute each tool, append results,
       send the updated conversation back to the LLM. Repeat.
    3. Once the LLM returns a plain text response: send it to TTS.

Conversation memory is stored as a list of turns. Each turn is a list of
messages forming one complete exchange (user + optional tool calls + assistant).
This ensures tool call/result pairs are never split during trimming.
"""
import json
import time
import logging
from typing import Optional

from voxcore.config import Config
from voxcore.stt.base import STTProvider
from voxcore.llm.base import LLMClient
from voxcore.tts.base import TTSProvider
from voxcore.audio.recorder import Recorder
from voxcore.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_MIN_TRANSCRIPT_LEN = 3
_FALLBACK_RESPONSE = "I'm sorry, I wasn't able to complete that request."
_ERROR_RESPONSE = "Something went wrong."

# Injected into the conversation when a tool (e.g. web_search) signals failure,
# so the LLM answers from its own knowledge instead of retrying the same call.
_SEARCH_UNAVAILABLE_HINT = (
    "Web search is currently unavailable. "
    "Answer the user's question using your own knowledge. "
    "Do not attempt another web search. "
    "Be explicit that you could not verify with live data."
)


class Orchestrator:
    """
    Pipeline runner with tool-calling support and turn-based conversation memory.

    Providers and the tool registry are injected at construction.
    run_pipeline() is the only public method; the wake engine calls it
    once per detection and blocks until the cycle is complete.

    Conversation history is stored as a list of turns, where each turn
    is a list of OpenAI-format messages. This preserves tool call/result
    pairs as atomic units that are never split during trimming.
    """

    def __init__(
        self,
        stt: STTProvider,
        llm: LLMClient,
        tts: TTSProvider,
        recorder: Recorder,
        config: Config,
        tool_registry: Optional[ToolRegistry] = None,
    ):
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.recorder = recorder
        self.system_prompt = config.llm_system_prompt
        self.tool_registry = tool_registry
        self.max_tool_rounds = config.llm_max_tool_rounds

        # Turn-based conversation memory — each turn is a list of messages
        self.turns: list[list[dict]] = []
        self.max_turns: int = config.llm_max_history

    def run_pipeline(self) -> None:
        """
        Execute one full listen -> process -> speak cycle.

        Pipeline errors are caught, logged, and spoken back to the user.
        """
        try:
            self._run()
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            self._speak_error()

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _run(self) -> None:
        t0 = time.perf_counter()

        # 1. Listen
        logger.info("[LISTENING]")
        audio_bytes = self.recorder.record_utterance()
        t1 = time.perf_counter()

        # 2. Transcribe
        logger.info("[STT]")
        user_text = self.stt.transcribe(audio_bytes)
        t2 = time.perf_counter()
        logger.info(f"  heard: {user_text!r}  ({t2 - t1:.2f}s)")

        if not user_text or len(user_text.strip()) < _MIN_TRANSCRIPT_LEN:
            logger.info("  (nothing detected — returning to idle)")
            return

        # 3. LLM + tool loop
        final_text = self._llm_tool_loop(user_text)
        t3 = time.perf_counter()
        logger.info(f"  response: {final_text!r}  ({t3 - t2:.2f}s)")

        # 4. Synthesize
        logger.info("[TTS]")
        audio_out = self.tts.synthesize(final_text)
        t4 = time.perf_counter()

        # 5. Speak
        logger.info("[SPEAKING]")
        self.recorder.play_wav(audio_out)
        t5 = time.perf_counter()

        logger.info(
            f"[IDLE] total={t5 - t0:.2f}s "
            f"(listen={t1 - t0:.2f}, stt={t2 - t1:.2f}, "
            f"llm={t3 - t2:.2f}, tts={t4 - t3:.2f}, speak={t5 - t4:.2f})"
        )

    def _llm_tool_loop(self, user_text: str) -> str:
        """
        Run the multi-turn LLM + tool execution loop.

        Conversation is built as:
            [system prompt] + [flattened turn history] + [current user message]

        Each round:
          - If the LLM returns tool calls: execute them, append results, repeat.
          - If the LLM returns text: save the full turn to history and return it.
        Loop is capped at max_tool_rounds to prevent runaway chains.

        Dedup cache: identical tool calls within the same pipeline run return
        the cached result immediately, preventing the LLM from hammering a
        failed tool with the same arguments.

        Failure guard: when a tool returns structured JSON with "ok": false
        (or non-JSON output), a system hint is injected telling the LLM to
        answer from its own knowledge instead of retrying.

        Returns the final natural language response string.
        """
        logger.info("[LLM]")

        # Build conversation: system + flattened past turns + current user turn
        messages = [{"role": "system", "content": self.system_prompt}]
        for turn in self.turns:
            messages.extend(turn)
        messages.append({"role": "user", "content": user_text})

        # Track messages for the current turn (for saving to history)
        current_turn: list[dict] = [{"role": "user", "content": user_text}]

        # Provide tool specs only if tools are registered
        tools = self.tool_registry.specs() if self.tool_registry else None

        # Per-pipeline dedup cache: (tool_name, canonical_args) -> result
        tool_cache: dict[tuple, str] = {}

        for round_num in range(1, self.max_tool_rounds + 1):
            response = self.llm.chat(messages, tools=tools)

            # --- Final text response: save turn to history and return ---
            if not response.has_tool_calls:
                final_text = response.text or _FALLBACK_RESPONSE
                current_turn.append({"role": "assistant", "content": final_text})
                self.turns.append(current_turn)
                if len(self.turns) > self.max_turns:
                    self.turns = self.turns[-self.max_turns:]
                return final_text

            # --- Tool calls: execute each and append results ---
            logger.info(f"  [TOOL ROUND {round_num}/{self.max_tool_rounds}]")

            # Append the assistant's tool_calls turn to both lists
            tc_msg: dict = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(tc_msg)
            current_turn.append(tc_msg)

            # Execute each tool and append its result
            for tc in response.tool_calls:
                cache_key = (tc.name, json.dumps(tc.arguments, sort_keys=True))

                if cache_key in tool_cache:
                    result = tool_cache[cache_key]
                    logger.info(f"    -> {tc.name}({tc.arguments})  [CACHED]")
                else:
                    logger.info(f"    -> {tc.name}({tc.arguments})")
                    result = self.tool_registry.execute(tc.name, tc.arguments)
                    tool_cache[cache_key] = result
                    logger.info(f"    <- {result!r}")

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                }
                messages.append(tool_msg)
                current_turn.append(tool_msg)

                # Failure guard: if the tool signals failure, inject a hint
                # so the LLM answers from knowledge instead of retrying.
                if self._is_tool_failure(result):
                    logger.info(f"    [FAILURE DETECTED] injecting search-unavailable hint")
                    messages.append({
                        "role": "system",
                        "content": _SEARCH_UNAVAILABLE_HINT,
                    })
                    # NOT appended to current_turn — ephemeral steering only

        # Safety valve: max rounds reached without a text response
        logger.warning(f"Max tool rounds ({self.max_tool_rounds}) reached without final response.")
        return _FALLBACK_RESPONSE

    @staticmethod
    def _is_tool_failure(result: str) -> bool:
        """
        Detect whether a tool result signals failure.

        Checks for structured JSON with "ok": false. If the result is not
        valid JSON (e.g. HTML error page, plaintext), it is also treated
        as a failure.
        """
        try:
            data = json.loads(result)
            return isinstance(data, dict) and data.get("ok") is False
        except (json.JSONDecodeError, TypeError):
            # Non-JSON output from a tool that should return JSON → failure
            return False

    def _speak_error(self) -> None:
        """Best-effort: speak an error message. Fails silently if TTS is broken too."""
        try:
            audio = self.tts.synthesize(_ERROR_RESPONSE)
            self.recorder.play_wav(audio)
        except Exception as e:
            logger.warning(f"Could not speak error: {e}")
