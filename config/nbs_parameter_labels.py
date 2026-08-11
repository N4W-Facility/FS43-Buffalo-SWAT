"""Nombres legibles (inglés, idioma del resto de la UI) para los códigos
crudos SWAT que expone el wizard de NbS -- pedido explícito del usuario:
"que aparezca el significado de lo que son y no el acrónimo".

A diferencia de wetland_params.yaml (20 campos fijos con rango de
validación por campo), acá no hay rangos curados -- mismo criterio ya
usado para .hru en general (ver CLAUDE.md) -- así que esto es solo texto
descriptivo, sin necesidad de la infraestructura YAML de Wetlands. Las
descripciones se tomaron de SWAT2012 Input/Output File Documentation,
Version 2012 (capítulos 14 y 20) y de la guía del proyecto
(SWAT2012_rev670_guia_general_cambio_creacion_coberturas.md).

``label_for`` es la única función que el resto de la app debería llamar;
un código sin entrada acá se muestra tal cual (nunca una excepción por un
campo no catalogado).
"""
from __future__ import annotations

PARAMETER_LABELS: dict[str, str] = {
    # --- .hru: superficie / dosel / residuos ---
    "CANMX": "Maximum canopy storage (mm H2O)",
    "OV_N": "Manning's n for overland flow",
    "RSDIN": "Initial residue cover (kg/ha)",
    # --- .mgt: condición inicial ---
    "IGRO": "Land cover growing at simulation start (0 = none, 1 = yes)",
    "LAI_INIT": "Initial leaf area index",
    "BIO_INIT": "Initial biomass (kg/ha)",
    "PHU_PLT": "Heat units required to reach maturity",
    "CN2": "Initial SCS runoff curve number (moisture condition II)",
    # --- plant.dat: identidad ---
    "CPNM": "4-character plant code",
    "IDC": "Plant functional class",
    # --- plant.dat: línea 2 (biomasa, dosel, raíces) ---
    "BIO_E": "Biomass-energy ratio (radiation-use efficiency)",
    "HVSTI": "Harvest index under optimal conditions",
    "BLAI": "Maximum potential leaf area index",
    "FRGRW1": "Growing-season fraction at 1st LAI development point",
    "LAIMX1": "Fraction of max LAI at FRGRW1",
    "FRGRW2": "Growing-season fraction at 2nd LAI development point",
    "LAIMX2": "Fraction of max LAI at FRGRW2",
    "DLAI": "Growing-season fraction when LAI starts declining",
    "CHTMX": "Maximum canopy height (m)",
    "RDMX": "Maximum root depth (m)",
    # --- plant.dat: línea 3 (temperatura y nutrientes) ---
    "T_OPT": "Optimal temperature for plant growth",
    "T_BASE": "Minimum (base) temperature for plant growth",
    "CNYLD": "Normal fraction of nitrogen in yield",
    "CPYLD": "Normal fraction of phosphorus in yield",
    "PLTNFR1": "Normal N fraction in biomass at emergence",
    "PLTNFR2": "Normal N fraction in biomass at ~50% maturity",
    "PLTNFR3": "Normal N fraction in biomass at maturity",
    "PLTPFR1": "Normal P fraction in biomass at emergence",
    "PLTPFR2": "Normal P fraction in biomass at ~50% maturity",
    "PLTPFR3": "Normal P fraction in biomass at maturity",
    # --- plant.dat: línea 4 (estrés, erosión, CO2, residuos, dormancia) ---
    "WSYF": "Lower limit of harvest index under stress",
    "USLE_C": "Minimum USLE cover/management (C) factor",
    "GSI": "Maximum stomatal conductance",
    "VPDFR": "Vapor pressure deficit for the stomatal response curve",
    "FRGMAX": "Fraction of max stomatal conductance at VPDFR",
    "WAVP": "Radiation-use efficiency response to vapor pressure deficit",
    "CO2HI": "Elevated CO2 concentration for the response curve",
    "BIOEHI": "Biomass-energy ratio at CO2HI",
    "RSDCO_PL": "Plant residue decomposition coefficient",
    "ALAI_MIN": "Minimum LAI during dormancy (perennials/trees)",
    # --- plant.dat: línea 5 (árboles/dosel/raíces) ---
    "BIO_LEAF": "Fraction of tree biomass converted to residue each dormancy",
    "MAT_YRS": "Years for a tree species to reach full development",
    "BMX_TREES": "Maximum biomass of a mature forest (metric tons/ha)",
    "EXT_COEF": "Light extinction coefficient of the canopy",
    "BMDIEOFF": "Fraction of standing biomass that dies off during dormancy",
    # --- .mgt operaciones: campos comunes ---
    "MONTH": "Month",
    "DAY": "Day",
    "HUSC": "Fraction of base-zero heat units when the operation occurs",
    "PLANT_ID": "Plant/land cover ID (from the plant database)",
    "CURYR_MAT": "Current age of the tree (years)",
    "HEAT_UNITS": "Total heat units for the cover to reach maturity",
    "HI_TARG": "Harvest index target",
    "BIO_TARG": "Biomass target (metric tons/ha)",
    "CNOP": "Curve number (moisture condition II) set by this operation",
    "IRR_SC": "Irrigation source code",
    "IRR_NO": "Irrigation source location",
    "IRR_AMT": "Depth of irrigation water applied (mm)",
    "IRR_SALT": "Salt concentration in irrigation water (mg/kg)",
    "IRR_EFM": "Irrigation efficiency (0-1)",
    "IRR_SQ": "Irrigation surface runoff ratio (0-1)",
    "FERT_ID": "Fertilizer/manure ID (from the fertilizer database)",
    "FRT_KG": "Amount of fertilizer applied (kg/ha)",
    "FRT_SURFACE": "Fraction of fertilizer applied to the top 10mm of soil",
    "PEST_ID": "Pesticide ID (from the pesticide database)",
    "PST_KG": "Amount of pesticide applied (kg/ha)",
    "PST_DEP": "Depth of pesticide incorporation in soil (mm)",
    "HI_OVR": "Harvest index override",
    "FRAC_HARVK": "Stover fraction removed (0-1)",
    "TILL_ID": "Tillage implement ID (from the tillage database)",
    "IHV_GBM": "Harvest type (0 = biomass, 1 = grain)",
    "HARVEFF": "Harvest efficiency",
    "GRZ_DAYS": "Number of consecutive days of grazing",
    "MANURE_ID": "Manure ID (from the fertilizer database)",
    "BIO_EAT": "Biomass consumed daily by grazing ((kg/ha)/day)",
    "BIO_TRMP": "Biomass trampled daily ((kg/ha)/day)",
    "MANURE_KG": "Manure deposited daily ((kg/ha)/day)",
    "WSTRS_ID": "Water stress trigger (1 = plant demand, 2 = soil water content)",
    "IRR_SCA": "Auto irrigation source code",
    "IRR_NOA": "Auto irrigation source location",
    "AUTO_WSTRS": "Water stress threshold that triggers auto irrigation",
    "IRR_EFF": "Auto irrigation efficiency (0-100)",
    "IRR_MX": "Amount applied per auto irrigation event (mm)",
    "IRR_ASQ": "Auto irrigation surface runoff ratio (0-1)",
    "AFERT_ID": "Auto fertilization fertilizer ID",
    "AUTO_NSTRS": "Nitrogen stress factor that triggers auto fertilization",
    "AUTO_NAPP": "Max mineral N allowed in a single application (kg N/ha)",
    "AUTO_NYR": "Max mineral N allowed per year (kg N/ha)",
    "AUTO_EFF": "Auto fertilization application efficiency",
    "AFRT_SURFACE": "Fraction of auto-fertilizer applied to top 10mm of soil",
    "SWEEPEFF": "Street sweeping removal efficiency (0-1)",
    "FR_CURB": "Fraction of curb length available for sweeping",
    "IMP_TRIG": "Release/impound action (0 = impound, 1 = release)",
    "FERT_DAYS": "Duration of the continuous fertilizer period (days)",
    "CFRT_ID": "Continuous fertilizer ID",
    "IFRT_FREQ": "Continuous fertilizer application frequency (days)",
    "CFRT_KG": "Amount applied per continuous fertilizer event (kg/ha)",
    "CPST_ID": "Continuous pesticide ID",
    "PEST_DAYS": "Duration of the continuous pesticide period (days)",
    "IPEST_FREQ": "Continuous pesticide application frequency (days)",
    "CPST_KG": "Amount applied per continuous pesticide event (kg/ha)",
    "BURN_FRLB": "Fraction of biomass/nutrients remaining after a burn",
}


def label_for(code: str) -> str:
    """Nombre legible de ``code`` (nombre de columna/campo SWAT crudo).
    Devuelve ``code`` sin cambios si no está catalogado -- nunca falla."""
    return PARAMETER_LABELS.get(code.upper(), code)


# IDC (plant.dat línea 1): clase funcional de la planta -- ver guía del
# proyecto sección 17, tabla de valores de IDC.
IDC_CLASSES: dict[int, str] = {
    1: "1 — Warm season annual legume",
    2: "2 — Cold season annual legume",
    3: "3 — Perennial legume",
    4: "4 — Warm season annual",
    5: "5 — Cold season annual",
    6: "6 — Perennial",
    7: "7 — Tree",
}
