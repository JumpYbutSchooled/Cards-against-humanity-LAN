"""Cards Against Humanity - LAN edition. Run: python main.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import updater  # noqa: E402

# Install a downloaded update before any game code is imported.
try:
    updater.apply_staged()
except Exception as e:  # a failed update must never stop the game from starting
    print("Update could not be applied:", e)

from cah.app import App  # noqa: E402

if __name__ == "__main__":
    App().run()
