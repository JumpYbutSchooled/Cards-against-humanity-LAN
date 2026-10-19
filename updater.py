"""Auto-updater: pulls new versions from GitHub. Standard library only.

How it works:
  * VERSION in the repo holds a number. Each release bumps it.
  * In the background the game compares the local VERSION with the one on GitHub.
  * If GitHub's is newer it downloads the branch ZIP and unpacks it into .update/staged.
  * Staged updates are copied over the install when the game starts (main.py calls
    apply_staged() before importing anything else), or straight away via "Restart".
  * A folder that is a git clone (it has .git) is a developer copy: it is told about
    updates but never overwritten - use git pull there.
"""
import io
import json
import os
import shutil
import threading
import urllib.request
import zipfile

REPO = "JumpYbutSchooled/Cards-against-humanity-LAN"
BRANCH = "main"
ROOT = os.path.dirname(os.path.abspath(__file__))
UPDATE_DIR = os.path.join(ROOT, ".update")
STAGED = os.path.join(UPDATE_DIR, "staged")
READY = os.path.join(UPDATE_DIR, "ready.json")
KEEP = {"settings.json", ".git", ".update"}  # never overwritten by an update
HEADERS = {"User-Agent": "cah-lan-updater", "Cache-Control": "no-cache"}


def read_version(root=ROOT):
    try:
        with open(os.path.join(root, "VERSION"), encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def is_dev_copy():
    return os.path.isdir(os.path.join(ROOT, ".git"))


def _get(url, timeout, extra=None):
    req = urllib.request.Request(url, headers=dict(HEADERS, **(extra or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def remote_version(timeout=6):
    # The API answers fresh; raw.githubusercontent.com can serve a copy up to ~5 minutes old.
    try:
        data = _get(f"https://api.github.com/repos/{REPO}/contents/VERSION?ref={BRANCH}", timeout,
                    {"Accept": "application/vnd.github.raw"})
    except Exception:
        data = _get(f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/VERSION", timeout)
    return int(data.decode("utf-8").strip())


def download_and_stage(expected_version, timeout=60):
    """Downloads the branch ZIP and unpacks it into .update/staged."""
    try:
        data = _get(f"https://api.github.com/repos/{REPO}/zipball/{BRANCH}", timeout)
    except Exception:
        data = _get(f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}", timeout)
    if os.path.isdir(STAGED):
        shutil.rmtree(STAGED)
    os.makedirs(STAGED, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            # GitHub zips have one top folder ("Repo-main/"); strip it.
            parts = info.filename.replace("\\", "/").split("/")[1:]
            if not parts or not parts[-1] or any(p in ("", ".", "..") for p in parts[:-1]) or parts[0] in KEEP:
                continue
            if ":" in info.filename or info.filename.startswith("/"):
                continue
            dest = os.path.join(STAGED, *parts)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    got = read_version(STAGED)
    if got < expected_version or not os.path.isfile(os.path.join(STAGED, "main.py")):
        shutil.rmtree(STAGED, ignore_errors=True)
        raise RuntimeError("Downloaded update looks incomplete.")
    with open(READY, "w", encoding="utf-8") as f:
        json.dump({"version": got}, f)
    return got


def apply_staged():
    """Copies a staged update over the install. Returns the new version, or None."""
    if is_dev_copy() or not os.path.isfile(READY) or not os.path.isdir(STAGED):
        return None
    try:
        with open(READY, encoding="utf-8") as f:
            version = json.load(f)["version"]
        for dirpath, dirnames, filenames in os.walk(STAGED):
            rel = os.path.relpath(dirpath, STAGED)
            target_dir = ROOT if rel == "." else os.path.join(ROOT, rel)
            os.makedirs(target_dir, exist_ok=True)
            for name in filenames:
                if rel == "." and name in KEEP:
                    continue
                shutil.copy2(os.path.join(dirpath, name), os.path.join(target_dir, name))
        # The card database is rebuilt wholesale upstream, so drop packs that no longer exist.
        new_cards = os.path.join(STAGED, "assets", "cards")
        old_cards = os.path.join(ROOT, "assets", "cards")
        if os.path.isdir(new_cards) and os.path.isdir(old_cards):
            for dirpath, _, filenames in os.walk(old_cards):
                rel = os.path.relpath(dirpath, old_cards)
                for name in filenames:
                    if not os.path.exists(os.path.join(new_cards, rel, name)):
                        os.remove(os.path.join(dirpath, name))
        for dirpath, dirnames, _ in os.walk(ROOT):
            if "__pycache__" in dirnames:
                shutil.rmtree(os.path.join(dirpath, "__pycache__"), ignore_errors=True)
        return version
    finally:
        shutil.rmtree(UPDATE_DIR, ignore_errors=True)


class Updater:
    """Background check + download. Poll .state from the UI thread."""

    def __init__(self):
        self.local = read_version()
        self.remote = None
        self.state = "checking"  # checking | latest | downloading | ready | dev | offline | error
        self.message = ""
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.remote = remote_version()
        except Exception:
            self.state = "offline"
            return
        if self.remote <= self.local:
            self.state = "latest"
            return
        if is_dev_copy():
            self.state = "dev"
            return
        self.state = "downloading"
        try:
            download_and_stage(self.remote)
            self.state = "ready"
        except Exception as e:
            self.state = "error"
            self.message = str(e)
