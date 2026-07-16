import pytest

from scenarios.models import WETLAND_ABBREVIATIONS, build_scenario_name


def test_build_scenario_name_composes_convention() -> None:
    assert build_scenario_name("Buffalo", "WET_MS", "annual") == "Buffalo_WET_MS_annual"


def test_build_scenario_name_strips_timestep_whitespace() -> None:
    assert build_scenario_name("Buffalo", "WET_LS", "  annual  ") == "Buffalo_WET_LS_annual"


@pytest.mark.parametrize("abbreviation", ["LS", "wet_ms", "WET_XX", ""])
def test_build_scenario_name_rejects_invalid_abbreviation(abbreviation: str) -> None:
    with pytest.raises(ValueError):
        build_scenario_name("Buffalo", abbreviation, "annual")


@pytest.mark.parametrize("timestep", ["", "   "])
def test_build_scenario_name_rejects_blank_timestep(timestep: str) -> None:
    with pytest.raises(ValueError):
        build_scenario_name("Buffalo", "WET_MS", timestep)


def test_wetland_abbreviations_content() -> None:
    assert WETLAND_ABBREVIATIONS == ("WET_LS", "WET_MS", "WET_HS")
