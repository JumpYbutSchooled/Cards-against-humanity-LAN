"""Cards Against Humanity - online/LAN edition. Run: python main.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import updater  # noqa: E402

# Update BEFORE any game code is imported, so this launch already runs the newest version.
try:
    updater.apply_staged()  # something downloaded in the background last session
    if os.environ.get("CAH_NO_UPDATE") != "1":
        print("Checking for updates...")
        updater.update_now()
except Exception as e:  # a failed update must never stop the game from starting
    updater.log(f"update step crashed: {e!r}")
    print("Update could not be applied - starting anyway. See update.log.")

from cah.app import App  # noqa: E402

if __name__ == "__main__":
    App().run()
