from __future__ import annotations


def _field_by_id(layout: dict, field_id: str) -> dict:
    for field in layout["fields"]:
        if field["id"] == field_id:
            return field
    raise KeyError(f"Campo desconocido en el layout: {field_id}")


def validate_field_value(field_id: str, value: float, layout: dict) -> None:
    """Valida value contra el rango [lo, hi] declarado para field_id en layout.

    lo/hi en None significan "sin cota" de ese lado.
    """
    field = _field_by_id(layout, field_id)
    lo, hi = field["range"]
    if lo is not None and value < lo:
        raise ValueError(f"{field_id}: {value} está por debajo del mínimo permitido ({lo}).")
    if hi is not None and value > hi:
        raise ValueError(f"{field_id}: {value} está por encima del máximo permitido ({hi}).")
