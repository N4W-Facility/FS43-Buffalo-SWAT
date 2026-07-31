from __future__ import annotations

from config.settings import ConfigManager
from ui import App


def main() -> None:
    config = ConfigManager()
    config.load_all()
    app = App(config)
    app.mainloop()


if __name__ == "__main__":
    main()
