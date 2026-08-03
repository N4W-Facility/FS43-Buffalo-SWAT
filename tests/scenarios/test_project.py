from pathlib import Path

from scenarios.project import (
    ProjectMetadata,
    SummaryEntry,
    is_valid_project_dir,
    load_project,
    save_project,
    validate_shapefile_path,
)


def test_is_valid_project_dir_requires_txtinout(tmp_path: Path) -> None:
    assert not is_valid_project_dir(tmp_path)
    (tmp_path / "TxtInOut").mkdir()
    assert is_valid_project_dir(tmp_path)


def test_load_project_missing_file_returns_empty_metadata(tmp_path: Path) -> None:
    metadata = load_project(tmp_path)
    assert metadata == ProjectMetadata()


def test_load_project_corrupt_json_returns_empty_metadata(tmp_path: Path) -> None:
    (tmp_path / "project.json").write_text("{not valid json", encoding="utf-8")

    metadata = load_project(tmp_path)

    assert metadata == ProjectMetadata()


def test_save_and_load_project_round_trip(tmp_path: Path) -> None:
    metadata = ProjectMetadata(name="Buffalo", description="Calibrated baseline")
    save_project(tmp_path, metadata)

    reloaded = load_project(tmp_path)

    assert reloaded.name == "Buffalo"
    assert reloaded.description == "Calibrated baseline"
    assert reloaded.wetlands is None
    assert reloaded.hru is None


def test_save_project_preserves_summary_when_editing_metadata_only(tmp_path: Path) -> None:
    metadata = ProjectMetadata(
        name="Buffalo",
        description="v1",
        wetlands=SummaryEntry(generated_at="2026-07-30T12:00:00+00:00", stats={"subbasin_count": 3}),
    )
    save_project(tmp_path, metadata)

    reloaded = load_project(tmp_path)
    reloaded.description = "v2"
    save_project(tmp_path, reloaded)

    final = load_project(tmp_path)
    assert final.description == "v2"
    assert final.wetlands is not None
    assert final.wetlands.generated_at == "2026-07-30T12:00:00+00:00"
    assert final.wetlands.stats == {"subbasin_count": 3}


def test_save_and_load_project_round_trips_shapefile_paths(tmp_path: Path) -> None:
    metadata = ProjectMetadata(
        name="Buffalo", reach_shp_path=r"C:\gis\riv1.shp", subbasin_shp_path=r"C:\gis\subs1.shp"
    )
    save_project(tmp_path, metadata)

    reloaded = load_project(tmp_path)

    assert reloaded.reach_shp_path == r"C:\gis\riv1.shp"
    assert reloaded.subbasin_shp_path == r"C:\gis\subs1.shp"


def test_load_project_defaults_shapefile_paths_to_none(tmp_path: Path) -> None:
    metadata = load_project(tmp_path)

    assert metadata.reach_shp_path is None
    assert metadata.subbasin_shp_path is None


def test_validate_shapefile_path_valid(tmp_path: Path) -> None:
    shp = tmp_path / "subs1.shp"
    shp.write_text("fake shapefile")

    assert validate_shapefile_path(shp) is None


def test_validate_shapefile_path_missing_file(tmp_path: Path) -> None:
    assert validate_shapefile_path(tmp_path / "missing.shp") == "project.error.invalid_shp"


def test_validate_shapefile_path_wrong_extension(tmp_path: Path) -> None:
    not_shp = tmp_path / "subs1.txt"
    not_shp.write_text("not a shapefile")

    assert validate_shapefile_path(not_shp) == "project.error.invalid_shp"
