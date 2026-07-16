import customtkinter as ctk
import pytest


@pytest.fixture
def hidden_root():
    root = ctk.CTk()
    root.withdraw()
    yield root
    root.destroy()
