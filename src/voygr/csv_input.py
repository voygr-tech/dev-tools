"""Read a CSV of places into job rows. Every problem names its line; the header is line 1."""
import csv
import os

from voygr.client import MAX_JOB_ROWS


class CSVInputError(ValueError):
    """The file cannot be sent as a job. The message starts with `line N:`."""


# Column -> longest value the API accepts.
_MAX_LENGTH = {"name": 200, "address": 500, "id": 100}


def _cell(row: dict, column: str) -> str:
    return (row.get(column) or "").strip()


def _coordinate(row: dict, column: str, limit: int, line: int) -> float | None:
    text = _cell(row, column)
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        raise CSVInputError(f"line {line}: {column} {text!r} is not a number")
    if not -limit <= value <= limit:  # also rejects nan
        raise CSVInputError(f"line {line}: {column} {text} is outside -{limit} to {limit}")
    return value


def _place(row: dict, line: int) -> dict:
    for column, longest in _MAX_LENGTH.items():
        length = len(_cell(row, column))
        if length > longest:
            raise CSVInputError(f"line {line}: {column} is {length} characters; the limit is {longest}")
    if not _cell(row, "name"):
        raise CSVInputError(f"line {line}: name is empty")
    place = {"poi_name": _cell(row, "name")}
    for column in ("address", "id"):
        if _cell(row, column):
            place[column] = _cell(row, column)
    if _cell(row, "country"):
        place["country"] = _cell(row, "country").upper()

    latitude = _coordinate(row, "latitude", 90, line)
    longitude = _coordinate(row, "longitude", 180, line)
    if (latitude is None) != (longitude is None):
        raise CSVInputError(f"line {line}: latitude and longitude go together; fill in both or neither")
    if latitude is not None:
        place["latitude"], place["longitude"] = latitude, longitude
    return place


def _first_bad_line(path) -> int:
    with open(path, "rb") as f:
        for number, raw in enumerate(f, 1):
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                return number
    return 1


def read_places(path: str | os.PathLike) -> list[dict]:
    """The file's places as job rows: `poi_name` plus any address, country, latitude, longitude and id.

    Columns match after strip and lower-case; unknown columns are ignored and fully blank rows skipped.
    """
    places = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise CSVInputError("line 1: the file is empty; it needs a header row with a name column")
            reader.fieldnames = [column.strip().lower() for column in reader.fieldnames]
            if "name" not in reader.fieldnames:
                raise CSVInputError("line 1: the header needs a name column")
            for row in reader:
                if not any(isinstance(value, str) and value.strip() for value in row.values()):
                    continue
                if len(places) == MAX_JOB_ROWS:
                    raise CSVInputError(f"line {reader.line_num}: a job takes at most {MAX_JOB_ROWS:,} places")
                places.append(_place(row, reader.line_num))
    except UnicodeDecodeError:
        raise CSVInputError(f"line {_first_bad_line(path)}: the file is not UTF-8; save it as CSV UTF-8")
    except csv.Error as e:
        raise CSVInputError(f"line {reader.line_num + 1}: {e}")  # the row that failed was not counted yet
    if not places:
        raise CSVInputError("line 1: the file has a header but no places")
    return places
