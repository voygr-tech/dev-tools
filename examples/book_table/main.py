"""Preview a restaurant booking brief; explicitly confirm to call with PlaceCall."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import click
import httpx


def load_request(path: Path) -> dict:
    """Read the exact request saved before submission, within its recovery window."""
    with path.open(encoding="utf-8") as source:
        content = source.read(65_537)
    if len(content) > 65_536:
        raise ValueError("Recovery request is too large")
    record = json.loads(content)
    if (not isinstance(record, dict) or set(record) != {"version", "created_at", "idempotency_key", "body"}
            or record["version"] != 1):
        raise ValueError("Invalid saved recovery request")
    key, body, created_at = record["idempotency_key"], record["body"], record["created_at"]
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", key):
        raise ValueError("Invalid saved idempotency key")
    if (not isinstance(body, dict) or set(body) != {"target_phone", "brief", "language"}
            or not isinstance(body["target_phone"], str)
            or not re.fullmatch(r"\+1[2-9]\d{2}[2-9]\d{6}", body["target_phone"])
            or not isinstance(body["brief"], str) or not 1 <= len(body["brief"]) <= 4000
            or body["language"] != "en" or not isinstance(created_at, str)):
        raise ValueError("Invalid saved call body or timestamp")
    created = datetime.fromisoformat(created_at)
    if created.tzinfo is None or created.utcoffset() is None:
        raise ValueError("Saved request needs an offset timestamp")
    age = (datetime.now(timezone.utc) - created).total_seconds()
    if not 0 <= age < 24 * 60 * 60:
        raise ValueError("Saved request is outside its 24-hour recovery window; inspect account calls before calling again")
    return record


def save_request(body: dict, idempotency_key: str) -> Path:
    """Persist recovery details before HTTP, without storing the API credential."""
    directory = Path(".voygr-calls")
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / f"{hashlib.sha256(idempotency_key.encode('ascii')).hexdigest()}.json"
    record = {"version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "idempotency_key": idempotency_key, "body": body}
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        saved = load_request(path)
        if saved["body"] != body or saved["idempotency_key"] != idempotency_key:
            raise ValueError("This idempotency key already belongs to a different saved request")
    else:
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            json.dump(record, destination)
            destination.flush()
            os.fsync(destination.fileno())
    return path


def booking_body(phone: str, restaurant: str, name: str, party_size: int, at: str, callback: str) -> dict:
    if not re.fullmatch(r"\+1[2-9]\d{2}[2-9]\d{6}", phone):
        raise ValueError("--phone needs a US +1 number in E.164 format")
    if not re.fullmatch(r"\+[1-9]\d{6,14}", callback):
        raise ValueError("--callback needs an E.164 phone number")
    if not restaurant.strip() or not name.strip():
        raise ValueError("Restaurant and reservation name must be nonempty")
    moment = datetime.fromisoformat(at.replace("Z", "+00:00"))
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("--at needs an explicit UTC offset, such as 2027-01-15T19:00:00-08:00")
    if moment <= datetime.now(timezone.utc):
        raise ValueError("--at must be in the future")
    brief = (
        f"Call {restaurant.strip()} to request a table for {party_size} people on {at}, "
        f"in the restaurant's local time with the supplied UTC offset, under {name.strip()}. "
        f"The callback number is {callback}. "
        "Do not accept deposits, payment commitments, cancellation fees, substitutions or changes "
        "to the date, time or party size. If unavailable or another decision is needed, "
        "report what the restaurant said and end the call. "
        "Read back the reservation name, date, time, party size and any confirmation number. "
        "Thank the person and end the call. Report whether the booking was confirmed."
    )
    if len(brief) > 4000:
        raise ValueError("Booking brief exceeds the API's 4000-character limit")
    return {"target_phone": phone, "brief": brief, "language": "en"}


@click.command()
@click.option("--phone", help="Restaurant's US phone number in +1 E.164 format.")
@click.option("--restaurant", help="Restaurant name.")
@click.option("--name", help="Name on the reservation.")
@click.option("--party-size", type=click.IntRange(min=1), help="Number of guests.")
@click.option("--at", help="Future local ISO datetime with UTC offset, e.g. 2027-01-15T19:00:00-08:00.")
@click.option("--callback", help="Your callback number in E.164 format.")
@click.option("--confirm-call", is_flag=True, help="Place a real phone call using the previewed details.")
@click.option("--idempotency-key", help="Unique call key; keep it to retry the identical request.")
@click.option("--call-id", help="Read an existing call's result; does not place another call.")
@click.option("--retry-request", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Replay a saved request within 24 hours, including after its booking time.")
def main(phone, restaurant, name, party_size, at, callback, confirm_call, idempotency_key, call_id, retry_request):
    """Preview a table-booking request, confirm a call, or read an existing call."""
    try:
        details = {"phone": phone, "restaurant": restaurant, "name": name,
                   "party-size": party_size, "at": at, "callback": callback}
        if call_id is not None:
            if confirm_call or idempotency_key is not None or retry_request is not None or any(v is not None for v in details.values()):
                raise ValueError("Use --call-id by itself, without booking or confirmation options")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", call_id):
                raise ValueError("Invalid --call-id")
            body = None
        else:
            if retry_request is not None:
                if idempotency_key is not None or any(v is not None for v in details.values()):
                    raise ValueError("--retry-request uses its saved key and body; do not add booking options or another key")
                saved = load_request(retry_request)
                body, idempotency_key = saved["body"], saved["idempotency_key"]
            else:
                missing = [f"--{k}" for k, value in details.items() if value is None]
                if missing:
                    raise ValueError(f"Booking requires: {', '.join(missing)}")
                body = booking_body(phone, restaurant, name, party_size, at, callback)
            if not confirm_call:
                click.echo(json.dumps(body, ensure_ascii=False, indent=2))
                click.echo("Preview only. Review the details before adding --confirm-call and --idempotency-key.", err=True)
                return
            if not idempotency_key or not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", idempotency_key):
                raise ValueError("--confirm-call requires a nonempty ASCII --idempotency-key without spaces")

        key = (os.environ.get("PLACECALL_API_KEY") or os.environ.get("VOYGR_API_KEY", "")).strip()
        if not key:
            raise ValueError("Set PLACECALL_API_KEY or VOYGR_API_KEY before using the API")
        headers = {"X-API-Key": key}
        if call_id is None:
            request_path = retry_request if retry_request is not None else save_request(body, idempotency_key)
            headers.update({"Idempotency-Key": idempotency_key, "X-Client-Surface": "gh-repo"})
            click.echo(f"Idempotency key: {idempotency_key}. Keep the same key and body for retries within 24 hours.", err=True)
            click.echo(f"Saved request: {request_path}. Replay with: python -m examples.book_table.main --retry-request {request_path} --confirm-call", err=True)
        recovery = ("Read the same call ID again; do not place another call." if call_id else
                    "The call may have been placed. Retry only with the same key and body within 24 hours; do not redial with a new key.")
        try:
            with httpx.Client(timeout=60.0, follow_redirects=False) as client:
                if call_id:
                    response = client.get(f"https://api.voygr.tech/calls/{quote(call_id, safe='')}", headers=headers)
                else:
                    response = client.post("https://api.voygr.tech/calls", headers=headers, json=body)
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("status"), str):
                raise ValueError("Unexpected call response schema")
            if call_id:
                if "result" not in data:
                    raise ValueError("Call readback is missing result")
            else:
                returned_id = data.get("call_id")
                if not isinstance(returned_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", returned_id):
                    raise ValueError("Call response is missing a valid call_id")
                click.echo(f"Call: {returned_id}. Read it with: python -m examples.book_table.main --call-id {returned_id}", err=True)
            click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        except httpx.HTTPStatusError as exc:
            raise ValueError(f"API returned HTTP {exc.response.status_code}. {recovery}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ValueError(f"API request failed ({type(exc).__name__}). {recovery}") from exc
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc


if __name__ == "__main__":
    main()
