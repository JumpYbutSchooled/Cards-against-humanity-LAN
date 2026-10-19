"""Auto-updater: keeps every copy of the game on the newest version from GitHub. Standard library only.

  * VERSION in the repo holds a number; each release bumps it.
  * On launch (main.py) we check GitHub and, if there's something newer, download and install it
    BEFORE the game starts - so you're never stuck one version behind your friends.
  * The game also checks in the background while it runs and offers "restart to update".
  * Several download routes (GitHub API, GitHub raw/codeload, and our Cloudflare relay as a mirror)
    so one blocked address on a school network doesn't break updates.
  * A git clone updates with `git pull --ff-only` when its working tree is clean.
  * Everything that happens is written to update.log next to this file.
"""
import io
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request
import zipfile

REPO = "JumpYbutSchooled/Cards-against-humanity-LAN"
BRANCH = "main"
MIRROR = "https://cah-relay.magnusbradley16.workers.dev/update"
ROOT = os.path.dirname(os.path.abspath(__file__))
UPDATE_DIR = os.path.join(ROOT, ".update")
STAGED = os.path.join(UPDATE_DIR, "staged")
READY = os.path.join(UPDATE_DIR, "ready.json")
LOG = os.path.join(ROOT, "update.log")
KEEP = {"settings.json", ".git", ".update", "update.log"}  # never overwritten by an update
HEADERS = {"User-Agent": "cah-game-updater", "Cache-Control": "no-cache"}


def log(msg):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 100_000:
            os.replace(LOG, LOG + ".old")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def read_version(root=None):
    try:
        with open(os.path.join(root or ROOT, "VERSION"), encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


DEV_MARKER = os.path.join(os.path.expanduser("~"), ".cah-dev-folders")


def is_dev_copy():
    """A developer's own git checkout: updated with git pull, never overwritten.

    Decided per computer (a list of folders in the user's profile), NOT by the presence of .git -
    a zipped-up copy of the developer's folder includes the hidden .git folder, and those copies
    on friends' PCs must still update normally.
    """
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        return False
    try:
        with open(DEV_MARKER, encoding="utf-8-sig") as f:
            folders = {os.path.normcase(os.path.abspath(line.strip())) for line in f if line.strip()}
    except OSError:
        return False
    return os.path.normcase(os.path.abspath(ROOT)) in folders


def _get(url, timeout, extra=None):
    req = urllib.request.Request(url, headers=dict(HEADERS, **(extra or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _first(sources, timeout, what):
    """Tries each (name, url, headers) in turn; returns (name, data). Raises with every error if all fail."""
    errors = []
    for name, url, extra in sources:
        try:
            return name, _get(url, timeout, extra)
        except Exception as e:  # noqa: BLE001 - any failure just means "try the next route"
            errors.append(f"{name}: {e}")
    raise RuntimeError(f"couldn't get {what} ({'; '.join(errors)})")


def remote_version(timeout=5):
    sources = [
        ("github-api", f"https://api.github.com/repos/{REPO}/contents/VERSION?ref={BRANCH}",
         {"Accept": "application/vnd.github.raw"}),
        ("github-raw", f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/VERSION?t={int(time.time())}", None),
        ("mirror", f"{MIRROR}/VERSION", None),
    ]
    name, data = _first(sources, timeout, "the latest version number")
    return int(data.decode("utf-8").strip())


def _zip_sources():
    return [
        ("codeload", f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}", None),
        ("github-api", f"https://api.github.com/repos/{REPO}/zipball/{BRANCH}", None),
        ("mirror", f"{MIRROR}/zip", None),
    ]


def _unpack(data):
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


def download_and_stage(expected_version, timeout=60):
    """Downloads the newest code and unpacks it into .update/staged. Skips stale copies from caches."""
    errors = []
    for name, url, extra in _zip_sources():
        try:
            data = _get(url, timeout, extra)
            _unpack(data)
            got = read_version(STAGED)
            if got < expected_version or not os.path.isfile(os.path.join(STAGED, "main.py")):
                errors.append(f"{name}: gave an old or incomplete copy (v{got})")
                continue
            with open(READY, "w", encoding="utf-8") as f:
                json.dump({"version": got}, f)
            log(f"downloaded v{got} via {name}")
            return got
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    shutil.rmtree(STAGED, ignore_errors=True)
    raise RuntimeError("download failed (" + "; ".join(errors) + ")")


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
        log(f"installed v{version}")
        return version
    except PermissionError as e:
        log(f"install failed - no permission to write game files ({e}). Move the game folder somewhere "
            "like Downloads, or allow Python in Windows Security > Controlled folder access.")
        raise
    finally:
        shutil.rmtree(UPDATE_DIR, ignore_errors=True)


def git_pull():
    """Updates a git clone if it's safe (clean working tree, fast-forward only). Returns True if it pulled."""
    try:
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                               capture_output=True, text=True, timeout=15)
        if dirty.returncode != 0 or dirty.stdout.strip():
            log("git copy has local changes - not pulling automatically")
            return False
        r = subprocess.run(["git", "pull", "--ff-only", "--quiet"], cwd=ROOT, capture_output=True, text=True,
                           timeout=60)
        log(f"git pull -> {r.returncode} {r.stderr.strip()[:300]}")
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError) as e:
        log(f"git pull unavailable: {e}")
        return False


def update_now(say=print):
    """Called on launch, before the game imports anything. Returns the installed version or None."""
    local = read_version()
    try:
        remote = remote_version(timeout=4)
    except Exception as e:  # noqa: BLE001
        log(f"launch check: v{local}, {e}")
        return None
    if remote <= local:
        log(f"launch check: v{local} is up to date")
        return None
    if is_dev_copy():
        say(f"Update v{remote} found - pulling with git...")
        return remote if git_pull() and read_version() >= remote else None
    say(f"Updating from v{local} to v{remote}...")
    try:
        download_and_stage(remote)
        v = apply_staged()
        say(f"Updated to v{v}.")
        return v
    except Exception as e:  # noqa: BLE001
        log(f"launch update failed: {e}")
        say("Update failed - starting the current version. (Details in update.log)")
        return None


class Updater:
    """Background check + download while the game runs. Poll .state from the UI thread."""

    def __init__(self):
        self.local = read_version()
        self.remote = None
        self.state = "checking"  # checking | latest | downloading | ready | dev | offline | error
        self.message = ""
        self.start()

    def start(self):
        self.state = "checking"
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.remote = remote_version()
        except Exception as e:  # noqa: BLE001
            self.state, self.message = "offline", str(e)
            log(f"background check: {e}")
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
        except Exception as e:  # noqa: BLE001
            self.state, self.message = "error", str(e)
            log(f"background update failed: {e}")
