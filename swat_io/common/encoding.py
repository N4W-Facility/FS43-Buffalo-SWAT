"""Detección conservadora de codificación de texto para archivos SWAT2012.

Estrategia (en este orden):

1. UTF-8 con BOM (``utf-8-sig``) si el archivo empieza con el BOM de UTF-8.
2. UTF-8 sin BOM.
3. ``cp1252`` (codificación típica de archivos Windows antiguos), que acepta
   cualquier secuencia de bytes y por lo tanto actúa como último recurso.

La codificación detectada se conserva en el objeto resultante para que la
capa de escritura pueda reescribir el archivo con la misma codificación en
lugar de convertir todo a UTF-8 de forma silenciosa.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_UTF8_BOM = b"\xef\xbb\xbf"
_FALLBACK_ENCODINGS: tuple[str, ...] = ("utf-8", "cp1252")


@dataclass(frozen=True)
class DecodedText:
    """Resultado de decodificar bytes crudos con la estrategia conservadora."""

    text: str
    encoding: str


def decode_bytes_with_fallback(
    raw: bytes,
    *,
    fallback_encodings: tuple[str, ...] = _FALLBACK_ENCODINGS,
) -> DecodedText:
    """Decodifica ``raw`` probando, en orden, BOM UTF-8, UTF-8 y cp1252.

    ``cp1252`` asigna un carácter a cada uno de los 256 valores de byte,
    así que en la práctica siempre puede decodificar cualquier archivo;
    actúa como red de seguridad final, nunca lanza excepción si aparece en
    ``fallback_encodings``.
    """
    if raw.startswith(_UTF8_BOM):
        return DecodedText(text=raw[len(_UTF8_BOM):].decode("utf-8"), encoding="utf-8-sig")

    last_error: UnicodeDecodeError | None = None
    for encoding in fallback_encodings:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        return DecodedText(text=text, encoding=encoding)

    assert last_error is not None
    raise last_error


def read_text_with_fallback(
    path: str | Path,
    *,
    fallback_encodings: tuple[str, ...] = _FALLBACK_ENCODINGS,
) -> DecodedText:
    """Lee ``path`` como bytes y lo decodifica con :func:`decode_bytes_with_fallback`."""
    raw = Path(path).read_bytes()
    return decode_bytes_with_fallback(raw, fallback_encodings=fallback_encodings)


def encode_text(text: str, encoding: str) -> bytes:
    """Codifica ``text`` con ``encoding`` (incluye soporte nativo para ``utf-8-sig``)."""
    return text.encode(encoding)
