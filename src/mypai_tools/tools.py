"""Utility functions for macro substitution, cron string normalization, and file I/O."""

import json
import os
from typing import Any

import apscheduler

APSCHEDULER_VERSION = getattr(apscheduler, "__version__", "3.0.0")
IS_APSCHEDULER_V4 = APSCHEDULER_VERSION.startswith("4")


def substitute_vars(val: Any, extra_vars: dict[str, Any] | None = None) -> Any:
    """Recursively expand #{VARNAME} and #[VARNAME] environment and internal variables.

    Supports #{VARNAME} and #[VARNAME] syntax for:
    1. System & Process Environment Variables (e.g. #{HINDSIGHT_API_URL}, #[HOME])
    2. Internal Execution Variables (e.g. #[_RETURN_CODE], #[_OUTPUT], #[_ERROR], #[_OBJECT], #[_HTTP_CODE], #[_DURATION], #[_JOB_ID], #[_JOB_NAME])
    """
    combined_vars: dict[str, Any] = dict(os.environ)
    if extra_vars:
        combined_vars.update(extra_vars)

    if isinstance(val, str):
        expanded = val
        for k, v in combined_vars.items():
            placeholders = (f"#{{{k}}}", f"#[{k}]")
            v_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            for placeholder in placeholders:
                if placeholder in expanded:
                    expanded = expanded.replace(placeholder, v_str)
        return expanded
    elif isinstance(val, dict):
        return {
            substitute_vars(k, extra_vars): substitute_vars(v, extra_vars)
            for k, v in val.items()
        }
    elif isinstance(val, list):
        return [substitute_vars(item, extra_vars) for item in val]
    return val


substitute_env_vars = substitute_vars


def extract_omp_prompt(job: dict[str, Any]) -> str:
    """Extract OMP prompt text strictly from canonical job attributes.

    Priority:
    1. kwargs["prompt"]
    2. args[0] (if string or list containing a prompt)
    3. job["prompt"]
    4. job["result_prompt"]
    5. job["action"] (if not a standard RPC mode verb)

    Leading and trailing whitespace is stripped (.strip()).
    A whitespace-only string (e.g. "   \n\t  ") is evaluated as empty ("").
    No non-standard naming aliases or workflow cross-overs are used.
    """
    if not isinstance(job, dict):
        return ""

    # 1. Parse kwargs["prompt"]
    kwargs_raw = job.get("kwargs") or {}
    rpc_kwargs: dict[str, Any] = {}
    if isinstance(kwargs_raw, str) and kwargs_raw.strip():
        if kwargs_raw.strip().startswith("{"):
            try:
                rpc_kwargs = json.loads(kwargs_raw)
            except Exception:  # noqa: BLE001, S110
                pass
        else:
            rpc_kwargs = {"prompt": kwargs_raw}
    elif isinstance(kwargs_raw, dict):
        rpc_kwargs = dict(kwargs_raw)

    prompt_val = rpc_kwargs.get("prompt")
    if prompt_val and isinstance(prompt_val, str) and prompt_val.strip():
        return prompt_val.strip()

    # 2. Parse args[0]
    args_raw = job.get("args") or []
    rpc_args: list[Any] = []
    if isinstance(args_raw, str) and args_raw.strip():
        if args_raw.strip().startswith("["):
            try:
                rpc_args = json.loads(args_raw)
            except Exception:  # noqa: BLE001
                rpc_args = [args_raw]
        else:
            rpc_args = [args_raw]
    elif isinstance(args_raw, list):
        rpc_args = args_raw

    if rpc_args and isinstance(rpc_args[0], str) and rpc_args[0].strip():
        return rpc_args[0].strip()

    # 3. Top-level 'prompt'
    if job.get("prompt") and isinstance(job["prompt"], str) and job["prompt"].strip():
        return job["prompt"].strip()

    # 4. 'result_prompt'
    if (
        job.get("result_prompt")
        and isinstance(job["result_prompt"], str)
        and job["result_prompt"].strip()
    ):
        return job["result_prompt"].strip()

    # 5. Non-verb 'action'
    action = str(job.get("action", "") or "").strip()
    if action and action.lower() not in (
        "prompt",
        "prompt_and_wait",
        "steer",
        "followup",
        "abort_and_prompt",
        "switch_session",
        "branch",
    ):
        return action

    return ""


def normalize_cron_expression(expr: str) -> str:
    """Normalize 5-field cron expression for APScheduler version compatibility.

    Standard cron convention:
    0 = Sun, 1 = Mon, 2 = Tue, 3 = Wed, 4 = Thu, 5 = Fri, 6 = Sat, 7 = Sun.

    APScheduler < 4.0 convention:
    0 = Mon, 1 = Tue, 2 = Wed, 3 = Thu, 4 = Fri, 5 = Sat, 6 = Sun.

    On APScheduler < 4.0, transparently remaps day-of-week (0->6, 1->0, 2->1, 3->2, 4->3, 5->4, 6->5, 7->6)
    so users can always supply standard cron syntax (0 = Sunday).
    """
    if IS_APSCHEDULER_V4 or not expr or not isinstance(expr, str):
        return expr

    parts = expr.strip().split()
    if len(parts) != 5:
        return expr

    minute, hour, dom, month, dow = parts

    def remap_token(token: str) -> str:
        mapping = {
            "0": "6",
            "7": "6",
            "1": "0",
            "2": "1",
            "3": "2",
            "4": "3",
            "5": "4",
            "6": "5",
            "sun": "6",
            "mon": "0",
            "tue": "1",
            "wed": "2",
            "thu": "3",
            "fri": "4",
            "sat": "5",
        }
        low = token.lower()
        return mapping.get(low, token)

    if "," in dow:
        subparts = [remap_token(t) for t in dow.split(",")]
        new_dow = ",".join(subparts)
    elif "-" in dow and not dow.startswith("*"):
        range_parts = dow.split("-", 1)
        start = remap_token(range_parts[0])
        end = remap_token(range_parts[1])
        new_dow = f"{start}-{end}"
    else:
        new_dow = remap_token(dow)

    return f"{minute} {hour} {dom} {month} {new_dow}"


def load_jobs_file(file_path: str) -> list[dict[str, Any]]:
    """Load cron jobs list from a YAML or JSON file."""
    import yaml

    abs_path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Import file '{abs_path}' not found.")

    with open(abs_path, "r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except Exception:  # noqa: BLE001
            f.seek(0)
            data = json.load(f)

    jobs_list = data.get("jobs", data) if isinstance(data, dict) else data
    if not isinstance(jobs_list, list):
        raise ValueError(  # noqa: TRY004
            f"Expected list of jobs in '{abs_path}', got {type(jobs_list).__name__}"
        )
    return jobs_list


def dump_jobs_file(
    file_path: str, jobs: list[dict[str, Any]], fmt: str | None = None
) -> str:
    """Dump cron jobs list to a YAML or JSON file.

    Defaults to YAML format unless fmt is 'json' or file_path ends with '.json'.
    """
    import yaml

    abs_path = os.path.abspath(os.path.expanduser(file_path))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    target_fmt = (fmt or "").lower().strip()
    if not target_fmt:
        if abs_path.endswith(".json"):
            target_fmt = "json"
        else:
            target_fmt = "yaml"

    with open(abs_path, "w", encoding="utf-8") as f:
        if target_fmt == "json":
            json.dump({"jobs": jobs}, f, indent=2)
        else:
            yaml.safe_dump({"jobs": jobs}, f, sort_keys=False, default_flow_style=False)

    return abs_path
