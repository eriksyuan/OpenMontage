# OpenMontage

**MANDATORY: Read `AGENT_GUIDE.md` before responding to ANY user message.**

Do not act on the user's request until you have read AGENT_GUIDE.md.
It contains routing rules that determine your first action based on what the user asked.
Skipping it WILL cause you to take the wrong action.

There are no instructions in this file. All instructions are in AGENT_GUIDE.md.

## Cursor Cloud specific instructions

Environment is Python 3.12 + Node 22 + FFmpeg 6.1, all preinstalled. The startup update script runs `pip install -r requirements-dev.txt` and `npm install --prefix remotion-composer`, so Python deps and the Remotion composer's `node_modules` are already present on session start. No API keys are required for core development or testing.

Non-obvious notes:

- **Lint / test / run commands live in the `Makefile`** — use `make lint`, `make test`, `make preflight`, `make demo`. CI (`.github/workflows/ci.yml`) only runs `make install-dev`, `make lint`, `make test`. `make lint` is a `py_compile` smoke check, not a full linter.
- **`.env` is optional.** `make setup` copies `.env.example` to `.env`; an empty `.env` is fine for the zero-key paths. Adding keys unlocks cloud providers (see `.env.example`).
- **Zero-key end-to-end demo:** `python3 render_demo.py [world-in-numbers|code-to-screen|focusflow-pitch]` renders a real MP4 via Remotion into `projects/demos/renders/` (no keys needed). `python3 render_demo.py --list` lists them. This is the fastest proof the full render pipeline works.
- **Three composition runtimes are available** (verify with `make preflight` → `composition_runtimes`): FFmpeg, Remotion (`remotion-composer/`, needs `node_modules`), and HyperFrames (`npx hyperframes`, fetched/cached on first use — run `make hyperframes-warm` to refresh, `make hyperframes-doctor` to validate).
- **HyperFrames Chrome caveat in this container:** `/dev/shm` is only 64 MB (Chrome wants ≥256 MB) and there is no `chrome-headless-shell`, so HyperFrames renders fall back to system-Chrome screenshot capture mode. It still works for validation/small renders but is slower; this is expected, not a misconfiguration.
- `piper-tts` (offline TTS) and GPU deps (`requirements-gpu.txt`) are intentionally NOT installed by the update script — they are optional and only needed for those specific provider paths.
