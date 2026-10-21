import pytest

from voygr.csv_input import CSVInputError, read_places


@pytest.fixture
def write_csv(tmp_path):
    """Write `text` (or raw `data`) to a CSV file, byte for byte, and return its path."""
    def write(text="", *, data=None):
        path = tmp_path / "places.csv"
        path.write_bytes(data if data is not None else text.encode("utf-8"))
        return path

    return write


def read_error(path) -> str:
    with pytest.raises(CSVInputError) as exc_info:
        read_places(path)
    return str(exc_info.value)


def test_name_and_address_only(write_csv):
    path = write_csv("name,address\nStarbucks,1390 Market St\n")
    assert read_places(path) == [{"poi_name": "Starbucks", "address": "1390 Market St"}]


def test_all_columns(write_csv):
    path = write_csv(
        "name,address,country,latitude,longitude,id\n"
        "Blue Bottle,66 Mint St,us,37.78,-122.41,p-1\n"
    )
    assert read_places(path) == [{
        "poi_name": "Blue Bottle", "address": "66 Mint St", "country": "US",
        "latitude": 37.78, "longitude": -122.41, "id": "p-1",
    }]


def test_accepts_str_and_path(write_csv):
    path = write_csv("name\nX\n")
    assert read_places(str(path)) == read_places(path) == [{"poi_name": "X"}]


def test_name_only_column(write_csv):
    assert read_places(write_csv("name\nA\nB\n")) == [{"poi_name": "A"}, {"poi_name": "B"}]


def test_excel_style_file(write_csv):
    data = b"\xef\xbb\xbf" + b"Name ,ADDRESS,Notes\r\nCafe Roma,1 Main St,x\r\nBar Uno,,y\r\n,,\r\n\r\n\r\n"
    assert read_places(write_csv(data=data)) == [
        {"poi_name": "Cafe Roma", "address": "1 Main St"},
        {"poi_name": "Bar Uno"},
    ]


def test_header_is_case_and_space_insensitive(write_csv):
    path = write_csv(" NAME ,  Country,LATITUDE , Longitude\nX,gb,51.5,-0.12\n")
    assert read_places(path) == [{"poi_name": "X", "country": "GB", "latitude": 51.5, "longitude": -0.12}]


def test_unknown_columns_ignored(write_csv):
    path = write_csv("rank,name,phone\n1,X,555\n")
    assert read_places(path) == [{"poi_name": "X"}]


def test_values_are_stripped_and_empty_ones_dropped(write_csv):
    path = write_csv("name,address,country,latitude,longitude,id\n  X  ,   ,  ,  ,  ,  \n")
    assert read_places(path) == [{"poi_name": "X"}]


def test_short_and_long_rows(write_csv):
    path = write_csv("name,address\nA\nB,2 Main St,extra,cells\n")
    assert read_places(path) == [{"poi_name": "A"}, {"poi_name": "B", "address": "2 Main St"}]


def test_zero_coordinates_are_kept(write_csv):
    path = write_csv("name,latitude,longitude\nX,0,0\n")
    assert read_places(path) == [{"poi_name": "X", "latitude": 0.0, "longitude": 0.0}]


def test_limits_are_inclusive(write_csv):
    name, address, place_id = "n" * 200, "a" * 500, "i" * 100
    path = write_csv(f"name,address,id,latitude,longitude\n{name},{address},{place_id},90,180\nX,,,-90,-180\n")
    rows = read_places(path)
    assert rows[0] == {
        "poi_name": name, "address": address, "id": place_id, "latitude": 90.0, "longitude": 180.0,
    }
    assert rows[1] == {"poi_name": "X", "latitude": -90.0, "longitude": -180.0}


def test_quoted_commas_and_newlines(write_csv):
    path = write_csv('name,address\n"Smith, Jones & Co","1 Main St\nSuite 2"\n')
    assert read_places(path) == [{"poi_name": "Smith, Jones & Co", "address": "1 Main St\nSuite 2"}]


def test_csv_input_error_is_a_value_error():
    assert issubclass(CSVInputError, ValueError)


def test_missing_name_column(write_csv):
    message = read_error(write_csv("address,country\n1 Main St,US\n"))
    assert message.startswith("line 1:")
    assert "name" in message


def test_empty_file_and_header_only(write_csv):
    assert read_error(write_csv("")).startswith("line 1:")
    assert read_error(write_csv("name,address\n")).startswith("line 1:")
    assert read_error(write_csv("name,address\n\n,\n")).startswith("line 1:")
    assert read_error(write_csv(data=b"\xef\xbb\xbf")).startswith("line 1:")


def test_empty_name_reports_line(write_csv):
    message = read_error(write_csv("name,address\nA,1 Main St\nB,2 Main St\n,3 Main St\nD,4 Main St\n"))
    assert message.startswith("line 4:")
    assert "name" in message


def test_line_numbers_count_skipped_blank_lines(write_csv):
    message = read_error(write_csv("name,address\nA,1\n\n,,\n,5 Main St\n"))
    assert message.startswith("line 5:")


@pytest.mark.parametrize("column,value", [("latitude", "37.78"), ("longitude", "-122.41")])
def test_one_coordinate_column_alone(write_csv, column, value):
    message = read_error(write_csv(f"name,{column}\nA,\nB,{value}\n"))
    assert message.startswith("line 3:")
    assert "latitude" in message and "longitude" in message


def test_lat_without_lng(write_csv):
    message = read_error(write_csv("name,latitude,longitude\nA,37.78,\n"))
    assert message.startswith("line 2:")
    assert "latitude" in message and "longitude" in message


@pytest.mark.parametrize("lat,lng,word", [
    ("north", "1", "latitude"),
    ("1", "east", "longitude"),
    ("nan", "1", "latitude"),
    ("1", "inf", "longitude"),
])
def test_non_numeric_coordinate(write_csv, lat, lng, word):
    message = read_error(write_csv(f"name,latitude,longitude\nA,{lat},{lng}\n"))
    assert message.startswith("line 2:")
    assert word in message


@pytest.mark.parametrize("header,good,bad,word", [
    ("name", "ok", "n" * 201, "name"),
    ("name,id", "ok,1", "X," + "i" * 101, "id"),
    ("name,address", "ok,1", "X," + "a" * 501, "address"),
    ("name,latitude,longitude", "ok,1,1", "X,123,1", "latitude"),
    ("name,latitude,longitude", "ok,1,1", "X,-90.5,1", "latitude"),
    ("name,latitude,longitude", "ok,1,1", "X,1,-181", "longitude"),
    ("name,latitude,longitude", "ok,1,1", "X,1,180.01", "longitude"),
])
def test_field_limits_reported_with_line_number(write_csv, header, good, bad, word):
    message = read_error(write_csv(f"{header}\n{good}\n{bad}\n"))
    assert message.startswith("line 3:")
    assert word in message


def test_row_limit(write_csv):
    body = "name\n" + "".join(f"P{i}\n" for i in range(10_000))
    assert len(read_places(write_csv(body))) == 10_000

    message = read_error(write_csv(body + "one more\n"))
    assert message.startswith("line 10002:")
    assert "10,000" in message


def test_blank_rows_do_not_count_toward_the_row_limit(write_csv):
    body = "name\n" + "".join(f"P{i}\n\n" for i in range(10_000))
    assert len(read_places(write_csv(body))) == 10_000


def test_unicode_preserved(write_csv):
    path = write_csv("name,address\nCafé Zürich,Bahnhofstraße 1\n東京タワー,\n")
    assert read_places(path) == [
        {"poi_name": "Café Zürich", "address": "Bahnhofstraße 1"},
        {"poi_name": "東京タワー"},
    ]


def test_not_utf8_reports_the_bad_line(write_csv):
    data = "name\nA\nB\n".encode() + "Café\n".encode("cp1252") + b"D\n"
    message = read_error(write_csv(data=data))
    assert message.startswith("line 4:")
    assert "UTF-8" in message


def test_csv_syntax_error_reports_line(write_csv):
    # The csv module refuses a single field over 131,072 characters.
    message = read_error(write_csv("name\nA\n" + "x" * 200_000 + "\n"))
    assert message.startswith("line 3:")
