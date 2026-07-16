import customtkinter as ctk

from ui.form_builder import build_wetland_form

_LAYOUT = {
    "fields": [
        {"id": "wet_fr", "label_key": "wetland.wet_fr", "range": [0.0, 1.0]},
        {"id": "wet_nsa", "label_key": "wetland.wet_nsa", "range": [0.0, None]},
    ]
}


class _FakeConfig:
    def text(self, key: str) -> str:
        return {"wetland.wet_fr": "WET_FR", "wetland.wet_nsa": "WET_NSA"}[key]


def test_build_wetland_form_creates_one_entry_per_field(hidden_root) -> None:
    parent = ctk.CTkFrame(hidden_root)
    entries = build_wetland_form(parent, _FakeConfig(), _LAYOUT, {"wet_fr": 0.2, "wet_nsa": 10.0}, lambda *_: None, lambda *_: None)

    assert set(entries.keys()) == {"wet_fr", "wet_nsa"}
    assert entries["wet_fr"].get() == "0.2"
    assert entries["wet_nsa"].get() == "10.0"


def test_build_wetland_form_commits_valid_edit(hidden_root) -> None:
    parent = ctk.CTkFrame(hidden_root)
    committed = []
    entries = build_wetland_form(
        parent, _FakeConfig(), _LAYOUT, {"wet_fr": 0.2, "wet_nsa": 10.0},
        on_commit=lambda field_id, value: committed.append((field_id, value)),
        on_error=lambda *_: None,
    )

    hidden_root.deiconify()
    parent.pack()
    entries["wet_fr"].delete(0, "end")
    entries["wet_fr"].insert(0, "0.9")
    entries["wet_fr"].focus_set()
    hidden_root.update()
    entries["wet_fr"].event_generate("<Return>")
    hidden_root.update()

    assert committed == [("wet_fr", 0.9)]


def test_build_wetland_form_reports_unparseable_input(hidden_root) -> None:
    parent = ctk.CTkFrame(hidden_root)
    errors = []
    entries = build_wetland_form(
        parent, _FakeConfig(), _LAYOUT, {"wet_fr": 0.2, "wet_nsa": 10.0},
        on_commit=lambda *_: None,
        on_error=lambda field_id, message: errors.append((field_id, message)),
    )

    hidden_root.deiconify()
    parent.pack()
    entries["wet_fr"].delete(0, "end")
    entries["wet_fr"].insert(0, "not-a-number")
    entries["wet_fr"].focus_set()
    hidden_root.update()
    entries["wet_fr"].event_generate("<Return>")
    hidden_root.update()

    assert errors and errors[0][0] == "wet_fr"
