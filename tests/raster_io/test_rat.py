"""Regresión del bug real encontrado al probar contra el .aux.xml real del
raster de restauración: el nombre del tipo de campo ("String") está en el
atributo typeAsString de <Type>, no en su texto (que es un código numérico
de enum de GDAL) -- ver raster_io/rat.py."""
from __future__ import annotations

from pathlib import Path

from raster_io.rat import read_pam_rat_names

_REAL_SHAPE_AUX_XML = """<PAMDataset>
  <PAMRasterBand band="1">
    <GDALRasterAttributeTable tableType="thematic">
      <FieldDefn index="0">
        <Name>Value</Name>
        <Type typeAsString="Integer">0</Type>
        <Usage usageAsString="MinMax">5</Usage>
      </FieldDefn>
      <FieldDefn index="1">
        <Name>Count</Name>
        <Type typeAsString="Real">1</Type>
        <Usage usageAsString="Generic">0</Usage>
      </FieldDefn>
      <FieldDefn index="2">
        <Name>descriptio</Name>
        <Type typeAsString="String">2</Type>
        <Usage usageAsString="Generic">0</Usage>
      </FieldDefn>
      <Row index="0">
        <F>0</F>
        <F>49765426</F>
        <F>background</F>
      </Row>
      <Row index="1">
        <F>1</F>
        <F>1767548</F>
        <F>potential wetland area only</F>
      </Row>
    </GDALRasterAttributeTable>
  </PAMRasterBand>
</PAMDataset>
"""


def test_read_pam_rat_names_parses_real_shape(tmp_path: Path) -> None:
    raster_path = tmp_path / "restoration_combine.tif"
    (tmp_path / "restoration_combine.tif.aux.xml").write_text(_REAL_SHAPE_AUX_XML, encoding="utf-8")

    names = read_pam_rat_names(raster_path)

    assert names == {0: "background", 1: "potential wetland area only"}


def test_read_pam_rat_names_none_without_aux_xml(tmp_path: Path) -> None:
    assert read_pam_rat_names(tmp_path / "no_sidecar.tif") is None


def test_read_pam_rat_names_none_without_rat(tmp_path: Path) -> None:
    raster_path = tmp_path / "cdl.tif"
    (tmp_path / "cdl.tif.aux.xml").write_text(
        '<PAMDataset><PAMRasterBand band="1"><Metadata><MDI key="STATISTICS_MAXIMUM">255</MDI></Metadata></PAMRasterBand></PAMDataset>',
        encoding="utf-8",
    )

    assert read_pam_rat_names(raster_path) is None
