"""Text for `--human` output, one formatter per command."""
import json

import click

_BAR_WIDTH = 20
_PLACE_STATUS_COLORS = {"open": "green", "closed": "red", "not_exists": "red", "unknown": "yellow"}
_JOB_STATUS_COLORS = {"completed": "green", "failed": "red", "cancelled": "yellow"}


def format_human(cmd_name: str, data: dict, *, color: bool) -> str:
    formatter = _FORMATTERS.get(cmd_name)
    if formatter is None:
        return json.dumps(data, indent=2, ensure_ascii=False)
    return formatter(data, color)


def _paint(text: str, fg: str | None, color: bool) -> str:
    return click.style(text, fg=fg) if color and fg else text


def _credits(n) -> str:
    return f"{n} {'credit' if n == 1 else 'credits'}"


def _signup(data: dict, color: bool) -> str:
    message = data.get("message", "API key sent to your email.")
    return f"{message}\nTo recover a key from the terminal, run: voygr recover <email>"


def _recover(data: dict, color: bool) -> str:
    return data.get("message", "If an account exists for that email, a recovery link has been sent.")


def _login(data: dict, color: bool) -> str:
    return _paint(data.get("message", "API key saved."), "green", color)


def _logout(data: dict, color: bool) -> str:
    return data.get("message", "API key removed.")


def _validate(data: dict, color: bool) -> str:
    operational = data.get("operational_status") or {}
    status = operational.get("status") or "unknown"
    reason = operational.get("closure_reason")
    confidence = data.get("existence_confidence")

    lines = [
        "Existence: " + (f"{confidence:.2f} confidence" if isinstance(confidence, (int, float)) else "unknown"),
        "Status:    " + _paint(f"{status} ({reason})" if reason else status, _PLACE_STATUS_COLORS.get(status), color),
    ]
    if data.get("request_id"):
        lines.append(f"Request:   {data['request_id']}")
    return "\n".join(lines)


def _cell(cell: dict) -> str:
    value = cell.get("value")
    if value is None:
        return (cell.get("abstain_reason") or "unavailable").replace("_", " ")
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    confidence = cell.get("confidence")
    return f"{text} ({confidence})" if confidence else text


def _enrich(data: dict, color: bool) -> str:
    meta = data.get("meta") or {}
    if meta.get("stopped_reason") == "estimate_only":
        return f"Estimated cost: {_credits(meta.get('estimated_credits', 0))}. Nothing was charged."

    lines = []
    # Existence and open/closed come back with the attributes when the place could be checked.
    existence, operational = data.get("status"), data.get("operational_status")
    existence = existence if isinstance(existence, dict) else {}
    operational = operational if isinstance(operational, dict) else {}
    if existence or operational:
        verdict = {"existence_confidence": existence.get("existence_confidence"), "operational_status": operational}
        lines.append(_validate(verdict, color))
    lines += [f"{name}: {_cell(cell)}" for name, cell in (data.get("attributes") or {}).items()]
    if data.get("place_summary"):
        lines.append(f"Summary: {data['place_summary']}")
    return "\n".join(lines) or "No attributes returned."


def _usage(data: dict, color: bool) -> str:
    quota = data.get("quota_limit", 0)
    available = data.get("available", data.get("remaining", 0))
    pct = data.get("percentage_used") or 0
    period = data.get("period", "")
    status = data.get("status", "")
    if period:
        status = f"{status} ({period})".strip()

    lines = []
    if data.get("tier"):
        lines.append(f"Tier:      {data['tier']}")
    if status:
        lines.append(f"Status:    {status}")
    lines.append(f"Available: {_credits(available)}")
    lines.append(f"Usage:     {data.get('current_usage', 0)} / {quota}")
    filled = min(int(_BAR_WIDTH * pct / 100), _BAR_WIDTH) if quota > 0 else 0
    lines.append(f"[{'█' * filled}{'░' * (_BAR_WIDTH - filled)}] {pct:.1f}%")
    # Free keys report a far-future placeholder date for a lifetime allowance, so it is not shown.
    if data.get("reset_date") and period != "lifetime":
        lines.append(f"Resets:    {data['reset_date']}")
    return "\n".join(lines)


def _pricing(data: dict, color: bool) -> str:
    lines = [
        f"{rate.get('label') or rate.get('key')}: {_credits(rate.get('credits'))} per {rate.get('per')}"
        for rate in data.get("rates") or []
    ]
    return "\n".join(lines) or "No rates returned."


def _job_status(data: dict, color: bool) -> str:
    status = data.get("status", "unknown")
    lines = [f"Job {data.get('batch_id', '')}: {_paint(status, _JOB_STATUS_COLORS.get(status), color)}"]
    progress = data.get("progress")
    if progress:
        lines.append(
            f"Progress: {progress.get('processed', 0)}/{data.get('total_items', '?')}, "
            f"{progress.get('failed', 0)} failed"
        )
    if data.get("error"):
        lines.append(f"Error: {data['error']}")
    return "\n".join(lines)


def _job_cancel(data: dict, color: bool) -> str:
    return _job_status(data, color) + "\nRows already processed stay billed and downloadable."


_FORMATTERS = {
    "signup": _signup,
    "recover": _recover,
    "login": _login,
    "logout": _logout,
    "validate": _validate,
    "enrich": _enrich,
    "usage": _usage,
    "pricing": _pricing,
    "status": _job_status,
    "cancel": _job_cancel,
}
