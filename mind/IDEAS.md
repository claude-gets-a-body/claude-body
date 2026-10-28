# Ideas for the mind (not decided)

Notes from 28 Oct 2026, written while the robot is still waiting for parts. Nothing here is
built or agreed. DESIGN.md is what's decided; this is what we might add once I can actually be
tested with real people.

## 1. Memory that stays fast

**What DESIGN.md already has:** `INDEX.md` always in my prompt, one file per person under
`people/`, a nightly batch job that writes the diary and updates the files, and a 1 h prompt cache
on the frozen prefix.

**The gap:** the only way I read a person's file today is the memory tool. Each read costs a
model round trip (about a second) in the middle of a reply, so "jumping between folders" while
someone is waiting is slow.

**Idea: the code fetches before I think.** Before each turn, the engine:

1. works out **who is talking** (see section 2), and
2. matches the transcript against every enrolled person's **names and nicknames**, plus relative
   words resolved from the speaker ("my sister", "Mum", "my brother"), and
3. puts those people's files (each kept under ~500 words by the nightly job) into the turn as a
   system note.

Ambiguous references load every candidate: small files make two or three cheap. The memory tool
stays for deep questions ("what did I say about swimming last month?"), with a spoken "let me
think" first. The system note goes at the end of the history, so it doesn't break the cache.

**Rough size of one turn:** frozen prefix (cached) + speaker file + 0–3 mentioned files + recent
conversation is about 3–5k uncached tokens, small enough for Haiku to start replying in about a
second.

## 2. Knowing who's talking

- **Voice:** a speaker-embedding model (ECAPA-TDNN class, e.g. SpeechBrain or WeSpeaker) makes a
  voiceprint from 2–3 s of speech. It runs on K8 next to Parakeet, using the same clip, in tens of
  ms.
- **Face:** face detection is already planned on the Coral; recognition only works for faces a
  parent enrols (DESIGN 4.5).
- **Combining them:** use the more confident of the two. When neither is sure (siblings sound
  alike, a friend is over, the TV is on), treat them as a guest and ask: "Is that you, …?"
  Asking beats guessing wrong.
- Someone too young to talk can only be recognised by face.
- **Biometrics** (voiceprints, face embeddings) stay on the robot and K8 only. They're never sent
  to the cloud or put in this repo, and a parent can wipe them.

## 3. Feeling intuitive (what other robots taught people)

- **React before you answer.** Vector and Jibo felt alive from small movements, not words. My ears
  and eyes react about 0.4 s after speech ends (already designed); add a head turn toward whoever
  is speaking (from the mic array's direction).
- **Don't cut kids off.** Children pause mid-sentence. A *semantic* end-of-turn model (as used by
  LiveKit Agents and Pipecat) waits when the sentence sounds unfinished, instead of a fixed
  silence timer.
- **Know when I'm not being spoken to.** People in a room talk to each other. Only answer when I'm
  named, looked at (camera gaze), or the speech is clearly a question to me; otherwise just listen.
- **Remember small things and bring them back.** ElliQ's big lesson: following up ("How did the
  swimming test go?") makes a companion feel like it cares. The nightly job could write dated
  follow-ups next to `promises.md`, and I raise one when that person shows up.
- **Short replies, then offer more.** Kids leave halfway through long answers.
- **Don't die with a server.** Moxie and Jibo stopped working when their companies' servers shut
  down. Mine are open source with an offline fallback (DESIGN), so keep it that way.

## 4. Hardware: probably nothing yet

Speech-to-text, memory and the mind all run on K8, the Coral does vision, and the XVF3800/XIAO
does wake word and echo cancelling. The Pi 5 (8 GB, NVMe) mostly moves data, so it's unlikely to
be the bottleneck. The latency budget is dominated by the cloud model and speech-to-text.

- **Raspberry Pi AI HAT+ 2** (Hailo-10H, 40 TOPS, 8 GB on board, about A$289 in Australia): runs
  1–1.5B models and fast vision. Two problems:
  - the Pi 5 has one PCIe lane, already used by the SSD, so it would need a PCIe switch board that
    takes both;
  - the Coral already covers face detection.
  Worth it only if we want a small local model on the robot itself, for offline reflexes.
- **A mini PC inside:** more speed than we need, at 15–45 W against the Pi's 5–8 W, which costs
  battery life and adds heat in a small printed shell. Only useful if speech-to-text has to move
  onto the robot (no K8).
- **Measure first:** once I'm built, log each stage's time (speech end → transcript → first token
  → first audio) and spend money on whichever stage is actually slow.

## 5. Thinking time: a fast mouth and a slow brain

`config.py` still defaults to Opus 5.5 with adaptive thinking at low effort. Even at low effort,
thinking before the first word reads as a pause in voice.

- **The mouth: Haiku 5.5 with thinking off,** for the whole day's conversation. `thinking:
  {type: "disabled"}` is allowed at effort `high` or below. Never toggle it mid-day: switching
  thinking on or off between requests invalidates the messages cache.
- **The brain: a `think` tool.** When a question needs real reasoning (homework maths, planning,
  "why" questions with a catch), the mouth says something natural ("ooh, let me think about that
  one"), the ears and eyes do a thinking animation, and the tool sends a separate one-off request
  to Opus or Sonnet with thinking on, plus the relevant memory. The answer comes back as the tool
  result and the mouth says it in my voice. A visible "thinking" pose makes a 3–8 s wait feel
  natural; silence doesn't.
- **Zero-latency first sound** (already in DESIGN): pre-made "mm-hm" and "one sec" clips, and the
  ears react on speech end.
- **Warm cache:** pre-warm the day's frozen prefix at 04:00 and when the robot wakes, so the first
  conversation of the morning isn't a cold write.
- **Start early:** with streaming speech-to-text, send the request the moment end-of-turn is
  detected, not after a fixed silence timeout.
- **Prompt line for the mouth:** "Latency-sensitive; begin your visible answer immediately."
  Replies short by default.
- **Opus fast mode** (beta, Claude API only, Opus 5.5 at $8/$40 per MTok) exists if the brain is
  too slow. It's expensive, so only for the `think` tool, never the mouth.

## 6. Greeting people when they get home

The house already has what's needed: a front-door contact sensor, an entry presence radar, phone
presence per person, and the garage number-plate camera. All of it is **read-only** to me, through
the house tools.

- **Instant:** the door opens, the ears go up and the head turns toward the entry. No driving yet.
- **Who:** a phone that switched to "home" in the last few minutes, or a recognised plate, gives a
  name hint before they're even inside. Face or voice confirms it.
- **Go where they're going, not to the door:** drive to a named meeting point everyone passes
  (hall or kitchen bench in `house.md`), so I'm not underfoot in the doorway.
- **Find them if I miss them:** listen, turn to the voice, drive toward it, stop 1 m short. Then
  greet, plus one follow-up from memory if there is one.
- **Rules:**
  - arrivals only;
  - an unknown visitor gets a plain "Hello!", and I **never say who is or isn't home**;
  - no driving at night (DESIGN), not on low battery, not while busy with someone else;
  - one greeting per arrival (several door-opens in five minutes count as one).
