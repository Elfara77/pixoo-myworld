"""Thin shim — redirige vers Pixoo Studio."""

from pixoo_studio.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
