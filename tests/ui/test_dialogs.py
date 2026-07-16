def test_dialogs_module_exposes_ask_choice_and_ask_text() -> None:
    from ui import dialogs

    assert callable(dialogs.ask_choice)
    assert callable(dialogs.ask_text)
