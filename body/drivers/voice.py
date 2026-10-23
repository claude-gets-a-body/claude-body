"""Voice: hearing and speaking.

    Voice         the interface
    ConsoleVoice  simulator: you type what the robot hears, it prints what it says
    LocalVoice    STUB for the robot: wake word + VAD on the Pi, speech-to-text
                  and text-to-speech on K8 over HTTP (shapes documented below)

Audio never leaves the house: the mic stream stays on the Pi until the wake word,
then one utterance goes to K8's whisper; replies come back from K8's Piper.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class Utterance:
    text: str
    # Who said it. Only ever set by an explicit `/as` in the simulator. On the
    # robot it stays None: there's no face recognition (honest eyes) and no
    # voice-ID yet (see LocalVoice.identify_speaker).
    speaker: str | None = None
    # Direction of arrival in degrees, + = left, RELATIVE TO THE HEAD (the mic
    # array is on the head). The agent adds the neck pan angle to turn it into a
    # bearing relative to the body before telling the mind.
    doa: float = 0.0
    conf: float = 1.0              # speech-to-text confidence 0..1


class Voice:
    async def next_utterance(self) -> Utterance:
        """Wait for the next thing someone says to the robot."""
        raise NotImplementedError

    async def speak(self, text: str, style: str = "normal") -> bool:
        """Say it. Returns False if interrupted (someone said the wake word)."""
        raise NotImplementedError

    def open_followup(self, seconds: float) -> None:
        """Listen without the wake word for a few seconds (after asking a question)."""


class ConsoleVoice(Voice):
    def __init__(self, seconds_per_word: float = 0.0, out=print):
        self.queue: asyncio.Queue[Utterance] = asyncio.Queue()
        self.seconds_per_word = seconds_per_word
        self.out = out
        self.spoken: list[str] = []
        self.followup_s = 0.0

    def hear(self, utterance: Utterance) -> None:
        self.queue.put_nowait(utterance)

    async def next_utterance(self) -> Utterance:
        return await self.queue.get()

    async def speak(self, text: str, style: str = "normal") -> bool:
        self.spoken.append(text)
        prefix = "ROBOT SAYS (quietly)" if style == "quiet" else "ROBOT SAYS"
        self.out(f"\n{prefix}: {text}\n")
        if self.seconds_per_word:
            await asyncio.sleep(self.seconds_per_word * len(text.split()))
        return self.queue.empty()   # someone spoke over it -> interrupted

    def open_followup(self, seconds: float) -> None:
        self.followup_s = seconds
        self.out(f"  [ears up: listening for {seconds:g} s without the wake word]")


class LocalVoice(Voice):
    """STUB — the robot's real voice pipeline (phase 1).

    On the Pi:
      - reSpeaker XVF3800 (USB): 16 kHz mono capture, echo-cancelled.
      - Direction of arrival: read over USB with Seeed's `xvf_host` tool or their
        Python control library (parameters DOA_VALUE / AEC_AZIMUTH_VALUES).
        The angle is relative to the HEAD; return it as Utterance.doa and let
        the agent add the neck pan.
      - Wake word: openWakeWord with a custom "Hey Claude" model (DESIGN.md §8).
      - Voice activity detection (e.g. webrtcvad or Silero) to cut one utterance.
      - ALL audio playback goes out through the XVF3800's own USB audio output
        (its on-board amp drives the speaker). That is how its echo canceller
        gets the reference signal. Never play sound through any other device
        (not the Pi's HDMI audio, not a Bluetooth speaker), or the robot will
        hear itself and the wake word will false-trigger.

    Speech-to-text on K8 — the robot's OWN whisper instance, not the house
    assistant's (its prompt is tuned for house devices). Expected shape, if it
    is a whisper.cpp server:
        POST http://k8:8913/inference
             multipart/form-data: file=<utterance.wav>, response_format=json, language=en
        ->   200 {"text": "what's this bug?"}
    (faster-whisper servers usually offer the OpenAI-style
     POST /v1/audio/transcriptions with the same multipart file field.)

    Text-to-speech on K8 — Piper's HTTP server (python -m piper.http_server):
        POST http://k8:5000/   body: {"text": "Hello!", "voice": "en_GB-..."}  (JSON)
        ->   200 audio/wav
    Play the WAV out through the XVF3800's USB audio device only (select it by
    its ALSA/PipeWire name, never the system default). Return False from
    speak() if the wake word fires during playback.

    Confirm both URLs and ports when the services are set up on K8.
    """

    async def next_utterance(self) -> Utterance:
        raise NotImplementedError("openWakeWord + VAD + whisper client not written yet (phase 1)")

    async def speak(self, text: str, style: str = "normal") -> bool:
        raise NotImplementedError("Piper TTS client not written yet (phase 1)")

    def identify_speaker(self, audio: bytes) -> str | None:
        """STUB for a possible future voice-ID (speaker embedding compared with
        enrolled family voices, enrolment only when a parent says so). Until then
        the robot doesn't know who is talking, and returns None."""
        return None
