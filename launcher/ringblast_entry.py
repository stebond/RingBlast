"""Entry point used by the PyInstaller build (the package uses relative imports)."""
import sys

from ringblast.gui.launch import main

if __name__ == "__main__":
    sys.exit(main())
