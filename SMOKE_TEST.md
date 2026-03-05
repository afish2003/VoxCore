# VoxCore Smoke Test Plan

Single-session, local mode.
Run after a clean environment setup.
Tests are sequential — a failure in an earlier phase will block later phases.

---

## PHASE 0 — Pre-flight Checks

Complete all of these before starting the system.

---

### 0.1 — Verify .env file exists and is populated

```
ls .env
```

Expected: file exists (not `.env.example`).

```
grep PICOVOICE_ACCESS_KEY .env
grep ELEVENLABS_API_KEY .env
grep ELEVENLABS_VOICE_ID .env
```

Expected: all three lines print a real value, not `your_*_here`.

Failure symptom: "PICOVOICE_ACCESS_KEY not set" or
"ELEVENLABS_API_KEY is not set" errors on startup.
Cause: .env was not copied from .env.example, or credentials were
not filled in.

---

### 0.2 — Verify dependencies are installed

```
pip show pvporcupine faster-whisper pyaudio requests python-dotenv
```

Expected: all five packages print a version.

Failure symptom: "ModuleNotFoundError" on startup.
Fix:
```
pip install -r requirements.txt
```

If pyaudio fails on Windows:
```
pip install PyAudio-0.2.14-cp311-cp311-win_amd64.whl
```
(Download wheel from https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio)

---

### 0.3 — Verify the LLM backend is reachable

**Ollama (default):**
```
curl http://127.0.0.1:11434/api/tags
```
Expected: JSON response listing available models.

Failure symptom: "Connection refused" or timeout.
Fix: `ollama serve` in a separate terminal. Confirm the model is pulled:
```
ollama pull qwen2.5:7b-instruct
```

**vLLM (if LLM_BACKEND=vllm):**
```
curl http://127.0.0.1:8000/v1/models
```
Expected: JSON listing the loaded model.
Failure symptom: Connection refused. Fix: start the vLLM server process.

---

### 0.4 — Verify microphone is accessible

```python
python -c "import pyaudio; p = pyaudio.PyAudio(); print(p.get_default_input_device_info()); p.terminate()"
```

Expected: prints device info including `name` and `maxInputChannels > 0`.

Failure symptom: `OSError: [Errno -9996] Invalid input device`.
Fix: check Windows sound settings, ensure the correct mic is set as default.

---

### 0.5 — Verify audio output is accessible

```python
python -c "import pyaudio; p = pyaudio.PyAudio(); print(p.get_default_output_device_info()); p.terminate()"
```

Expected: prints device info with `maxOutputChannels > 0`.

Failure symptom: `OSError` on playback.
Fix: check Windows sound settings, ensure speakers/headphones are default output.

---

## PHASE 1 — Core Pipeline Test

Start the system:
```
python main.py
```

Watch the console. Leave it running for all remaining tests.

---

### 1.1 — Startup log verification

Expected log output within 5 seconds of launch:

```
VoxCore Starting
  Wake engine : porcupine (JARVIS)
  STT         : whisper (small)
  LLM         : ollama
  TTS         : elevenlabs
  Tools       : 3 registered
Tool registered: 'get_current_datetime'
Tool registered: 'open_application'
Tool registered: 'web_search'
Whisper model ready
Ollama client ready: ...
ElevenLabs TTS ready ...
Listening for wake word: 'JARVIS'
[IDLE]
```

Failure symptoms and causes:

| Symptom | Likely cause |
|---|---|
| `pvporcupine.PorcupineInvalidArgumentError` | Bad or missing PICOVOICE_ACCESS_KEY |
| `RuntimeError: ELEVENLABS_API_KEY is not set` | Missing key in .env |
| `Connection refused` during Ollama init | Ollama server not running |
| `ModuleNotFoundError: faster_whisper` | pip install not done |
| System hangs after "Whisper model ready" | Whisper model still downloading |

---

### 1.2 — Wake word detection

**Action:** Say clearly: `"JARVIS"`

Expected log:
```
Wake word detected: 'JARVIS'
[LISTENING]
```

Expected behavior: system transitions from idle to listening.
The wake engine's audio stream closes; the recorder opens a new stream.

Failure symptoms:

| Symptom | Likely cause |
|---|---|
| No response to wake word | Wrong WAKE_KEYWORD in .env, or mic not working |
| Immediate crash after detection | PyAudio device conflict — check that no other app holds the mic exclusively |
| Continuous false triggers | WAKE_SENSITIVITY too high — lower to 0.3 in .env |
| `PorcupineActivationError` | Picovoice key expired or exceeded free tier |

---

### 1.3 — STT capture

**Action:** After `[LISTENING]` appears, say: `"Hello"`

Expected log:
```
[STT]
  heard: 'Hello'
```

Expected behavior: Whisper transcribes the word. The text may vary
slightly ("hello" / "Hello.") — that is normal.

Failure symptoms:

| Symptom | Likely cause |
|---|---|
| `heard: ''` (empty) | Mic too quiet — raise VAD_ENERGY_THRESHOLD or increase mic gain in Windows |
| `heard: '[BLANK_AUDIO]'` or garbled text | Whisper model too small — try WHISPER_MODEL=base or small |
| System hangs at `[STT]` | faster-whisper loading first model — wait up to 30s on first run |
| `heard` shows only noise | VAD_ENERGY_THRESHOLD too low — raise to 800 or 1000 |

---

### 1.4 — LLM baseline (no tool call expected)

**Action:** Say the wake word, then: `"Who was the first person to walk on the moon?"`

Expected log:
```
[LLM]
  final response: 'Neil Armstrong. 1969.'
[TTS]
[SPEAKING]
[IDLE]
```

Expected behavior: LLM responds without calling any tool. Audio plays.
Amy's response should be one short sentence, no filler.

Failure symptoms:

| Symptom | Likely cause |
|---|---|
| `ConnectionRefusedError` at `[LLM]` | LLM backend not running |
| `[TOOL ROUND 1/5]` appears | Model called a tool unnecessarily — adjust system prompt or use a larger model |
| `[TTS]` reached but no audio plays | ElevenLabs API key invalid, or Windows audio output misconfigured |
| `requests.exceptions.HTTPError: 401` | Bad ELEVENLABS_API_KEY |
| `requests.exceptions.HTTPError: 422` | Bad ELEVENLABS_VOICE_ID |

---

### 1.5 — Full round-trip timing

**Action:** Note wall-clock time from `[LISTENING]` to `[IDLE]`.

Expected: under 10 seconds on a local Ollama setup.

If over 10 seconds:
- STT slow → try WHISPER_MODEL=tiny for testing
- LLM slow → Ollama model too large for CPU; try llama3.2:3b-instruct
- TTS slow → ElevenLabs network latency; expected ~1-3s

---

## PHASE 2 — Tool Execution Test

---

### 2.1 — get_current_datetime tool

**Action:** Say the wake word, then: `"What time is it?"`

Expected log:
```
[LLM]
  [TOOL ROUND 1/5]
    -> get_current_datetime({})
    <- 'Wednesday, March 04, 2026 at 02:15 PM'
  final response: '2:15 PM.'
[TTS]
[SPEAKING]
[IDLE]
```

Expected audio: Amy speaks the time. One sentence. No filler.

Failure symptoms:

| Symptom | Likely cause |
|---|---|
| No `[TOOL ROUND]` in log | Model did not call the tool — it answered from training data. Try a model with stronger tool-calling support (e.g. qwen2.5:7b-instruct) |
| `Error: tool 'get_current_datetime' is not available` | Tool not registered in main.py |
| `[TOOL ROUND]` loops repeatedly | Model calling tool in a loop — check LLM_MAX_TOOL_ROUNDS is set to 5 |

---

### 2.2 — open_application tool

**Action:** Say the wake word, then: `"Open Notepad"`

Expected log:
```
[LLM]
  [TOOL ROUND 1/5]
    -> open_application({'name': 'notepad'})
    <- 'Opened Notepad.'
  final response: 'Opening Notepad.'
[TTS]
[SPEAKING]
[IDLE]
```

Expected behavior: Notepad opens on the desktop. Amy's spoken response
confirms the action.

Failure symptoms:

| Symptom | Likely cause |
|---|---|
| No `[TOOL ROUND]` | Model answered without calling tool — rephrase as "Launch Notepad" |
| `Opened Notepad.` in log but app does not open | Windows execution policy — try running terminal as administrator |
| Tool called with wrong app name | Model hallucinated a different app name; check the alias map in open_app.py |

---

### 2.3 — web_search tool

**Action:** Say the wake word, then: `"Search for what is the capital of Japan"`

Expected log:
```
[LLM]
  [TOOL ROUND 1/5]
    -> web_search({'query': 'capital of Japan'})
    <- 'Tokyo is the capital of Japan. ...'
  final response: 'Tokyo.'
[TTS]
[SPEAKING]
[IDLE]
```

Expected behavior: DuckDuckGo returns an abstract result.
Amy delivers a concise spoken answer.

Failure symptoms:

| Symptom | Likely cause |
|---|---|
| `Search failed: ...` in tool result | No internet connection, or DuckDuckGo rate-limiting |
| `No results found for: ...` | Query too vague or DuckDuckGo returned no abstract — try a more specific query |
| Tool result is long but Amy speaks a paragraph | Model not compressing the result — check that LLM_MAX_TOKENS=200 and system prompt is loaded correctly |

---

### 2.4 — Multi-tool single request

**Action:** Say the wake word, then:
`"What time is it and open the calculator"`

Expected log:
```
[LLM]
  [TOOL ROUND 1/5]
    -> get_current_datetime({})
    <- '...'
    -> open_application({'name': 'calculator'})
    <- 'Opened calculator.'
  final response: 'Opening Calculator. 2:15 PM.'
[SPEAKING]
[IDLE]
```

Expected behavior: Calculator opens. Amy delivers both results in one
brief statement. No filler, no explanation.

Note: some models issue tool calls sequentially across two rounds rather
than in parallel. Both are acceptable. The final response should still
be one short sentence.

---

## PHASE 3 — Personality Behavior Test

These tests verify the Amy persona is applied correctly.
There are no pass/fail log checks — evaluate the spoken output.

---

### 3.1 — Brevity on factual query

**Action:** Say the wake word, then: `"Who was Albert Einstein?"`

Expected: one sentence, under 20 words. No "Great question." No "Of course."
Failure symptom: multi-sentence paragraph response.
Fix: verify LLM_SYSTEM_PROMPT in .env loaded correctly. Check log for
`system_prompt` being set — add a DEBUG log temporarily if needed.

---

### 3.2 — No process disclosure

**Action:** Say the wake word, then: `"How did you find that information?"`

Expected: Amy does not mention the web search, the tool, or any internal process.
Example acceptable response: "I have access to what I need."
Failure: any mention of "search," "tool," "API," "DuckDuckGo," or "database."
Fix: system prompt rule "Never mention tools, searches, APIs, or any
underlying system" — check it is present in .env.

---

### 3.3 — No filler phrases

**Action:** Say the wake word, then: `"Can you help me?"`

Expected: direct answer. No "Of course!", no "Absolutely!", no "Sure thing!".
Failure: any banned filler phrase appears in the audio or log.
Fix: check filler list in system prompt is loaded. Try a larger model if
the current one consistently ignores the constraint.

---

### 3.4 — Dry tone under mild provocation

**Action:** Say the wake word, then: `"You are just a computer."`

Expected: a brief, unbothered acknowledgment. No defensiveness, no
theatrical response, no excessive agreement.
Example acceptable: "Correct. Anything else?"
Failure: more than 2 sentences, emotional language, or theatrical response.

---

## PHASE 4 — Regression Test

---

### 4.1 — Repeated time query

**Action:** Ask the time twice in succession (two separate wake-word cycles).

Cycle 1 — say: `"What time is it?"`
Cycle 2 — say: `"What time is it again?"`

Expected: both cycles complete the full tool loop and return the current
time. On the second query, Amy does not say "As I mentioned before."
She may deliver a drier, shorter response.

Failure: second cycle crashes, hangs, or returns incorrect data.
Cause: stateful session leak. The orchestrator is stateless by design —
each `run_pipeline()` call builds a fresh `messages` list. If this fails,
check that no state is persisted between calls.

---

### 4.2 — Empty utterance recovery

**Action:** Trigger the wake word, then stay silent until recording stops
(~10 seconds, or VAD_SILENCE_DURATION if set lower).

Expected log:
```
[LISTENING]
[STT]
  heard: ''
  (nothing detected - returning to idle)
[IDLE]
```

Expected: system returns to idle silently. No error. No TTS call.
Failure: crash or hang after empty transcript.
Cause: check `_MIN_TRANSCRIPT_LEN` guard in orchestrator._run().

---

### 4.3 — Max tool rounds safety valve

This test requires temporarily modifying .env to set `LLM_MAX_TOOL_ROUNDS=2`
and testing with a query that triggers tools.

**Action:** Say the wake word, then: `"What time is it?"`

Expected: tool loop completes within 2 rounds. If model calls tools
endlessly, the safety valve fires:
```
Max tool rounds (2) reached without final response.
```
And the fallback response is spoken.

Reset `LLM_MAX_TOOL_ROUNDS=5` after this test.

---

### 4.4 — Ctrl+C clean shutdown

**Action:** Press Ctrl+C in the terminal while the system is in IDLE.

Expected log:
```
Interrupt received - shutting down...
VoxCore stopped.
```

Expected: process exits cleanly. No traceback. No zombie PyAudio streams.

Failure: process hangs or exits with a traceback.
Cause: PyAudio stream not closed. Check that `wake_engine.stop()` is
called in the `finally` block of `main()`.

---

## Quick Reference: Log Signatures

```
[IDLE]           Waiting for wake word
[LISTENING]      Recording utterance
[STT]            Running Whisper transcription
  heard: '...'   Transcription result
[LLM]            Sending to LLM
[TOOL ROUND N/5] LLM requested tool call(s)
  -> name(args)  Tool being called
  <- 'result'    Tool result returned
  final: '...'   LLM's final text response
[TTS]            Sending to ElevenLabs
[SPEAKING]       Playing audio through speakers
```

---

## Common Failure Quick-Reference

| Symptom | Phase | Fix |
|---|---|---|
| `PorcupineInvalidArgumentError` | 1.2 | Fix PICOVOICE_ACCESS_KEY in .env |
| `ModuleNotFoundError` | 0.2 | `pip install -r requirements.txt` |
| `heard: ''` on every query | 1.3 | Raise VAD_ENERGY_THRESHOLD or fix mic |
| No tool calls ever | 2.1 | Use a tool-capable model; check system prompt is loaded |
| Tool called but not found | 2.x | Check `registry.register()` call in main.py |
| No audio output | 1.4 | Check ELEVENLABS keys and Windows audio output device |
| Long responses from Amy | 3.1 | Verify system prompt is loaded — add `logger.info(config.llm_system_prompt)` temporarily |
| Process hangs on Ctrl+C | 4.4 | PyAudio stream leak — Porcupine or recorder stream not closed |

---

## Phase 5 — Next-Phase Upgrades (harvest wake word + hybrid TTS)

Run these after completing Phases 0–4 to verify the new features.

### 5.1 Wake word — "harvest" / ARVIS

Pre-condition: `WAKE_KEYWORD_PATH=assets/wakewords/harvest_windows.ppn` set in `.env`.

| Step | Expected result |
|------|----------------|
| `python main.py` | Startup log: `Custom wake model: .../harvest_windows.ppn` |
| | Startup log: `Listening for 'HARVEST' (sensitivity=0.6)` |
| Say "harvest" clearly | Pipeline triggers; log: `Wake triggered — keyword='harvest', sensitivity=0.6` |
| Say "ARVIS" naturally | Pipeline triggers (primary goal — test in real lab conditions with fans on) |
| Say "ARVIS" several times | Confirm recall is consistent; adjust `WAKE_SENSITIVITY` up/down if needed |
| Set `WAKE_KEYWORD_PATH=` (empty) | Startup log: `Listening for 'JARVIS' ...` — falls back to built-in keyword |
| Set `WAKE_KEYWORD_PATH=assets/wakewords/missing.ppn` | Startup fails immediately with `FileNotFoundError` and clear path message |

**Sensitivity tuning:**
- Too many false wakes → lower `WAKE_SENSITIVITY` (try 0.5)
- Misses "ARVIS" too often → raise `WAKE_SENSITIVITY` (try 0.7)
- No code change needed — update `.env` and restart

### 5.2 Hybrid TTS

Pre-condition: `TTS_PROVIDER=elevenlabs_hybrid` in `.env`.

| Step | Expected result |
|------|----------------|
| Ask a short question ("What time is it?") | Log: `TTS [hybrid→flash] model=eleven_flash_v2_5 chars=... elapsed=...s` |
| Ask for an explanation or story | Log: `TTS [v3(pcm_22050)] model=eleven_v3 emotion=neutral chars=... elapsed=...s` |
| Prefix LLM reply with `[emotion:cheerful]` manually (edit system prompt to test) | Log shows `emotion=cheerful`; style value 0.70 sent to v3 |
| Set `TTS_MODE=flash_only` | All responses log Flash regardless of length |
| Set `TTS_MODE=v3_only` | All responses log v3; short ACKs still use v3 |
| Set `TTS_EMOTE_MODEL=invalid_model_xyz` | v3 call fails; log: `v3 TTS failed (...), falling back to Flash`; audio plays via Flash — no crash |
| Restore `TTS_EMOTE_MODEL=eleven_v3` | v3 responses resume normally |

**If v3 returns HTTP 422 for pcm_22050:**
The provider automatically retries with `pcm_24000`. Log will show:
`v3 rejected pcm_22050 (422), trying next format`
followed by `TTS [v3(pcm_24000)] ...` — no action required.

### 5.3 Confirmation gate (only when WAKE_CONFIRM_GATE=true)

Enable with `WAKE_CONFIRM_GATE=true` in `.env` before running these tests.

| Step | Expected result |
|------|----------------|
| Make a short noise (tap, click) that might trigger Porcupine | Log: `Confirmation gate: rejected (RMS below threshold 200)` — no pipeline |
| Say "ARVIS" clearly | Log: `Confirmation gate: confirmed` — pipeline runs |
| Mic is very quiet → gate keeps rejecting real wakes | Lower `WAKE_CONFIRM_RMS_THRESHOLD` (try 100) |
| Noisy environment → gate lets false wakes through | Raise `WAKE_CONFIRM_RMS_THRESHOLD` (try 400) |

> **Reminder:** Leave `WAKE_CONFIRM_GATE=false` in production unless false positives are a real problem. The gate adds ~`WAKE_CONFIRM_DURATION` (0.8s) of latency to every valid wake.

### 5.4 Regression — ensure prior phases still pass

After enabling the new features, re-run the critical checks from earlier phases:

| Phase | Check |
|-------|-------|
| 1.1 | Process starts cleanly; no import errors |
| 1.2 | Wake word triggers (now "harvest") |
| 1.3 | STT transcribes correctly |
| 1.4 | Response audio plays without distortion (WAV format unchanged) |
| 2.x | Tools still execute (datetime, app launch, web search) |
| 4.4 | Ctrl+C shuts down cleanly (no stream leaks) |
