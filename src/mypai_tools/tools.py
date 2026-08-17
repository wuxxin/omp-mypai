"""Utility functions for macro substitution, cron string normalization, and file I/O."""

import json
import os
from typing import Any

import apscheduler

APSCHEDULER_VERSION = getattr(apscheduler, "__version__", "3.0.0")
IS_APSCHEDULER_V4 = APSCHEDULER_VERSION.startswith("4")


def substitute_vars(val: Any, extra_vars: dict[str, Any] | None = None) -> Any:
    """Recursively expand #{VARNAME} and #[VARNAME] environment and internal variables."""
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
            substitute_vars(k, extra_vars): substitute_vars(v, extra_vars) for k, v in val.items()
        }
    elif isinstance(val, list):
        return [substitute_vars(item, extra_vars) for item in val]
    return val


def build_internal_vars(
    job: dict[str, Any],
    return_code: int = 0,
    output: str = "",
    error: str = "",
    obj: Any = None,
    http_code: int = 0,
    duration: float = 0.0,
) -> dict[str, Any]:
    """Construct standard internal execution variables for result prompt template substitution.

    Exposes strictly _UPPERCASE internal variables:
    _ACTION, _ARGS, _KWARGS, _OPTS, _RETURN_CODE, _OUTPUT, _ERROR, _OBJECT, _HTTP_CODE, _DURATION, _JOB_ID, _JOB_NAME
    """
    action = job.get("action", "")
    args = job.get("args", "")
    kwargs = job.get("kwargs", "")
    opts = job.get("opts", "")

    return {
        "_ACTION": action,
        "_ARGS": args,
        "_KWARGS": kwargs,
        "_OPTS": opts,
        "_RETURN_CODE": return_code,
        "_OUTPUT": output,
        "_ERROR": error,
        "_OBJECT": obj,
        "_HTTP_CODE": http_code,
        "_DURATION": duration,
        "_JOB_ID": job.get("id", ""),
        "_JOB_NAME": job.get("name", "Unnamed Job"),
    }


def evaluate_and_dispatch_result_prompt(
    job: dict[str, Any],
    internal_vars: dict[str, Any],
    is_success: bool,
    default_output: str,
    daemon_queue: Any | None = None,
    session_mgr: Any | None = None,
    dispatch_fn: Any | None = None,
) -> str:
    """Evaluate result/error prompt template macros and dispatch to OMP session via TurnQueue."""
    if dispatch_fn is None:
        from mypai_tools.executors.omp_rpc_executor import dispatch_result_to_omp

        dispatch_fn = dispatch_result_to_omp

    res_dict = job.get("result") if isinstance(job.get("result"), dict) else {}
    if not is_success:
        result_action = (
            res_dict.get("error_action")
            or res_dict.get("action")
            or job.get("result_error_action")
            or job.get("result_action")
            or "log"
        )
        template = (
            res_dict.get("error_prompt")
            or res_dict.get("prompt")
            or job.get("result_error_prompt")
            or job.get("result_prompt")
            or ""
        )
    else:
        result_action = res_dict.get("action") or job.get("result_action") or "log"
        template = res_dict.get("prompt") or job.get("result_prompt") or ""

    if isinstance(template, str):
        template = template.strip()

    if template:
        if "#" in template:
            final_output = substitute_vars(template, extra_vars=internal_vars)
        else:
            final_output = f"{template}\n{default_output}"
    else:
        final_output = default_output

    clean_action = str(result_action or "log").lower().strip()
    if clean_action not in ("log", "ignore", "none", ""):
        dispatch_fn(
            clean_action,
            final_output,
            daemon_queue=daemon_queue,
            session_mgr=session_mgr,
            job_id=job.get("id", ""),
        )

    return final_output


def format_system_trigger_prompt(
    prompt: str, source: str = "", context: dict[str, Any] | None = None
) -> str:
    """Format automated non-human prompts with a standardized system trigger header."""
    if (
        not prompt
        or not source
        or source in ("webui", "signal", "interactive", "human")
        or prompt.startswith("[SYSTEM TRIGGER")
    ):
        return prompt

    job_name = context.get("name") if isinstance(context, dict) else None
    if source == "cron":
        tag = f"CRON ({job_name})" if job_name else "CRON"
    elif source == "executor_result":
        tag = f"EXECUTOR_RESULT ({job_name})" if job_name else "EXECUTOR_RESULT"
    elif source == "spooler":
        tag = "INPUT_SPOOLER"
    elif source == "acp":
        tag = f"ACP_SUBAGENT ({job_name})" if job_name else "ACP_SUBAGENT"
    else:
        tag = str(source).upper()

    return f"[SYSTEM TRIGGER: {tag}]\n{prompt}"


def extract_omp_prompt(job: dict[str, Any]) -> str:
    """Extract OMP prompt text strictly from canonical job attributes."""
    if not isinstance(job, dict):
        return ""

    kwargs_raw = job.get("kwargs") or {}
    rpc_kwargs: dict[str, Any] = {}
    if isinstance(kwargs_raw, str) and kwargs_raw.strip():
        if kwargs_raw.strip().startswith("{"):
            try:
                rpc_kwargs = json.loads(kwargs_raw)
            except Exception:  # noqa: BLE001
                pass
        else:
            rpc_kwargs = {"prompt": kwargs_raw}
    elif isinstance(kwargs_raw, dict):
        rpc_kwargs = dict(kwargs_raw)

    prompt_val = rpc_kwargs.get("prompt")
    if prompt_val and isinstance(prompt_val, str) and prompt_val.strip():
        return prompt_val.strip()

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

    if job.get("prompt") and isinstance(job["prompt"], str) and job["prompt"].strip():
        return job["prompt"].strip()

    action = str(job.get("action", "") or "").strip()
    if action and action.lower() not in (
        "prompt",
        "steer",
        "followup",
        "abort_and_prompt",
    ):
        return action

    return ""


def normalize_cron_expression(expr: str) -> str:
    """Normalize 5-field cron expression for APScheduler version compatibility."""
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
        raise ValueError(f"Expected list of jobs in '{abs_path}', got {type(jobs_list).__name__}")
    return jobs_list


def dump_jobs_file(file_path: str, jobs: list[dict[str, Any]], fmt: str | None = None) -> str:
    """Dump cron jobs list to a YAML or JSON file."""
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
