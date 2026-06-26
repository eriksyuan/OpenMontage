"""MiniMax Token Plan text-to-speech via mmx CLI."""

from __future__ import annotations

import time
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)
from tools.minimax_token_plan_common import (
    AGENT_SKILLS,
    INSTALL_INSTRUCTIONS,
    PROVIDER,
    failure_result,
    mmx_is_available,
    prepare_output_path,
    run_mmx,
    success_result,
)


class MiniMaxTokenPlanTTS(BaseTool):
    name = "minimax_token_plan_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = PROVIDER
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["cmd:npx"]
    install_instructions = INSTALL_INSTRUCTIONS
    agent_skills = [*AGENT_SKILLS, "text-to-speech"]
    fallback_tools = ["elevenlabs_tts", "openai_tts", "google_tts", "piper_tts"]

    capabilities = ["text_to_speech", "voice_selection", "multilingual", "subtitles"]
    supports = {
        "multilingual": True,
        "offline": False,
        "native_audio": True,
        "subtitles": True,
        "token_plan": True,
    }
    best_for = [
        "MiniMax Token Plan narration with 30+ voices",
        "Mandarin and multilingual voiceovers under monthly quota",
        "subtitle timing export via --subtitles",
    ]
    not_good_for = [
        "pay-as-you-go per-character billing",
        "fully offline production",
        "voice clone matching",
    ]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string", "maxLength": 10000},
            "voice": {"type": "string", "default": "English_expressive_narrator"},
            "model": {"type": "string", "default": "speech-2.8-hd"},
            "speed": {"type": "number"},
            "volume": {"type": "number"},
            "pitch": {"type": "number"},
            "format": {
                "type": "string",
                "enum": ["mp3", "pcm", "flac", "wav", "opus"],
                "default": "mp3",
            },
            "language": {"type": "string"},
            "subtitles": {"type": "boolean", "default": False},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=50, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["text", "voice", "model"]
    side_effects = ["writes audio file", "calls MiniMax Token Plan via mmx CLI"]
    user_visible_verification = ["Listen for clarity, pacing, and pronunciation"]

    def get_status(self) -> ToolStatus:
        if mmx_is_available():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 15.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if not mmx_is_available():
            return failure_result("mmx CLI not available. " + self.install_instructions)

        start = time.time()
        output_path = prepare_output_path(inputs, "minimax_token_plan_tts.mp3")
        args = [
            "speech",
            "synthesize",
            "--text",
            inputs["text"],
            "--model",
            inputs.get("model", "speech-2.8-hd"),
            "--voice",
            inputs.get("voice", "English_expressive_narrator"),
            "--format",
            inputs.get("format", "mp3"),
            "--out",
            str(output_path),
        ]
        if inputs.get("speed") is not None:
            args.extend(["--speed", str(inputs["speed"])])
        if inputs.get("volume") is not None:
            args.extend(["--volume", str(inputs["volume"])])
        if inputs.get("pitch") is not None:
            args.extend(["--pitch", str(inputs["pitch"])])
        if inputs.get("language"):
            args.extend(["--language", inputs["language"]])
        if inputs.get("subtitles"):
            args.append("--subtitles")

        try:
            run_mmx(self, args, timeout=180)
        except Exception as exc:
            return failure_result(f"MiniMax Token Plan TTS failed: {exc}")

        if not output_path.is_file():
            return failure_result(f"mmx did not write audio to {output_path}")

        return success_result(
            tool_name=self.name,
            model=inputs.get("model", "speech-2.8-hd"),
            start=start,
            data={
                "text": inputs["text"],
                "voice": inputs.get("voice", "English_expressive_narrator"),
                "output": str(output_path),
            },
            artifacts=[str(output_path)],
        )
