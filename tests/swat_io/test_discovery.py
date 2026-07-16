from pathlib import Path

from swat_io.discovery import discover_base_models


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
