"""MiniMax Token Plan video generation via mmx CLI."""

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
    extract_task_id,
    failure_result,
    mmx_is_available,
    parse_json_stdout,
    prepare_output_path,
    redact_secrets,
    run_mmx,
    success_result,
)


class MiniMaxTokenPlanVideo(BaseTool):
    name = "minimax_token_plan_video"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = PROVIDER
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.ASYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["cmd:npx"]
    install_instructions = INSTALL_INSTRUCTIONS
    agent_skills = [*AGENT_SKILLS, "ai-video-gen"]

    capabilities = ["text_to_video", "image_to_video", "subject_reference_video"]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "first_frame": True,
        "last_frame": True,
        "subject_image": True,
        "token_plan": True,
    }
    best_for = [
        "MiniMax Token Plan quota-based video (Hailuo 2.3)",
        "first-frame or subject-reference conditioned clips",
        "one Subscription Key across all MiniMax modalities",
    ]
    not_good_for = [
        "fal.ai gateway billing (use minimax_video with FAL_KEY instead)",
        "very long clips",
        "offline generation",
    ]
    fallback_tools = ["minimax_video", "kling_video", "veo_video", "wan_video"]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "model": {
                "type": "string",
                "default": "MiniMax-Hailuo-2.3",
            },
            "first_frame": {"type": "string", "description": "Local path or URL"},
            "last_frame": {"type": "string", "description": "Local path or URL (SEF mode)"},
            "subject_image": {"type": "string", "description": "Subject reference image (S2V mode)"},
            "async_mode": {
                "type": "boolean",
                "default": False,
                "description": "Return task_id immediately without waiting for completion",
            },
            "poll_interval_seconds": {"type": "number", "default": 5.0},
            "timeout_seconds": {"type": "integer", "default": 600},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=500, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout"])
    idempotency_key_fields = ["prompt", "model", "first_frame", "subject_image"]
    side_effects = ["writes video file", "calls MiniMax Token Plan via mmx CLI"]
    user_visible_verification = ["Watch clip for motion coherence and prompt adherence"]

    def get_status(self) -> ToolStatus:
        if mmx_is_available():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 120.0

    def _build_generate_args(self, inputs: dict[str, Any], output_path: Path) -> list[str]:
        args = [
            "video",
            "generate",
            "--prompt",
            inputs["prompt"],
            "--model",
            inputs.get("model", "MiniMax-Hailuo-2.3"),
        ]
        if inputs.get("first_frame"):
            args.extend(["--first-frame", inputs["first_frame"]])
        if inputs.get("last_frame"):
            args.extend(["--last-frame", inputs["last_frame"]])
        if inputs.get("subject_image"):
            args.extend(["--subject-image", inputs["subject_image"]])
        if inputs.get("async_mode"):
            args.append("--async")
        else:
            args.extend(["--download", str(output_path)])
            args.extend(["--poll-interval", str(inputs.get("poll_interval_seconds", 5))])
        return args

    def _poll_task(self, task_id: str, timeout_seconds: int, poll_interval: float) -> dict[str, Any]:
        deadline = time.time() + timeout_seconds
        last_status = "unknown"
        while time.time() < deadline:
            proc = run_mmx(
                self,
                ["video", "task", "get", "--task-id", task_id, "--output", "json"],
                timeout=30,
            )
            data = parse_json_stdout(proc.stdout) or {}
            status = str(data.get("status", data.get("task_status", "unknown"))).lower()
            last_status = status
            if status in {"success", "succeeded", "completed", "done"}:
                return data
            if status in {"failed", "error", "cancelled", "canceled"}:
                raise RuntimeError(f"Video task {task_id} failed with status={status}")
            time.sleep(poll_interval)
        raise TimeoutError(f"Video task {task_id} timed out (last status={last_status})")

    def _download_from_task(self, task_data: dict[str, Any], output_path: Path) -> None:
        file_id = task_data.get("file_id") or task_data.get("fileId")
        download_url = None
        file_info = task_data.get("file") or task_data.get("video") or {}
        if isinstance(file_info, dict):
            download_url = file_info.get("download_url") or file_info.get("url")
        if file_id:
            run_mmx(
                self,
                ["video", "download", "--file-id", str(file_id), "--out", str(output_path)],
                timeout=300,
            )
            return
        if download_url:
            import requests

            response = requests.get(download_url, timeout=300)
            response.raise_for_status()
            output_path.write_bytes(response.content)
            return
        raise RuntimeError("Task completed but no file_id or download URL found in task response")

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if not mmx_is_available():
            return failure_result("mmx CLI not available. " + self.install_instructions)

        start = time.time()
        output_path = prepare_output_path(inputs, "minimax_token_plan_video.mp4")
        args = self._build_generate_args(inputs, output_path)

        try:
            if inputs.get("async_mode"):
                proc = run_mmx(self, args, timeout=60)
                task_id = extract_task_id(proc.stdout)
                if not task_id:
                    return failure_result(
                        "MiniMax Token Plan video submitted but no task_id returned: "
                        + redact_secrets(proc.stdout.strip())
                    )
                return success_result(
                    tool_name=self.name,
                    model=inputs.get("model", "MiniMax-Hailuo-2.3"),
                    start=start,
                    data={
                        "prompt": inputs["prompt"],
                        "task_id": task_id,
                        "status": "submitted",
                    },
                )

            run_mmx(self, args, timeout=int(inputs.get("timeout_seconds", 600)))
            if not output_path.is_file():
                return failure_result(f"mmx did not write video to {output_path}")

            return success_result(
                tool_name=self.name,
                model=inputs.get("model", "MiniMax-Hailuo-2.3"),
                start=start,
                data={"prompt": inputs["prompt"], "output": str(output_path)},
                artifacts=[str(output_path)],
            )
        except Exception as exc:
            return failure_result(f"MiniMax Token Plan video generation failed: {exc}")
