"""Test de regresión para un bug real de customtkinter, reportado por el
usuario 2026-08-13: al mover la rueda del mouse sobre ciertos widgets
dentro de un CTkScrollableFrame (sub-widgets internos de ttk.Combobox/
ttk.Treeview, canvas interno de FigureCanvasTkAgg), Tkinter entrega
event.widget como string en vez de como objeto -- CTkScrollableFrame.
_check_if_valid_scroll asumía que siempre tenía `.master` y tiraba
"AttributeError: 'str' object has no attribute 'master'". Corregido en
ui/widgets.py (_patch_ctk_scrollable_frame_wheel_crash), aplicado al
importar el módulo."""
from types import SimpleNamespace

import customtkinter as ctk
import pytest

import ui.widgets  # noqa: F401 - aplica el parche a CTkScrollableFrame al importarse


@pytest.fixture(scope="module")
def hidden_root():
    root = ctk.CTk()
    root.withdraw()
    yield root
    root.destroy()


def test_mouse_wheel_does_not_crash_on_unresolvable_widget_string(hidden_root):
    frame = ctk.CTkScrollableFrame(hidden_root)
    frame.pack()
    hidden_root.update()

    # Un nombre de widget que Tkinter no puede resolver a ningún objeto --
    # antes del parche, esto tiraba AttributeError en el callback de scroll.
    fake_event = SimpleNamespace(widget=".!nonexistent.!widget.path", delta=120, num=4)

    frame._mouse_wheel_all(fake_event)


def test_mouse_wheel_still_resolves_a_real_widget_path_string(hidden_root):
    frame = ctk.CTkScrollableFrame(hidden_root)
    label = ctk.CTkLabel(frame, text="hello")
    label.pack()
    frame.pack()
    hidden_root.update()

    # event.widget como string apuntando a un widget real y válido debe
    # seguir resolviéndose igual que si Tkinter hubiera entregado el
    # objeto directo -- el parche solo agrega tolerancia al caso "no
    # resuelve", no cambia el comportamiento normal.
    fake_event = SimpleNamespace(widget=str(label), delta=120, num=4)

    frame._mouse_wheel_all(fake_event)
