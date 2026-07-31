from pathlib import Path

from swat_io.cio_parser import parse_file_cio
from swat_io.hru.scanner import parse_hru_directory
from swat_io.hru.summary import build_hru_summary
from swat_io.stats import compute_hru_stats, compute_wetland_stats, hru_stats_from_summary, wetland_stats_from_summary
from swat_io.summary import summarize_project
from tests.helpers import write_synthetic_pnd, write_synthetic_sub


def _write_subbasin(
    txtinout_dir: Path, subbasin_id: int, *, area_km2: float, wet_fr: float, wet_nsa_ha: float
) -> None:
    write_synthetic_sub(txtinout_dir / f"{subbasin_id:05d}0000.sub", area_km2=area_km2)
    write_synthetic_pnd(
        txtinout_dir / f"{subbasin_id:05d}0000.pnd",
        {"WET_FR": wet_fr, "WET_NSA": wet_nsa_ha},
    )


def _write_hru(txtinout_dir: Path, filename: str, *, subbasin: int, hru: int, land_use: str, hru_fr: float) -> None:
    content = (
        f"Subbasin:{subbasin}   Hru:{hru}   Luse:{land_use}   Soil: 1013090         Slope: 0-9999\n"
        f"{hru_fr:16.4f}    | HRU_FR : Fraction of subbasin area contained in HRU\n"
    )
    (txtinout_dir / filename).write_text(content, encoding="utf-8")


def test_compute_wetland_stats_aggregates_area_and_coverage(tmp_path: Path) -> None:
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_subbasin(txtinout_dir, 1, area_km2=10.0, wet_fr=0.2, wet_nsa_ha=50.0)
    _write_subbasin(txtinout_dir, 2, area_km2=5.0, wet_fr=0.0, wet_nsa_ha=0.0)

    stats = compute_wetland_stats(txtinout_dir)

    assert stats.subbasin_count == 2
    assert stats.total_area_km2 == 15.0
    assert stats.wetland_area_ha == 50.0
    # 15 km2 = 1500 ha; conversión explícita ha<->km2.
    assert round(stats.wetland_coverage_pct, 4) == round(50.0 / 1500.0 * 100, 4)
    assert stats.subbasins_with_wetland == 1  # solo la subcuenca con WET_FR > 0


def test_compute_wetland_stats_zero_fraction_not_counted(tmp_path: Path) -> None:
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_subbasin(txtinout_dir, 1, area_km2=10.0, wet_fr=0.0, wet_nsa_ha=25.0)

    stats = compute_wetland_stats(txtinout_dir)

    assert stats.subbasins_with_wetland == 0


def test_compute_hru_stats_counts_hru_and_land_use(tmp_path: Path) -> None:
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_hru(txtinout_dir, "000010001.hru", subbasin=1, hru=1, land_use="AGRL", hru_fr=0.6)
    _write_hru(txtinout_dir, "000010002.hru", subbasin=1, hru=2, land_use="FRST", hru_fr=0.4)
    _write_hru(txtinout_dir, "000020001.hru", subbasin=2, hru=1, land_use="AGRL", hru_fr=1.0)

    stats = compute_hru_stats(txtinout_dir)

    assert stats.hru_count == 3
    assert stats.land_use_count == 2
    assert stats.simulation_period is None  # no hay file.cio en este TxtInOut sintético


def test_compute_hru_stats_reads_simulation_period_from_file_cio(tmp_path: Path) -> None:
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_hru(txtinout_dir, "000010001.hru", subbasin=1, hru=1, land_use="AGRL", hru_fr=1.0)
    (txtinout_dir / "file.cio").write_text(
        "Master Watershed File: file.cio\n"
        "               8    | NBYR : Number of years simulated\n"
        "            2012    | IYR : Beginning year of simulation\n",
        encoding="utf-8",
    )

    stats = compute_hru_stats(txtinout_dir)

    assert stats.simulation_period is not None
    assert stats.simulation_period.start_year == 2012
    assert stats.simulation_period.end_year == 2019
    assert stats.simulation_period.n_years == 8


def test_wetland_stats_from_summary_matches_compute_wetland_stats(tmp_path: Path) -> None:
    """wetland_stats_from_summary(df) debe dar el mismo resultado que
    compute_wetland_stats(txtinout_dir), sin que el caller tenga que dejar
    que compute_wetland_stats vuelva a parsear TxtInOut."""
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_subbasin(txtinout_dir, 1, area_km2=10.0, wet_fr=0.2, wet_nsa_ha=50.0)

    df = summarize_project(txtinout_dir)

    assert wetland_stats_from_summary(df) == compute_wetland_stats(txtinout_dir)


def test_hru_stats_from_summary_matches_compute_hru_stats(tmp_path: Path) -> None:
    """Misma idea para HRU: hru_stats_from_summary(df, period) debe dar el
    mismo resultado que compute_hru_stats(txtinout_dir) sin volver a
    escanear los .hru."""
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_hru(txtinout_dir, "000010001.hru", subbasin=1, hru=1, land_use="AGRL", hru_fr=1.0)
    (txtinout_dir / "file.cio").write_text(
        "               8    | NBYR : Number of years simulated\n"
        "            2012    | IYR : Beginning year of simulation\n",
        encoding="utf-8",
    )

    scan_result = parse_hru_directory(txtinout_dir)
    df = build_hru_summary(scan_result.files)
    period = parse_file_cio(txtinout_dir / "file.cio")

    assert hru_stats_from_summary(df, period) == compute_hru_stats(txtinout_dir)
