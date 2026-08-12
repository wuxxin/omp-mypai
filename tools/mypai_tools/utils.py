"""Utility functions for macro substitution and cron string normalization."""

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
