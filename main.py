"""Cards Against Humanity - online/LAN edition. Run: python main.py"""
import os
import platform
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def report_crash(exc):
    """Save the error to crash.log and show it in a popup, so a crash is never just a vanishing window."""
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        version = open(os.path.join(ROOT, "VERSION")).read().strip()
    except OSError:
        version = "?"
    try:
        import pygame
        pg = pygame.version.ver
    except Exception:  # noqa: BLE001
        pg = "not installed"
    header = (f"{time.strftime('%Y-%m-%d %H:%M:%S')}  game v{version}  Python {platform.python_version()}  "
              f"pygame {pg}  {platform.platform()}")
    path = os.path.join(ROOT, "crash.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(header + "\n" + details + "\n")
    except OSError:
        path = "(could not write crash.log)"
    print(header, details, sep="\n", file=sys.stderr)
    last = details.strip().splitlines()[-1][:300]
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, f"The game crashed:\n\n{last}\n\nThe full details were saved to:\n{path}\n\n"
                      "Send that file to whoever set up the game.", "Cards Against Humanity - crash", 0x10)
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    # Hard crashes inside pygame/SDL skip Python's error handling; faulthandler still logs where they hit.
    try:
        import faulthandler
        _fault_log = open(os.path.join(ROOT, "crash.log"), "a", encoding="utf-8")
        faulthandler.enable(_fault_log)
    except OSError:
        pass
    try:
        import updater

        # Update BEFORE any game code is imported, so this launch already runs the newest version.
        try:
            updater.apply_staged()  # something downloaded in the background last session
            if os.environ.get("CAH_NO_UPDATE") != "1":
                print("Checking for updates...")
                updater.update_now()
        except Exception as e:  # a failed update must never stop the game from starting
            updater.log(f"update step crashed: {e!r}")
            print("Update could not be applied - starting anyway. See update.log.")

        from cah.app import App
        App().run()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:  # noqa: BLE001
        report_crash(e)
        sys.exit(1)
