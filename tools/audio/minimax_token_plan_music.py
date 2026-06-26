"""MiniMax Token Plan music generation via mmx CLI."""

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


class MiniMaxTokenPlanMusic(BaseTool):
    name = "minimax_token_plan_music"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "music_generation"
    provider = PROVIDER
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.ASYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["cmd:npx"]
    install_instructions = INSTALL_INSTRUCTIONS
    agent_skills = [*AGENT_SKILLS, "music"]
    fallback_tools = ["music_gen", "suno_music"]

    capabilities = [
        "generate_background_music",
        "generate_song",
        "generate_instrumental",
    ]
    supports = {
        "instrumental": True,
        "vocals": True,
        "custom_lyrics": True,
        "style_control": True,
        "token_plan": True,
    }
    best_for = [
        "MiniMax Token Plan background music under monthly quota",
        "instrumental beds with genre/mood/tempo controls",
        "vocal songs with structured lyrics tags",
    ]
    not_good_for = [
        "sub-10-second stingers",
        "pay-as-you-go per-call billing",
        "offline generation",
    ]

    input_schema = {
        "type": "object",
        "required": ["prompt", "duration_seconds"],
        "properties": {
            "prompt": {"type": "string"},
            "duration_seconds": {
                "type": "number",
                "minimum": 3,
                "maximum": 600,
                "description": "Target duration — woven into the music prompt for planning.",
            },
            "lyrics": {"type": "string"},
            "lyrics_file": {"type": "string"},
            "lyrics_optimizer": {"type": "boolean", "default": False},
            "instrumental": {"type": "boolean", "default": True},
            "vocals": {"type": "string"},
            "genre": {"type": "string"},
            "mood": {"type": "string"},
            "instruments": {"type": "string"},
            "tempo": {"type": "string"},
            "bpm": {"type": "number"},
            "key": {"type": "string"},
            "structure": {"type": "string"},
            "model": {"type": "string", "default": "music-2.6"},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=100, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout"])
    idempotency_key_fields = ["prompt", "duration_seconds", "instrumental", "model"]
    side_effects = ["writes audio file", "calls MiniMax Token Plan via mmx CLI"]
    user_visible_verification = ["Listen for mood match, loopability, and level balance"]

    def get_status(self) -> ToolStatus:
        if mmx_is_available():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 90.0

    def _build_prompt(self, inputs: dict[str, Any]) -> str:
        base = inputs["prompt"].strip()
        duration = inputs["duration_seconds"]
        suffix = f" Target duration approximately {duration} seconds."
        return base + suffix if suffix.strip() not in base else base

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if inputs.get("duration_seconds") is None:
            return failure_result(
                "minimax_token_plan_music: duration_seconds is required "
                "(derive from approved script runtime)."
            )
        if not mmx_is_available():
            return failure_result("mmx CLI not available. " + self.install_instructions)

        start = time.time()
        output_path = prepare_output_path(inputs, "minimax_token_plan_music.mp3")
        prompt = self._build_prompt(inputs)

        args = [
            "music",
            "generate",
            "--prompt",
            prompt,
            "--model",
            inputs.get("model", "music-2.6"),
            "--out",
            str(output_path),
        ]

        if inputs.get("instrumental"):
            args.append("--instrumental")
        elif inputs.get("lyrics_optimizer"):
            args.append("--lyrics-optimizer")
        elif inputs.get("lyrics_file"):
            args.extend(["--lyrics-file", inputs["lyrics_file"]])
        elif inputs.get("lyrics"):
            args.extend(["--lyrics", inputs["lyrics"]])
        else:
            args.append("--instrumental")

        for flag, key in [
            ("--vocals", "vocals"),
            ("--genre", "genre"),
            ("--mood", "mood"),
            ("--instruments", "instruments"),
            ("--tempo", "tempo"),
            ("--key", "key"),
            ("--structure", "structure"),
        ]:
            if inputs.get(key):
                args.extend([flag, inputs[key]])
        if inputs.get("bpm") is not None:
            args.extend(["--bpm", str(inputs["bpm"])])

        try:
            run_mmx(self, args, timeout=300)
        except Exception as exc:
            return failure_result(f"MiniMax Token Plan music generation failed: {exc}")

        if not output_path.is_file():
            return failure_result(f"mmx did not write music to {output_path}")

        return success_result(
            tool_name=self.name,
            model=inputs.get("model", "music-2.6"),
            start=start,
            data={
                "prompt": inputs["prompt"],
                "duration_seconds": inputs["duration_seconds"],
                "instrumental": bool(inputs.get("instrumental", True)),
                "output": str(output_path),
            },
            artifacts=[str(output_path)],
        )
