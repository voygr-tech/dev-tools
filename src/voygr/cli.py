import json
import os

import click

from voygr.client import Client, APIError
from voygr.config import load_config, save_api_key, delete_config


def resolve_base_url(ctx_base_url: str | None) -> str:
    return ctx_base_url or os.environ.get("VOYGR_BASE_URL", "https://dev.voygr.tech")


def create_client(api_key: str | None = None, base_url: str = "https://dev.voygr.tech") -> Client:
    return Client(api_key=api_key, base_url=base_url)


def resolve_api_key(ctx_api_key: str | None) -> str | None:
    if ctx_api_key:
        return ctx_api_key
    env_key = os.environ.get("VOYGR_API_KEY")
    if env_key:
        return env_key
    config = load_config()
    return config.get("api_key")


def _use_color() -> bool:
    return os.environ.get("NO_COLOR") is None


def output(data: dict, ctx) -> None:
    """Output data as JSON (default) or human-readable (--human)."""
    if ctx.obj.get("human"):
        cmd_name = ctx.info_name
        click.echo(format_human(cmd_name, data))
    else:
        click.echo(json.dumps(data))


def error_output(error: APIError, ctx) -> None:
    if ctx.obj.get("human"):
        msg = f"Error: {error}"
        if _use_color():
            msg = click.style(msg, fg="red")
        click.echo(msg, err=True)
    else:
        data = {"error": error.error_code or "CLIENT_ERROR", "message": str(error)}
        click.echo(json.dumps(data), err=True)


def format_human(cmd_name: str, data: dict) -> str:
    formatters = {
        "signup": _format_signup,
        "login": _format_login,
        "logout": _format_logout,
        "check": _format_check,
        "usage": _format_usage,
    }
    formatter = formatters.get(cmd_name)
    if formatter:
        return formatter(data)
    return json.dumps(data, indent=2)


def _format_signup(data: dict) -> str:
    return data.get("message", "API key sent to your email.")


def _format_login(data: dict) -> str:
    msg = "API key saved."
    if _use_color():
        msg = click.style(msg, fg="green")
    return msg


def _format_logout(data: dict) -> str:
    return "API key removed."


def _format_check(data: dict) -> str:
    existence = data.get("existence_status", "unknown")
    open_closed = data.get("open_closed_status", "unknown")
    request_id = data.get("request_id", "")

    if _use_color():
        color_map = {"exists": "green", "not_exists": "red", "uncertain": "yellow"}
        existence_display = click.style(existence, fg=color_map.get(existence, "white"))
        oc_color_map = {"open": "green", "closed": "red", "uncertain": "yellow"}
        open_closed_display = click.style(open_closed, fg=oc_color_map.get(open_closed, "white"))
    else:
        existence_display = existence
        open_closed_display = open_closed

    lines = [
        f"Existence: {existence_display}",
        f"Status:    {open_closed_display}",
    ]
    if request_id:
        lines.append(f"Request:   {request_id}")
    return "\n".join(lines)


def _format_usage(data: dict) -> str:
    quota = data.get("quota_limit", 0)
    used = data.get("current_usage", 0)
    remaining = data.get("remaining", 0)
    pct = data.get("percentage_used", 0)
    period = data.get("period", "")
    status = data.get("status", "")

    lines = []
    if status or period:
        lines.append(f"Plan:    {status} ({period})")
    lines.append(f"Usage:   {used} / {quota} ({remaining} remaining)")

    # Simple progress bar
    bar_width = 20
    filled = int(bar_width * pct / 100) if quota > 0 else 0
    bar = "█" * filled + "░" * (bar_width - filled)
    lines.append(f"[{bar}] {pct:.1f}%")
    return "\n".join(lines)


@click.group()
@click.option("--api-key", default=None, help="API key (overrides env and config).")
@click.option("--base-url", default=None, help="API base URL.")
@click.option("--human", is_flag=True, default=False, help="Human-readable output.")
@click.pass_context
def cli(ctx, api_key, base_url, human):
    """Voygr Business Validation API client."""
    ctx.ensure_object(dict)
    ctx.obj["api_key"] = api_key
    ctx.obj["base_url"] = base_url
    ctx.obj["human"] = human


@cli.command()
@click.argument("email")
@click.option("--name", default=None, help="Your name. Defaults to email if not provided.")
@click.pass_context
def signup(ctx, email, name):
    """Request an API key via email."""
    name = name or email
    base_url = resolve_base_url(ctx.obj["base_url"])
    with create_client(base_url=base_url) as client:
        try:
            result = client.signup(email=email, name=name)
            output(result, ctx)
        except APIError as e:
            error_output(e, ctx)
            ctx.exit(1)


@cli.command()
@click.argument("api_key")
@click.pass_context
def login(ctx, api_key):
    """Store your API key locally."""
    save_api_key(api_key)
    output({"success": True, "message": "API key saved"}, ctx)


@cli.command()
@click.pass_context
def logout(ctx):
    """Remove stored API key."""
    delete_config()
    output({"success": True, "message": "API key removed"}, ctx)


@cli.command()
@click.argument("name")
@click.argument("address")
@click.pass_context
def check(ctx, name, address):
    """Check if a business exists and whether it's open."""
    api_key = resolve_api_key(ctx.obj["api_key"])
    base_url = resolve_base_url(ctx.obj["base_url"])
    with create_client(api_key=api_key, base_url=base_url) as client:
        try:
            result = client.check(name=name, address=address)
            output(result, ctx)
        except APIError as e:
            error_output(e, ctx)
            ctx.exit(1)


@cli.command()
@click.pass_context
def usage(ctx):
    """Check your remaining validation quota."""
    api_key = resolve_api_key(ctx.obj["api_key"])
    base_url = resolve_base_url(ctx.obj["base_url"])
    with create_client(api_key=api_key, base_url=base_url) as client:
        try:
            result = client.usage()
            output(result, ctx)
        except APIError as e:
            error_output(e, ctx)
            ctx.exit(1)
