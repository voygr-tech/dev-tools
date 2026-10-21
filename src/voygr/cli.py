import json
import os
import sys
import uuid
from contextlib import contextmanager

import click

from voygr import __version__
from voygr.client import Client, APIError, DEFAULT_BASE_URL, STANDARD_ATTRIBUTES
from voygr.config import load_config, save_api_key, delete_config
from voygr.csv_input import CSVInputError, read_places
from voygr.human import format_human


def resolve_base_url(ctx_base_url: str | None) -> str:
    return ctx_base_url or os.environ.get("VOYGR_BASE_URL") or DEFAULT_BASE_URL


def create_client(api_key: str | None = None, base_url: str = DEFAULT_BASE_URL, debug: bool = False) -> Client:
    return Client(api_key=api_key, base_url=base_url, debug=debug, retries=3)


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


def output(data: dict, ctx, cmd_name: str | None = None) -> None:
    """Output data as JSON (default) or human-readable (--human), formatted for `cmd_name` or the running command."""
    if ctx.obj.get("human"):
        click.echo(format_human(cmd_name or ctx.info_name, data, color=_use_color()))
    else:
        click.echo(json.dumps(data, ensure_ascii=False))


def error_output(error: APIError, ctx) -> None:
    if ctx.obj.get("human"):
        msg = f"Error: {error}"
        if _use_color():
            msg = click.style(msg, fg="red")
        click.echo(msg, err=True)
    else:
        data = {"error": error.error_code or "CLIENT_ERROR", "message": str(error)}
        click.echo(json.dumps(data, ensure_ascii=False), err=True)


def place_result_output(data: dict, ctx) -> None:
    """Print a validate or enrich result. A success:false body is a failure: error on stderr, exit 1."""
    if data.get("success") is False:
        error_output(APIError(data.get("error") or "Request failed.", error_code=data.get("error_code") or "API_ERROR"), ctx)
        ctx.exit(1)
    output(data, ctx)


@contextmanager
def api_session(ctx, *, auth: bool = True):
    """A client for one command. An APIError inside the block is printed and exits with code 1."""
    api_key = resolve_api_key(ctx.obj["api_key"]) if auth else None
    base_url = resolve_base_url(ctx.obj["base_url"])
    with create_client(api_key=api_key, base_url=base_url, debug=ctx.obj.get("debug", False)) as client:
        try:
            yield client
        except APIError as e:
            error_output(e, ctx)
            ctx.exit(1)


def _drop_none(fields: dict) -> dict:
    return {key: value for key, value in fields.items() if value is not None}


def parse_research(value: str) -> dict:
    """Turn `NAME` or `NAME=DESCRIPTION` into the research field the API takes."""
    name, _, description = value.partition("=")
    name, description = name.strip(), description.strip()
    if not name:
        raise click.BadParameter("a research field needs a name")
    if name in STANDARD_ATTRIBUTES:
        raise click.BadParameter(f"{name!r} is a standard attribute; use --attr {name}")
    if len(name) > 100:
        raise click.BadParameter("a research field name is at most 100 characters")
    if len(description) > 500:
        raise click.BadParameter("a research field description is at most 500 characters")
    return {"name": name, "description": description} if description else {"name": name}


def place_fields(address, country, lat, lng, place_id) -> dict:
    """The optional place fields of a request, under the API's names."""
    if (lat is None) != (lng is None):
        raise click.UsageError("--lat and --lng go together")
    return _drop_none({
        "address": address,
        "country": country.upper() if country else None,
        "latitude": lat,
        "longitude": lng,
        "id": place_id,
    })


def _bulk_places(name, country, lat, lng, place_id, input_file, no_wait, idempotency_key) -> list[dict] | None:
    """The places of a --file run, or None for a single-place run. A mix that fits neither is a usage error."""
    if input_file is None:
        if name is None:
            raise click.UsageError("Give a NAME, or --file PATH for a CSV of places.")
        if no_wait:
            raise click.UsageError("--no-wait only applies with --file.")
        if idempotency_key is not None:
            raise click.UsageError("--idempotency-key only applies with --file.")
        return None
    if name is not None:
        raise click.UsageError("Give a NAME or --file, not both.")
    if any(option is not None for option in (country, lat, lng, place_id)):
        raise click.UsageError("--country, --lat, --lng and --id describe one place; with --file, put them in the CSV.")
    try:
        return read_places(input_file)
    except CSVInputError as e:
        raise click.UsageError(str(e))


def _show_progress(status: dict) -> None:
    done = (status.get("progress") or {}).get("processed", 0)
    click.echo(f"\r{done}/{status.get('total_items', '?')}", nl=False, err=True)


def _wait(ctx, client, batch_id: str) -> dict:
    """Poll until the job ends. Ctrl-C stops waiting, leaves the job running and exits 130."""
    tty = sys.stderr.isatty()
    try:
        try:
            status = client.wait_for_job(batch_id, on_progress=_show_progress if tty else None)
        finally:
            if tty:
                click.echo(err=True)  # end the progress line
    except KeyboardInterrupt:
        status = None
    if status is None:
        click.echo(
            f"Stopped waiting. Job {batch_id} keeps running.\n"
            f"  Results: voygr jobs results {batch_id}\n"
            f"  Cancel:  voygr jobs cancel {batch_id}",
            err=True,
        )
        ctx.exit(130)
    return status


_ENDED_EARLY = {"failed": "failed", "cancelled": "was cancelled"}


def _finish_job(ctx, client, batch_id: str) -> None:
    """Wait for a job, print its rows as JSON Lines, then exit 1 if it failed or was cancelled.

    A failed or cancelled job still prints the rows it processed before its error. An API error while waiting or
    downloading exits 1 and says where to fetch the job again, so a retry never submits (and pays for) a second one.
    """
    try:
        status = _wait(ctx, client, batch_id)
        for row in client.iter_job_results(batch_id):
            click.echo(json.dumps(row, ensure_ascii=False))
    except APIError as e:
        error_output(e, ctx)
        if e.status_code != 404:  # a 404 means there is no such job to fetch
            click.echo(f"Job {batch_id} is still on the server. Results: voygr jobs results {batch_id}", err=True)
        ctx.exit(1)
    state = status.get("status")
    if state in _ENDED_EARLY:
        message = status.get("error") or f"Job {batch_id} {_ENDED_EARLY[state]}."
        error_output(APIError(message, error_code=status.get("error_code") or f"JOB_{state.upper()}"), ctx)
        ctx.exit(1)


def _run_job(ctx, client, submit, pois: list[dict], no_wait: bool, idempotency_key: str | None) -> None:
    """Submit one job and, unless `no_wait`, wait for it and print its rows.

    The key is fixed before the first attempt. If the submit fails without a clear answer, the job may exist, so
    the error names the key: re-running with it replays that job instead of paying for a second one.
    """
    key = idempotency_key or str(uuid.uuid4())
    try:
        submitted = submit(pois, idempotency_key=key)
    except APIError as e:
        error_output(e, ctx)
        if e.status_code is None or e.status_code >= 500:
            click.echo("The job may have been created. To retry without creating a second one, "
                       f"run the same command with --idempotency-key {key}", err=True)
        ctx.exit(1)
    batch_id = submitted["batch_id"]
    count = submitted.get("total_items", len(pois))
    click.echo(f"Submitted job {batch_id} ({count} {'place' if count == 1 else 'places'}).", err=True)
    if no_wait:
        output(submitted, ctx, "status")
    else:
        _finish_job(ctx, client, batch_id)


def _place_options(command):
    """The arguments and options validate and enrich share."""
    for decorator in reversed((
        click.argument("name", required=False, default=None),
        click.argument("address", required=False, default=None),
        click.option("--country", default=None, help="Two-letter country code, for example US."),
        click.option("--lat", type=float, default=None, help="Latitude. Use with --lng."),
        click.option("--lng", type=float, default=None, help="Longitude. Use with --lat."),
        click.option("--id", "place_id", default=None, help="Your own ID for the place. It is echoed in the result."),
        click.option("--file", "input_file", type=click.Path(exists=True, dir_okay=False), default=None,
                     help="CSV of places to run as one job, instead of NAME. Columns: name (required), "
                          "address, country, latitude, longitude, id."),
        click.option("--no-wait", is_flag=True, default=False,
                     help="With --file, print the job and exit instead of waiting for the results."),
        click.option("--idempotency-key", default=None, metavar="KEY",
                     help="With --file, the key of a submit that may have failed. The same command and key "
                          "replay that job instead of creating a second one."),
    )):
        command = decorator(command)
    return command


@click.group()
@click.option("--api-key", default=None, help="API key (overrides env and config).")
@click.option("--base-url", default=None, help="API base URL.")
@click.option("--human", is_flag=True, default=False, help="Human-readable output.")
@click.option("--debug", is_flag=True, default=False, help="Print HTTP debug info to stderr.")
@click.version_option(version=__version__, prog_name="voygr")
@click.pass_context
def cli(ctx, api_key, base_url, human, debug):
    """Voygr Places API client."""
    ctx.ensure_object(dict)
    ctx.obj["api_key"] = api_key
    ctx.obj["base_url"] = base_url
    ctx.obj["human"] = human
    ctx.obj["debug"] = debug


@cli.command()
@click.argument("email")
@click.option("--name", default=None, help="Your name. Defaults to email if not provided.")
@click.pass_context
def signup(ctx, email, name):
    """Request an API key via email."""
    with api_session(ctx, auth=False) as client:
        output(client.signup(email=email, name=name or email, src="voygr-cli"), ctx)


@cli.command()
@click.argument("email")
@click.pass_context
def recover(ctx, email):
    """Request a recovery link for a forgotten or lost API key.

    The link is sent to the provided email if an account exists. Clicking it
    rotates the existing key and emails the new one. The current key stops
    working at that moment.
    """
    with api_session(ctx, auth=False) as client:
        output(client.recover(email=email), ctx)


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
@_place_options
@click.pass_context
def validate(ctx, name, address, country, lat, lng, place_id, input_file, no_wait, idempotency_key):
    """Check that a place exists and whether it is open. With --file, check a CSV of places as one job."""
    places = _bulk_places(name, country, lat, lng, place_id, input_file, no_wait, idempotency_key)
    if places is not None:
        with api_session(ctx) as client:
            _run_job(ctx, client, client.submit_validate_job, places, no_wait, idempotency_key)
        return
    fields = place_fields(address, country, lat, lng, place_id)
    with api_session(ctx) as client:
        place_result_output(client.validate(name, **fields), ctx)


@cli.command()
@_place_options
@click.option("--attr", "attrs", multiple=True, type=click.Choice(STANDARD_ATTRIBUTES),
              help="Standard attribute to return. Repeat for several. Default: the standard set.")
@click.option("--research", multiple=True, type=parse_research, metavar="NAME[=DESCRIPTION]",
              help="Paid research question about the place, with an optional description. Repeat for several.")
@click.option("--summary", is_flag=True, default=False, help="Also return a short summary of the place.")
@click.option("--estimate", is_flag=True, default=False, help="Print the estimated cost without running or charging.")
@click.option("--max-credits", type=click.IntRange(min=0), default=None,
              help="Refuse a place that would cost more than this many credits. The cap is per place; "
                   "with --file, it is per row.")
@click.pass_context
def enrich(ctx, name, address, country, lat, lng, place_id, input_file, no_wait, idempotency_key,
           attrs, research, summary, estimate, max_credits):
    """Look up contact details, opening hours and research answers for a place.

    With --file, look up a CSV of places as one job; the attribute options apply to every row.
    """
    if input_file and estimate:
        raise click.UsageError(
            "--estimate prices a single place, so it cannot be used with --file. The per-place rates: voygr pricing"
        )
    places = _bulk_places(name, country, lat, lng, place_id, input_file, no_wait, idempotency_key)
    options = _drop_none({
        "estimate_only": estimate or None,
        "include_summary": summary or None,
        "max_credits": max_credits,
    })
    attributes = [*attrs, *research] or None
    if places is not None:
        row_options = _drop_none({"attributes": attributes, **options})
        with api_session(ctx) as client:
            _run_job(ctx, client, client.submit_enrich_job, [{**place, **row_options} for place in places], no_wait,
                     idempotency_key)
        return
    fields = place_fields(address, country, lat, lng, place_id)
    with api_session(ctx) as client:
        place_result_output(client.enrich(name, attributes=attributes, **fields, **options), ctx)


@cli.command()
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]), required=False, default=None)
def completions(shell):
    """Print shell completion setup instructions."""
    if shell is None:
        shell_path = os.environ.get("SHELL", "")
        if "zsh" in shell_path:
            shell = "zsh"
        elif "fish" in shell_path:
            shell = "fish"
        else:
            shell = "bash"

    lines = {
        "bash": 'eval "$(_VOYGR_COMPLETE=bash_source voygr)"',
        "zsh":  'eval "$(_VOYGR_COMPLETE=zsh_source voygr)"',
        "fish": '_VOYGR_COMPLETE=fish_source voygr | source',
    }
    click.echo(f"# Add this to your shell profile:\n{lines[shell]}")


@cli.command()
@click.pass_context
def usage(ctx):
    """Check your remaining credits."""
    with api_session(ctx) as client:
        output(client.usage(), ctx)


@cli.command()
@click.pass_context
def pricing(ctx):
    """Show what each request costs. No API key needed."""
    with api_session(ctx, auth=False) as client:
        output(client.pricing(), ctx)


@cli.group()
def jobs():
    """Check, fetch or cancel a bulk job started with --file."""


@jobs.command("status")
@click.argument("batch_id")
@click.pass_context
def jobs_status(ctx, batch_id):
    """Show a job's status and progress."""
    with api_session(ctx) as client:
        output(client.get_job(batch_id), ctx)


@jobs.command("results")
@click.argument("batch_id")
@click.pass_context
def jobs_results(ctx, batch_id):
    """Wait for a job, then print its rows.

    Rows are JSON Lines. A failed or cancelled job prints the rows it processed, then exits 1.
    """
    with api_session(ctx) as client:
        _finish_job(ctx, client, batch_id)


@jobs.command("cancel")
@click.argument("batch_id")
@click.pass_context
def jobs_cancel(ctx, batch_id):
    """Stop a job. Rows already processed stay billed and downloadable."""
    with api_session(ctx) as client:
        output(client.cancel_job(batch_id), ctx)
