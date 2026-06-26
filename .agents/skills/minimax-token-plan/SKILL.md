---
name: minimax-token-plan
description: MiniMax Token Plan multimodal generation via mmx CLI — image, video, TTS, music, and text. Use provider=minimax_token_plan and MINIMAX_TOKEN_PLAN_KEY (Subscription Key). Distinct from pay-as-you-go provider=minimax API keys and fal.ai FAL_KEY routing.
metadata:
  author: OpenMontage
  version: "1.0.0"
  tags: minimax, token-plan, mmx-cli, image-generation, video-generation, tts, music, text-generation
---

# MiniMax Token Plan (mmx CLI)

## Provider distinction (critical)

MiniMax has **three separate integration paths** in OpenMontage. Do not mix keys or providers.

| Path | OpenMontage `provider` | Key / auth | Tools |
|------|------------------------|------------|-------|
| **Token Plan** (this skill) | `minimax_token_plan` | `MINIMAX_TOKEN_PLAN_KEY` (Subscription Key) + mmx CLI | `minimax_token_plan_*` |
| **Pay-as-you-go API** | `minimax` | `MINIMAX_API_KEY` (API Keys page) | Future direct HTTP tools |
| **fal.ai gateway** | `minimax` | `FAL_KEY` | `minimax_video` (Hailuo via fal.ai) |

**Subscription Key ≠ pay-as-you-go API Key.** They are issued from different console pages and are not interchangeable.

## Install and authenticate

```bash
npm install          # repo root — installs mmx-cli from package.json
npx mmx --version

# Subscription Key from: MiniMax console → Billing → Token Plan
export MINIMAX_TOKEN_PLAN_KEY=sk-xxxxx
mmx auth login --api-key "$MINIMAX_TOKEN_PLAN_KEY"

# Or rely on env var — OpenMontage tools pass --api-key automatically
mmx quota
```

**Region:** mmx auto-detects region from the key. If you get 401:

```bash
mmx config set --key region --value global   # overseas (platform.minimax.io)
mmx config set --key region --value cn       # mainland China (platform.minimaxi.com)
mmx auth status
```

## OpenMontage tools

| Tool | Capability | mmx command |
|------|------------|-------------|
| `minimax_token_plan_image` | `image_generation` | `mmx image generate` |
| `minimax_token_plan_video` | `video_generation` | `mmx video generate` |
| `minimax_token_plan_tts` | `tts` | `mmx speech synthesize` |
| `minimax_token_plan_music` | `music_generation` | `mmx music generate` |
| `minimax_token_plan_text` | `text_generation` | `mmx text chat` |

**Selector routing** (when user wants Token Plan explicitly):

```python
ImageSelector().execute({"preferred_provider": "minimax_token_plan", "prompt": "..."})
TTSSelector().execute({"preferred_provider": "minimax_token_plan", "text": "..."})
VideoSelector().execute({"preferred_provider": "minimax_token_plan", "prompt": "..."})
```

## Default models

| Modality | Default model | Notes |
|----------|---------------|-------|
| Image | `image-01` | aspect ratio, batch `--n`, subject reference |
| Video | `MiniMax-Hailuo-2.3` | Fast: `MiniMax-Hailuo-2.3-Fast` with `--first-frame` |
| Speech | `speech-2.8-hd` | 30+ voices, up to 10k chars |
| Music | `music-2.6` | instrumental or lyrics with structure tags |
| Text | `MiniMax-M2.7` | chat, system prompt, JSON output |

## Command reference

### Image

```bash
mmx image generate --prompt "Cyberpunk city at night, 16:9" --aspect-ratio 16:9 --out scene.png
mmx image generate --prompt "Same character in cafe" --subject-ref "type=character,image=ref.png" --out char.png
```

**Prompting:** Front-load subject and action. Specify lighting and composition. Use `--prompt-optimizer` for vague prompts.

### Video

```bash
# Sync (waits and downloads)
mmx video generate --prompt "Cat by window at sunset" --download clip.mp4

# Async (returns task id)
mmx video generate --prompt "Robot painting" --async --output json
mmx video task get --task-id <id> --output json
```

**I2V:** `--first-frame path-or-url`  
**SEF:** `--first-frame` + `--last-frame` (Hailuo-02)  
**Subject consistency:** `--subject-image` (S2V-01)

### Speech (TTS)

```bash
mmx speech synthesize --text "Welcome to our product." --voice English_expressive_narrator --out vo.mp3
mmx speech synthesize --text "中文旁白测试" --language zh --out zh.mp3
```

### Music

```bash
mmx music generate --prompt "Lo-fi study beat, soft piano" --instrumental --out bgm.mp3
mmx music generate --prompt "Upbeat pop" --lyrics "[Verse]\n..." --out song.mp3
```

Structured flags: `--genre`, `--mood`, `--instruments`, `--tempo`, `--bpm`, `--key`, `--structure`, `--vocals`.

### Text

```bash
mmx text chat --message "Write a 60s explainer hook about black holes"
mmx text chat --system "You are a scriptwriter." --message "..." --output json
```

## Billing and quota

- Token Plan tools use **monthly quota**, not per-call USD in OpenMontage (`estimate_cost` returns 0).
- Check remaining quota: `mmx quota`
- Quota resets monthly per plan tier.
- To switch to pay-as-you-go mid-session, replace Subscription Key with pay-as-you-go API Key per MiniMax docs (different provider in OpenMontage).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| 401 Unauthorized | Wrong key type or region — verify Subscription Key, run `mmx config set --key region` |
| `mmx: command not found` | Run `npm install` at repo root (installs `mmx-cli` locally) |
| Quota exhausted | `mmx quota` — wait for reset or upgrade plan |
| Video timeout | Use `async_mode: true` on `minimax_token_plan_video`, poll task separately |
| Wrong provider selected | Set `preferred_provider="minimax_token_plan"` (not `"minimax"`) |

## When NOT to use Token Plan tools

- User has only **FAL_KEY** and wants Hailuo via fal.ai → `minimax_video` (`provider=minimax`)
- User has **pay-as-you-go MINIMAX_API_KEY** only → future `provider=minimax` HTTP tools (not mmx CLI)
- Fully offline → `piper_tts`, local diffusion, etc.
