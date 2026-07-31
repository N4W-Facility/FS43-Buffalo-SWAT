import math

import pandas as pd
import pytest

from swat_io.hru.parser import parse_hru_file
from swat_io.hru.summary import (
    add_land_use_area,
    build_hru_summary,
    export_hru_summary_csv,
    export_land_use_summary_csv,
    find_subbasins_with_invalid_fraction_sum,
    land_use_percentages,
    read_land_use_summary_csv,
    subbasin_area_km2,
    summarize_land_use_by_subbasin,
)

from tests.swat_io.hru.conftest import fixture_path


def _load(*names: str):
    return [parse_hru_file(fixture_path(name)) for name in names]


def test_build_hru_summary_has_one_row_per_hru() -> None:
    hru_files = _load("000010001.hru", "000030003_duplicate.hru", "000040004_missing_hrufr.hru")

    df = build_hru_summary(hru_files)

    assert len(df) == 3


def test_build_hru_summary_includes_requested_parameters() -> None:
    hru_files = _load("000010001.hru")

    df = build_hru_summary(hru_files, parameters=["SLSUBBSN"])

    assert "SLSUBBSN" in df.columns
    assert df.loc[0, "SLSUBBSN"] == pytest.approx(44.427)


def test_build_hru_summary_uses_nan_for_missing_parameter() -> None:
    hru_files = _load("000010001.hru")

    df = build_hru_summary(hru_files, parameters=["DOES_NOT_EXIST"])

    assert math.isnan(df.loc[0, "DOES_NOT_EXIST"])


def test_build_hru_summary_keeps_stable_column_order() -> None:
    hru_files = _load("000010001.hru")

    df = build_hru_summary(hru_files, parameters=["CANMX", "ESCO"])

    expected_prefix = [
        "file_path",
        "file_name",
        "subbasin",
        "hru",
        "gis_id",
        "land_use",
        "soil",
        "slope_class",
        "HRU_FR",
        "parse_status",
        "validation_status",
    ]
    assert list(df.columns) == expected_prefix + ["CANMX", "ESCO"]


def test_summarize_land_use_by_subbasin_groups_and_computes_fractions() -> None:
    hru_files = _load("000010001.hru", "000030003_duplicate.hru")
    summary_df = build_hru_summary(hru_files)

    land_use_df = summarize_land_use_by_subbasin(summary_df)

    row = land_use_df[(land_use_df["subbasin"] == 1) & (land_use_df["land_use"] == "AGRL")].iloc[0]
    assert row["hru_count"] == 1
    assert row["fraction_sum"] == pytest.approx(0.75)
    assert row["percentage_of_subbasin"] == pytest.approx(75.0)


def test_find_subbasins_with_invalid_fraction_sum_flags_deviation() -> None:
    hru_files = _load("000010001.hru")  # HRU_FR = 0.75, único HRU de la subcuenca 1
    summary_df = build_hru_summary(hru_files)
    land_use_df = summarize_land_use_by_subbasin(summary_df)

    invalid = find_subbasins_with_invalid_fraction_sum(land_use_df)

    assert 1 in invalid["subbasin"].values


def test_add_land_use_area_computes_km2_and_ha() -> None:
    hru_files = _load("000010001.hru")
    summary_df = build_hru_summary(hru_files)
    land_use_df = summarize_land_use_by_subbasin(summary_df)
    subbasin_areas = pd.DataFrame({"subbasin": [1], "sub_km2": [10.0]})

    result = add_land_use_area(land_use_df, subbasin_areas)

    row = result.iloc[0]
    assert row["land_use_area_km2"] == pytest.approx(row["fraction_sum"] * 10.0)
    assert row["land_use_area_ha"] == pytest.approx(row["land_use_area_km2"] * 100)


def test_export_hru_summary_csv_has_no_index_and_stable_columns(tmp_path) -> None:
    hru_files = _load("000010001.hru")
    df = build_hru_summary(hru_files)
    destination = tmp_path / "out" / "hru_summary.csv"

    result_path = export_hru_summary_csv(df, destination)

    assert result_path == destination
    reloaded = pd.read_csv(destination)
    assert list(reloaded.columns) == list(df.columns)
    assert "Unnamed: 0" not in reloaded.columns


def test_export_land_use_summary_csv_round_trips(tmp_path) -> None:
    hru_files = _load("000010001.hru", "000030003_duplicate.hru")
    summary_df = build_hru_summary(hru_files)
    land_use_df = summarize_land_use_by_subbasin(summary_df)
    destination = tmp_path / "land_use_by_subbasin.csv"

    export_land_use_summary_csv(land_use_df, destination)

    reloaded = pd.read_csv(destination)
    assert list(reloaded.columns) == list(land_use_df.columns)
    assert len(reloaded) == len(land_use_df)


def _land_use_df_with_areas() -> pd.DataFrame:
    hru_files = _load("000010001.hru", "000030003_duplicate.hru")  # subbasin 1 AGRL, subbasin 3 PAST
    summary_df = build_hru_summary(hru_files)
    land_use_df = summarize_land_use_by_subbasin(summary_df)
    subbasin_areas = pd.DataFrame({"subbasin": [1, 3], "sub_km2": [10.0, 5.0]})
    return add_land_use_area(land_use_df, subbasin_areas)


def test_land_use_percentages_for_one_subbasin_matches_its_own_row() -> None:
    land_use_df = _land_use_df_with_areas()

    percentages = land_use_percentages(land_use_df, subbasin=1)

    expected = land_use_df.loc[land_use_df["subbasin"] == 1, "percentage_of_subbasin"].iloc[0]
    assert percentages["AGRL"] == pytest.approx(expected)


def test_land_use_percentages_total_watershed_weights_by_area() -> None:
    land_use_df = _land_use_df_with_areas()

    percentages = land_use_percentages(land_use_df, subbasin=None)

    total_area = land_use_df.drop_duplicates("subbasin")["sub_km2"].sum()
    agrl_area = land_use_df.loc[land_use_df["land_use"] == "AGRL", "land_use_area_km2"].sum()
    assert percentages["AGRL"] == pytest.approx(agrl_area / total_area * 100)


def test_land_use_percentages_reindexes_missing_categories_to_zero() -> None:
    land_use_df = _land_use_df_with_areas()

    percentages = land_use_percentages(land_use_df, subbasin=1, categories=["AGRL", "PAST"])

    assert list(percentages.index) == ["AGRL", "PAST"]
    assert percentages["PAST"] == 0.0


def test_subbasin_area_km2_for_one_subbasin() -> None:
    land_use_df = _land_use_df_with_areas()

    assert subbasin_area_km2(land_use_df, subbasin=3) == pytest.approx(5.0)


def test_subbasin_area_km2_total_watershed_sums_each_subbasin_once() -> None:
    land_use_df = _land_use_df_with_areas()

    assert subbasin_area_km2(land_use_df, subbasin=None) == pytest.approx(15.0)


def test_read_land_use_summary_csv_round_trips(tmp_path) -> None:
    land_use_df = _land_use_df_with_areas()
    destination = tmp_path / "land_use_by_subbasin.csv"
    export_land_use_summary_csv(land_use_df, destination)

    reloaded = read_land_use_summary_csv(destination)

    assert list(reloaded.columns) == list(land_use_df.columns)
    assert len(reloaded) == len(land_use_df)
