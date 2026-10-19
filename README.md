# Cards Against Humanity – LAN Edition

A pygame version of Cards Against Humanity. It has 205 packs (base game, every expansion, and third-party games), hot-seat play on one computer, and LAN multiplayer with automatic game discovery.

## Install (for everyone playing)

1. Install **Python 3.10+** from https://www.python.org/downloads/ and tick **"Add python.exe to PATH"** during setup.
2. Get the game: green **Code** button → **Download ZIP**, then unzip it anywhere.
3. Double-click **`Play.bat`**. The first run installs pygame automatically.

**Updates are automatic.** On launch the game checks GitHub and downloads any new version in the background. The main menu then shows **"Update ready – restart now"**. If you don't click it, the update installs the next time you start the game.

## Multiplayer

1. The host goes to **Multiplayer → Host Game**. The lobby shows a **room code** like `M J E F`. They can add bots and pick the packs and points.
2. Everyone else goes to **Multiplayer**, types the code, and presses **Join**.
3. The host presses **Start**.

Room codes work on **any network**: school Wi-Fi, different houses, phone hotspots. Like Epic's relay in Baldi's multiplayer, every player connects *out* to a small relay server (`relay/`, on Cloudflare Workers, port 443), so nobody needs open ports or firewall changes. The game rules still run on the host's PC.

If someone's Wi-Fi drops, they reconnect on their own within 30 seconds and get their seat back. A bot plays for them in the meantime. The host can kick players from the lobby.

**LAN fallback:** on a home network, games also show up under "On the same home network", or you can join by IP. This uses TCP port 47474 and UDP port 47475, and doesn't work on most school networks.

## Local (hot-seat) play

Go to **Play Local** and add people and bots. Everyone shares one screen, and a cover screen hides each person's hand until they click.

Keys: Esc opens the menu, Enter or Space confirms, 1–9 pick cards, F11 toggles fullscreen.

## Card packs

**Card Packs** is a checklist. Tick any mix of packs, or tick a group's checkbox to select the whole group. Click a group's arrow or name to expand or collapse it. Ctrl+F searches.

`assets/cards/` holds one JSON file per pack, sorted by group (`Official/Base Game/CAH Base Set.json`, `Third-Party/Crabs Adjust Humidity/...`), plus an `index.json`.
`python tools/build_cards.py` rebuilds the folder from the latest card database.

## For developers

- **Bump the number in `VERSION` with every push.** Players only get an update when that number goes up.
- If you change the network messages, also bump `PROTOCOL` in `cah/net.py`, so old and new versions refuse to connect to each other instead of misbehaving.
- A git clone never auto-overwrites itself. It only shows "vN is on GitHub – git pull to update".
- Code layout: `cah/engine.py` holds the game rules and runs on the host. `cah/net.py` is the server, client, LAN discovery and relay hookup. `cah/ws.py` is a tiny WebSocket client. `cah/scene_*.py` are the screens. `updater.py` is the auto-updater. `relay/` is the Cloudflare Worker.
- Relay: `cd relay`, `npm install`, `npx wrangler dev` for a local copy (`set CAH_RELAY=ws://127.0.0.1:8787` points the game at it), and `npx wrangler deploy` to publish. It runs on the free plan (Durable Objects, one per room).

## Credits

Cards Against Humanity is © Cards Against Humanity LLC and is released under CC BY-NC-SA 2.0.
The card text comes from [JSON Against Humanity](https://github.com/crhallberg/json-against-humanity) by Chris Hallberg (CC BY-NC-SA 4.0).
Third-party packs belong to their own creators. This project is for personal, non-commercial use only.
