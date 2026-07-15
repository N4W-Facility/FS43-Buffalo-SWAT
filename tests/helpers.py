from __future__ import annotations

from pathlib import Path

_WETLAND_CODES = [
    "WET_FR", "WET_NSA", "WET_NVOL", "WET_MXSA", "WET_MXVOL", "WET_VOL",
    "WET_SED", "WET_NSED", "WET_K", "PSETLW1", "PSETLW2", "NSETLW1",
    "NSETLW2", "CHLAW", "SECCIW", "WET_NO3", "WET_SOLP", "WET_ORGN",
    "WET_ORGP", "WETEVCOEFF",
]


def write_synthetic_pnd(path: Path, wetland_values: dict[str, float]) -> None:
    lines = ["Wetland inputs:\n"]
    for code in _WETLAND_CODES:
        value = wetland_values.get(code, 0.0)
        lines.append(f"{value:16.3f}    | {code} : synthetic test value\n")
    path.write_text("".join(lines), encoding="utf-8")


def write_synthetic_sub(path: Path, area_km2: float = 10.0) -> None:
    path.write_text(f"{area_km2:16.3f}    | SUB_KM : synthetic test value\n", encoding="utf-8")


def make_synthetic_txtinout(root: Path, subbasins: dict[int, dict[str, float]]) -> Path:
    txtinout_dir = root / "TxtInOut"
    txtinout_dir.mkdir(parents=True, exist_ok=True)
    for subbasin_id, wetland_values in subbasins.items():
        write_synthetic_sub(txtinout_dir / f"{subbasin_id:05d}0000.sub")
        write_synthetic_pnd(txtinout_dir / f"{subbasin_id:05d}0000.pnd", wetland_values)
    return txtinout_dir
