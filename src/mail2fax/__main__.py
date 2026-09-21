"""Ermoeglicht den Aufruf ueber ``python -m mail2fax``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
