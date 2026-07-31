from pathlib import Path

from swat_io.discovery import discover_base_models, discover_scenario_folders


def test_discover_base_models_finds_calibrated_txtinout(tmp_path: Path) -> None:
    buffalo_calibrated = tmp_path / "Buffalo" / "Buffalo_calibrated_annual" / "TxtInOut"
    buffalo_calibrated.mkdir(parents=True)
    (tmp_path / "Buffalo" / "Buffalo_LS_annual" / "TxtInOut").mkdir(parents=True)

    models = discover_base_models(tmp_path)

    assert len(models) == 1
    assert models[0].watershed == "Buffalo"
    assert models[0].model_dir == tmp_path / "Buffalo" / "Buffalo_calibrated_annual"
    assert models[0].txtinout_dir == buffalo_calibrated


def test_discover_base_models_skips_watershed_without_calibrated_model(tmp_path: Path) -> None:
    (tmp_path / "Crooked" / "Crooked_daily" / "TxtInOut").mkdir(parents=True)

    models = discover_base_models(tmp_path)

    assert models == []


def test_discover_base_models_returns_empty_for_missing_root(tmp_path: Path) -> None:
    assert discover_base_models(tmp_path / "does_not_exist") == []


def test_discover_scenario_folders_finds_subfolders_with_txtinout(tmp_path: Path) -> None:
    calibrated = tmp_path / "Buffalo_calibrated_annual" / "TxtInOut"
    calibrated.mkdir(parents=True)
    (calibrated / "000010000.sub").write_text("x")
    gi = tmp_path / "Buffalo_GI_annual" / "TxtInOut"
    gi.mkdir(parents=True)
    (gi / "000010000.sub").write_text("x")
    (tmp_path / "not_a_scenario.txt").write_text("x")

    folders = discover_scenario_folders(tmp_path)

    names = sorted(f.name for f in folders)
    assert names == ["Buffalo_GI_annual", "Buffalo_calibrated_annual"]


def test_discover_scenario_folders_skips_subfolders_without_valid_sub_files(tmp_path: Path) -> None:
    empty_txtinout = tmp_path / "Empty_annual" / "TxtInOut"
    empty_txtinout.mkdir(parents=True)

    folders = discover_scenario_folders(tmp_path)

    assert folders == []


def test_discover_scenario_folders_returns_empty_for_missing_project_dir(tmp_path: Path) -> None:
    assert discover_scenario_folders(tmp_path / "does_not_exist") == []
