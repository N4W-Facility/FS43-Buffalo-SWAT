from pathlib import Path
from unittest.mock import patch

from scenarios.activity_log import log_action


def test_log_action_appends_line_with_category_and_message(tmp_path: Path) -> None:
    log_action(tmp_path, "WETLANDS", "Saved subbasin 1: WET_FR=0.5")
    log_action(tmp_path, "RUN", "Started SWAT run.")

    log_path = tmp_path / "tool_outputs" / "activity_log.txt"
    lines = log_path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
    assert "[WETLANDS] Saved subbasin 1: WET_FR=0.5" in lines[0]
    assert "[RUN] Started SWAT run." in lines[1]


def test_log_action_creates_tool_outputs_dir_if_missing(tmp_path: Path) -> None:
    assert not (tmp_path / "tool_outputs").exists()

    log_action(tmp_path, "PROJECT", "Opened project.")

    assert (tmp_path / "tool_outputs" / "activity_log.txt").is_file()


def test_log_action_never_raises_on_write_failure(tmp_path: Path) -> None:
    with patch("scenarios.activity_log.tool_outputs_dir", side_effect=OSError("disk full")):
        log_action(tmp_path, "RUN", "Should not raise.")
