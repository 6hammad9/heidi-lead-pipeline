import gspread
import pytest

from pipeline.export.google_sheets import sheets_configured, write_google_sheet


class FakeWorksheet:
    def __init__(self, title: str) -> None:
        self.title = title
        self.values: list[list[object]] = [["stale"]]
        self.calls: list[str] = []

    def clear(self) -> None:
        self.values = []
        self.calls.append("clear")

    def update(self, range_name: str, values: list, value_input_option: str) -> None:
        assert (range_name, value_input_option) == ("A1", "RAW")
        self.values = values

    def resize(self, rows: int, cols: int) -> None:
        self.calls.append(f"resize {rows}x{cols}")

    def freeze(self, rows: int) -> None:
        self.calls.append(f"freeze {rows}")

    def format(self, cells: str, fmt: dict) -> None:
        self.calls.append(f"format {cells}")


class FakeSpreadsheet:
    url = "https://docs.google.com/spreadsheets/d/abc"

    def __init__(self) -> None:
        self.sheets = {"Leads": FakeWorksheet("Leads")}

    def worksheet(self, title: str) -> FakeWorksheet:
        if title not in self.sheets:
            raise gspread.WorksheetNotFound(title)
        return self.sheets[title]

    def add_worksheet(self, title: str, rows: int, cols: int) -> FakeWorksheet:
        self.sheets[title] = FakeWorksheet(title)
        return self.sheets[title]


class FakeClient:
    def __init__(self) -> None:
        self.spreadsheet = FakeSpreadsheet()

    def open_by_key(self, key: str) -> FakeSpreadsheet:
        assert key == "sheet-123"
        return self.spreadsheet


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEET_ID", "sheet-123")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "key.json")


def test_tabs_are_replaced_and_new_tabs_created() -> None:
    client = FakeClient()
    url = write_google_sheet(
        {"Leads": [["Company", "Score"], ["A", 94.0], ["B", None]], "Run log": [["Item"], ["x"]]},
        client,
    )
    sheets = client.spreadsheet.sheets
    assert url == FakeSpreadsheet.url
    assert sheets["Leads"].values == [["Company", "Score"], ["A", 94.0], ["B", ""]]
    assert sheets["Leads"].calls[:2] == ["resize 3x2", "clear"]
    assert "freeze 1" in sheets["Run log"].calls


def test_configuration_needs_both_values(monkeypatch: pytest.MonkeyPatch) -> None:
    assert sheets_configured()
    monkeypatch.delenv("GOOGLE_SHEET_ID")
    assert not sheets_configured()
