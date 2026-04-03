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


def output(data: dict, pretty: bool = False) -> None:
    if pretty:
        click.echo(json.dumps(data, indent=2))
    else:
        click.echo(json.dumps(data))


def error_output(error: APIError) -> None:
    data = {"error": error.error_code or "CLIENT_ERROR", "message": str(error)}
    click.echo(json.dumps(data), err=True)


@click.group()
@click.option("--api-key", default=None, help="API key (overrides env and config).")
@click.option("--base-url", default=None, help="API base URL.")
@click.option("--pretty", is_flag=True, default=False, help="Pretty-print JSON output.")
@click.pass_context
def cli(ctx, api_key, base_url, pretty):
    """Voygr Business Validation API client."""
    ctx.ensure_object(dict)
    ctx.obj["api_key"] = api_key
    ctx.obj["base_url"] = base_url
    ctx.obj["pretty"] = pretty


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
            output(result, ctx.obj["pretty"])
        except APIError as e:
            error_output(e)
            ctx.exit(1)


@cli.command()
@click.argument("api_key")
@click.pass_context
def login(ctx, api_key):
    """Store your API key locally."""
    save_api_key(api_key)
    output({"success": True, "message": "API key saved"}, ctx.obj["pretty"])


@cli.command()
@click.pass_context
def logout(ctx):
    """Remove stored API key."""
    delete_config()
    output({"success": True, "message": "API key removed"}, ctx.obj["pretty"])


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
            output(result, ctx.obj["pretty"])
        except APIError as e:
            error_output(e)
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
            output(result, ctx.obj["pretty"])
        except APIError as e:
            error_output(e)
            ctx.exit(1)
