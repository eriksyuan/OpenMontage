"""MiniMax Token Plan text generation via mmx CLI."""

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
    parse_json_stdout,
    run_mmx,
    success_result,
)


class MiniMaxTokenPlanText(BaseTool):
    name = "minimax_token_plan_text"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "text_generation"
    provider = PROVIDER
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["cmd:npx"]
    install_instructions = INSTALL_INSTRUCTIONS
    agent_skills = AGENT_SKILLS

    capabilities = ["chat_completion", "script_drafting", "json_output"]
    supports = {
        "system_prompt": True,
        "multi_turn": True,
        "json_output": True,
        "token_plan": True,
    }
    best_for = [
        "MiniMax Token Plan language model calls (M2.7)",
        "script outlines and copy under monthly quota",
        "structured JSON responses for pipeline artifacts",
    ]
    not_good_for = [
        "pay-as-you-go OpenAI-compatible API billing",
        "offline generation",
    ]

    input_schema = {
        "type": "object",
        "required": ["message"],
        "properties": {
            "message": {"type": "string", "description": "User message text"},
            "messages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Additional messages (prefix role: to set role)",
            },
            "messages_file": {"type": "string"},
            "system": {"type": "string"},
            "model": {"type": "string", "default": "MiniMax-M2.7"},
            "max_tokens": {"type": "integer", "default": 4096},
            "temperature": {"type": "number"},
            "top_p": {"type": "number"},
            "json_output": {"type": "boolean", "default": False},
            "output_path": {
                "type": "string",
                "description": "Optional path to save the response text",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=10, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["message", "system", "model"]
    side_effects = ["calls MiniMax Token Plan via mmx CLI"]
    user_visible_verification = ["Review response for accuracy and tone"]

    def get_status(self) -> ToolStatus:
        if mmx_is_available():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 10.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if not mmx_is_available():
            return failure_result("mmx CLI not available. " + self.install_instructions)

        start = time.time()
        args = [
            "text",
            "chat",
            "--model",
            inputs.get("model", "MiniMax-M2.7"),
            "--message",
            inputs["message"],
            "--max-tokens",
            str(inputs.get("max_tokens", 4096)),
            "--output",
            "json" if inputs.get("json_output") else "text",
        ]
        if inputs.get("system"):
            args.extend(["--system", inputs["system"]])
        if inputs.get("temperature") is not None:
            args.extend(["--temperature", str(inputs["temperature"])])
        if inputs.get("top_p") is not None:
            args.extend(["--top-p", str(inputs["top_p"])])
        if inputs.get("messages_file"):
            args.extend(["--messages-file", inputs["messages_file"]])
        for extra_message in inputs.get("messages") or []:
            args.extend(["--message", extra_message])

        try:
            proc = run_mmx(self, args, timeout=120)
        except Exception as exc:
            return failure_result(f"MiniMax Token Plan text generation failed: {exc}")

        stdout = proc.stdout.strip()
        parsed = parse_json_stdout(stdout) if inputs.get("json_output") else None
        text = stdout
        if parsed:
            choices = parsed.get("choices") or []
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message") or {}
                text = message.get("content") or stdout
            elif parsed.get("content"):
                text = str(parsed["content"])

        artifacts: list[str] = []
        output_path = inputs.get("output_path")
        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            artifacts.append(str(path))

        return success_result(
            tool_name=self.name,
            model=inputs.get("model", "MiniMax-M2.7"),
            start=start,
            data={
                "message": inputs["message"],
                "text": text,
                "raw": parsed or stdout,
            },
            artifacts=artifacts,
        )
