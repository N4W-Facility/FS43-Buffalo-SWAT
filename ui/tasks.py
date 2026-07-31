"""Patrón obligatorio de hilo de fondo + cola para operaciones largas.

CLAUDE.md: cualquier operación que pueda tardar más que milisegundos sobre
un modelo real (parsear miles de .hru/.pnd, y en el futuro correr
swat2012.exe) debe correr en threading.Thread(daemon=True). Ese hilo nunca
llama a widget.after() ni toca ningún widget directamente — solo empuja
mensajes a una queue.Queue. El hilo principal sondea la cola con
widget.after(), y en cada ciclo aplica solo el último mensaje de progreso
encontrado (nunca uno por uno): con archivos reales el hilo de fondo puede
encolar más rápido de lo que la UI alcanza a procesar, y redibujar por
cada mensaje congela la ventana igual, dos capas más abajo del bug
original. Este helper centraliza el patrón para que cada pestaña no lo
reimplemente.
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable

_POLL_INTERVAL_MS = 150


@dataclass(frozen=True)
class _Progress:
    message: str


@dataclass(frozen=True)
class _Done:
    result: Any


@dataclass(frozen=True)
class _Failed:
    error: Exception


def run_in_background(
    widget: Any,
    fn: Callable[[Callable[[str], None]], Any],
    *,
    on_progress: Callable[[str], None],
    on_done: Callable[[Any], None],
    on_error: Callable[[Exception], None],
    poll_interval_ms: int = _POLL_INTERVAL_MS,
) -> None:
    """Corre fn(report_progress) en un hilo de fondo y sondea sus mensajes
    desde el hilo principal vía widget.after().

    fn recibe un callback report_progress(str) que puede invocar cuantas
    veces quiera desde el hilo de fondo; ese callback solo hace
    queue.put(...), nunca toca widgets. on_progress/on_done/on_error
    siempre corren en el hilo principal (llamados desde widget.after()).
    """
    message_queue: "queue.Queue[_Progress | _Done | _Failed]" = queue.Queue()

    def report_progress(message: str) -> None:
        message_queue.put(_Progress(message))

    def worker() -> None:
        try:
            result = fn(report_progress)
        except Exception as exc:  # noqa: BLE001 - se reporta a la UI, nunca se traga
            message_queue.put(_Failed(exc))
        else:
            message_queue.put(_Done(result))

    def poll() -> None:
        latest_progress: _Progress | None = None
        terminal: _Done | _Failed | None = None
        try:
            while True:
                item = message_queue.get_nowait()
                if isinstance(item, _Progress):
                    latest_progress = item
                else:
                    terminal = item
        except queue.Empty:
            pass

        if latest_progress is not None:
            on_progress(latest_progress.message)

        if terminal is None:
            widget.after(poll_interval_ms, poll)
            return

        if isinstance(terminal, _Done):
            on_done(terminal.result)
        else:
            on_error(terminal.error)

    threading.Thread(target=worker, daemon=True).start()
    widget.after(poll_interval_ms, poll)
