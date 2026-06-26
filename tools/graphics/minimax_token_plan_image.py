"""MiniMax Token Plan image generation via mmx CLI."""

from __future__ import annotations

import time
from pathlib import Path
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


class MiniMaxTokenPlanImage(BaseTool):
    name = "minimax_token_plan_image"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "image_generation"
    provider = PROVIDER
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.API

    dependencies = ["cmd:npx"]
    install_instructions = INSTALL_INSTRUCTIONS
    agent_skills = AGENT_SKILLS

    capabilities = ["generate_image", "text_to_image"]
    supports = {
        "custom_size": True,
        "aspect_ratio": True,
        "batch_generation": True,
        "subject_reference": True,
        "token_plan": True,
    }
    best_for = [
        "MiniMax Token Plan quota-based image generation",
        "character consistency via subject reference",
        "one Subscription Key for image + video + TTS + music",
    ]
    not_good_for = [
        "pay-as-you-go API billing (use provider=minimax HTTP tools instead)",
        "offline generation",
    ]
    fallback_tools = ["flux_image", "openai_image", "grok_image"]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "aspect_ratio": {"type": "string", "default": "16:9"},
            "n": {"type": "integer", "default": 1, "minimum": 1},
            "width": {"type": "integer", "minimum": 512, "maximum": 2048},
            "height": {"type": "integer", "minimum": 512, "maximum": 2048},
            "seed": {"type": "integer"},
            "subject_ref": {
                "type": "string",
                "description": "Subject reference, e.g. type=character,image=/path/or/url",
            },
            "prompt_optimizer": {"type": "boolean", "default": False},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=200, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "aspect_ratio", "width", "height", "seed"]
    side_effects = ["writes image file", "calls MiniMax Token Plan via mmx CLI"]
    user_visible_verification = ["Inspect generated image for prompt relevance and quality"]

    def get_status(self) -> ToolStatus:
        if mmx_is_available():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 20.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if not mmx_is_available():
            return failure_result("mmx CLI not available. " + self.install_instructions)

        start = time.time()
        output_path = prepare_output_path(inputs, "minimax_token_plan_image.png")
        args = [
            "image",
            "generate",
            "--prompt",
            inputs["prompt"],
            "--aspect-ratio",
            inputs.get("aspect_ratio", "16:9"),
            "--n",
            str(inputs.get("n", 1)),
            "--out",
            str(output_path),
        ]
        if inputs.get("width"):
            args.extend(["--width", str(inputs["width"])])
        if inputs.get("height"):
            args.extend(["--height", str(inputs["height"])])
        if inputs.get("seed") is not None:
            args.extend(["--seed", str(inputs["seed"])])
        if inputs.get("subject_ref"):
            args.extend(["--subject-ref", inputs["subject_ref"]])
        if inputs.get("prompt_optimizer"):
            args.append("--prompt-optimizer")

        try:
            run_mmx(self, args, timeout=180)
        except Exception as exc:
            return failure_result(f"MiniMax Token Plan image generation failed: {exc}")

        if not output_path.is_file():
            return failure_result(f"mmx did not write image to {output_path}")

        return success_result(
            tool_name=self.name,
            model="image-01",
            start=start,
            data={"prompt": inputs["prompt"], "output": str(output_path)},
            artifacts=[str(output_path)],
        )
