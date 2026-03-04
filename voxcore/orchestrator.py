"""
VoxCore Pipeline Orchestrator

Full pipeline per wake-word detection:

    LISTEN -> STT -> LLM (+tools) -> TTS -> SPEAK

The LLM step is a multi-turn loop:

    1. Send user text + tool definitions to the LLM.
    2. If the LLM returns tool calls: execute each tool, append results,
       send the updated conversation back to the LLM. Repeat.
    3. Once the LLM returns a plain text response: send it to TTS.

Rolling conversation memory is maintained across pipeline invocations so
follow-up questions work correctly. History is capped at max_history
messages (oldest are dropped first) to keep token counts bounded.

This class is provider-agnostic and tool-agnostic.
Swapping any provider or adding/removing tools requires no changes here.
"""
import json
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


class Orchestrator:
    """
    Pipeline runner with tool-calling support and rolling conversation memory.

    Providers and the tool registry are injected at construction.
    run_pipeline() is the only public method; the wake engine calls it
    once per detection and blocks until the cycle is complete.

    Conversation history is stored in self.history and included in every
    LLM call so follow-up questions resolve correctly. History is capped
    at self.max_history messages; the oldest pair is dropped when full.
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

        # Rolling conversation memory — persists across pipeline invocations
        self.history: list = []
        self.max_history: int = 8  # keep last 8 messages (4 user/assistant pairs)

    def run_pipeline(self) -> None:
        """
        Execute one full listen -> process -> speak cycle.

        Errors are caught and logged so the wake engine resumes cleanly.
        """
        try:
            self._run()
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _run(self) -> None:
        # 1. Listen
        logger.info("[LISTENING]")
        audio_bytes = self.recorder.record_utterance()

        # 2. Transcribe
        logger.info("[STT]")
        user_text = self.stt.transcribe(audio_bytes)
        logger.info(f"  heard: {user_text!r}")

        if not user_text or len(user_text.strip()) < _MIN_TRANSCRIPT_LEN:
            logger.info("  (nothing detected - returning to idle)")
            return

        # 3. LLM + tool loop
        final_text = self._llm_tool_loop(user_text)
        logger.info(f"  final response: {final_text!r}")

        # 4. Synthesize
        logger.info("[TTS]")
        audio_out = self.tts.synthesize(final_text)

        # 5. Speak
        logger.info("[SPEAKING]")
        self.recorder.play_wav(audio_out)

        logger.info("[IDLE]")

    def _llm_tool_loop(self, user_text: str) -> str:
        """
        Run the multi-turn LLM + tool execution loop.

        Conversation is built as:
            [system prompt] + [rolling history] + [current user message]

        Each round:
          - If the LLM returns tool calls: execute them, append results, repeat.
          - If the LLM returns text: save the exchange to history and return it.
        Loop is capped at max_tool_rounds to prevent runaway chains.

        Returns the final natural language response string.
        """
        logger.info("[LLM]")

        # Build conversation: system + rolling history + current user turn
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.history)
        messages.append({"role": "user", "content": user_text})

        # Provide tool specs only if tools are registered
        tools = self.tool_registry.specs() if self.tool_registry else None

        for round_num in range(1, self.max_tool_rounds + 1):
            response = self.llm.chat(messages, tools=tools)

            # --- Final text response: save to history and return ---
            if not response.has_tool_calls:
                final_text = response.text or _FALLBACK_RESPONSE
                self.history.append({"role": "user",      "content": user_text})
                self.history.append({"role": "assistant", "content": final_text})
                self.history = self.history[-self.max_history:]
                return final_text

            # --- Tool calls: execute each and append results ---
            logger.info(f"  [TOOL ROUND {round_num}/{self.max_tool_rounds}]")

            # Append the assistant's tool_calls turn to the conversation
            messages.append({
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
            })

            # Execute each tool and append its result as a tool message
            for tc in response.tool_calls:
                logger.info(f"    -> {tc.name}({tc.arguments})")
                result = self.tool_registry.execute(tc.name, tc.arguments)
                logger.info(f"    <- {result!r}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        # Safety valve: max rounds reached without a text response
        logger.warning(f"Max tool rounds ({self.max_tool_rounds}) reached without final response.")
        return _FALLBACK_RESPONSE
