"""Shared helpers for MiniMax Token Plan tools (mmx CLI)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from tools.base_tool import BaseTool, DependencyError, ToolResult

PROVIDER = "minimax_token_plan"
BILLING = "token_plan"

INSTALL_INSTRUCTIONS = (
    "MiniMax Token Plan uses the mmx CLI with a Subscription Key (not pay-as-you-go API Keys).\n"
    "  1. npm install   (installs mmx-cli from repo package.json)\n"
    "  2. Get your Subscription Key from MiniMax console: Billing > Token Plan\n"
    "  3. mmx auth login --api-key sk-xxx\n"
    "     Or set MINIMAX_TOKEN_PLAN_KEY in .env (tools pass --api-key automatically)\n"
    "  4. If API calls return 401: mmx config set --key region --value global|cn\n"
    "  5. Check quota: mmx quota"
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _local_mmx_binary() -> Path | None:
    for name in ("mmx", "mmx.cmd", "mmx.ps1"):
        candidate = _REPO_ROOT / "node_modules" / ".bin" / name
        if candidate.is_file():
            return candidate
    return None

AGENT_SKILLS = ["minimax-token-plan"]


def get_token_plan_key() -> str | None:
    return os.environ.get("MINIMAX_TOKEN_PLAN_KEY") or os.environ.get("MINIMAX_SUBSCRIPTION_KEY")


def mmx_base_command() -> list[str]:
    local_mmx = _local_mmx_binary()
    if local_mmx is not None:
        return [str(local_mmx)]
    if shutil.which("mmx"):
        return ["mmx"]
    if shutil.which("npx"):
        return ["npx", "mmx-cli"]
    raise DependencyError(
        "mmx CLI not found. Run: npm install (repo root)\n" + INSTALL_INSTRUCTIONS
    )


def mmx_is_available() -> bool:
    try:
        mmx_base_command()
        return True
    except DependencyError:
        return False


def global_mmx_flags() -> list[str]:
    flags: list[str] = []
    api_key = get_token_plan_key()
    if api_key:
        flags.extend(["--api-key", api_key])
    region = os.environ.get("MINIMAX_REGION")
    if region:
        flags.extend(["--region", region])
    return flags


def run_mmx(
    tool: BaseTool,
    args: list[str],
    *,
    timeout: int | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [*mmx_base_command(), *args, *global_mmx_flags(), "--quiet"]
    try:
        return tool.run_command(cmd, timeout=timeout, cwd=cwd)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        if detail:
            parsed = parse_json_stdout(detail)
            if parsed and isinstance(parsed.get("error"), dict):
                err = parsed["error"]
                hint = err.get("hint", "")
                message = err.get("message", detail)
                raise RuntimeError(
                    f"{message}" + (f" ({hint})" if hint else "")
                ) from exc
            raise RuntimeError(redact_secrets(detail)) from exc
        raise


def prepare_output_path(inputs: dict[str, Any], default_name: str) -> Path:
    output_path = Path(inputs.get("output_path") or default_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def success_result(
    *,
    tool_name: str,
    model: str,
    start: float,
    data: dict[str, Any],
    artifacts: list[str] | None = None,
    cost_usd: float = 0.0,
) -> ToolResult:
    payload = {
        "provider": PROVIDER,
        "billing": BILLING,
        "tool": tool_name,
        **data,
    }
    return ToolResult(
        success=True,
        data=payload,
        artifacts=artifacts or [],
        cost_usd=cost_usd,
        duration_seconds=round(time.time() - start, 2),
        model=model,
    )


def failure_result(error: str) -> ToolResult:
    return ToolResult(success=False, error=error)


def redact_secrets(text: str) -> str:
    key = get_token_plan_key()
    if key:
        return text.replace(key, "***")
    return text


def parse_json_stdout(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return None


def extract_task_id(text: str) -> str | None:
    data = parse_json_stdout(text)
    if data:
        for key in ("task_id", "taskId", "id"):
            value = data.get(key)
            if value:
                return str(value)
    match = re.search(r"\b\d{10,}\b", text)
    return match.group(0) if match else None
