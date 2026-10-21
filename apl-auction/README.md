# Auction Premier League (APL) — Live Auction Management

A LAN-first live auction web app for an in-person cricket auction. One Node.js server on the operator's laptop owns the auction state; the projector and team phones receive synchronized read-only updates over the local network. Completed changes are written to local JSON files with atomic replacement and rotating backups.

**No cloud backend, hosted database, external API, account, key, or internet connection is used by the running auction.** Install the Node runtime and npm dependencies before event day; after that, the event can run with internet access disconnected.

## Quick start

### Requirements

- Windows 10/11, macOS, or Linux host laptop.
- Node.js 18.17 or later (Node.js 20 LTS recommended).
- One local Wi-Fi network shared by the host, projector browser and participant devices.

### Install and run

```bash
cd apl-auction
npm install
npm start
```

On Windows, double-click `start.bat` (it installs dependencies if `node_modules` is missing). The server binds to `0.0.0.0` and prints the local URL(s) and port. The default port is **3000**.

Open the printed address in a browser, for example `http://192.168.1.10:3000`.

- Operator console: `/admin`
- Projector display: `/display`
- Team selection: `/teams`
- Team dashboard: `/team/<team-id>`
- Player pool: `/players` (administrator only)
- Team setup: `/team-management` (administrator only)
- Auction rules / recovery: `/settings` (administrator only)
- History: `/history` (administrator only)
- Final report: `/report` (administrator only)

On a fresh data directory, the initial administrator PIN is **2468**. Sign in, then change it in **Settings → Administrator security** before the event. You can set a different initial PIN on the first startup with `APL_ADMIN_PIN`; the PIN is only used to create the first local state file. A later restart uses the stored PIN hash.

## Event-day setup

1. **Prepare the host:** Install Node.js and run `npm install` in this folder before the event. Keep this folder and `apl-auction/data/` on the host laptop.
2. **Connect everyone to the same Wi-Fi:** Put the host laptop, projector device and team phones on the same private network. A dedicated router is recommended if campus Wi-Fi uses device/client isolation.
3. **Start the app:** Run `start.bat` or `npm start`. Keep its terminal open while the auction is running. The server prints addresses it found; use the host's Wi-Fi/LAN address, not `localhost`, on other devices.
4. **Configure the auction:** Open `/admin`, change the administrator PIN, set auction rules, add/import teams and add/import players. Add team PINs if team budgets should be private.
5. **Open the projector:** On the display device, open `http://<host-lan-ip>:3000/display` and choose **Fullscreen**.
6. **Connect teams:** Share `http://<host-lan-ip>:3000/teams`. Teams select their franchise and enter its PIN if configured.
7. **Run the auction:** Start the auction, select a player from the queue, enter each verbally announced bid and choose **Confirm bid**. Confirm **SOLD** or **UNSOLD** at the end of bidding. Select the next player only when the room is ready; result screens do not auto-advance.
8. **Back up:** Export full auction JSON from **Settings** or copy the local `data/` folder after stopping the server.

### Firewall and network notes

- On the first Windows launch, allow **Node.js** through Windows Defender Firewall on **Private networks only**. Do not enable Public-network access unless your network administrator specifically requires it.
- Check that Windows marks the event Wi-Fi as a **Private** network. The app does not configure Windows Firewall itself.
- Run `ipconfig` if the printed IP is unclear. Use the IPv4 address for the active Wi-Fi/Ethernet adapter (typically `192.168.x.x`, `10.x.x.x` or `172.16–31.x.x`). Do not use `127.0.0.1` or `localhost` from a phone.
- To change the port, set `PORT` before starting (`set PORT=3001` in Command Prompt, then run `start.bat`) or use `PORT=3001 npm start` in a Unix shell. The app prints the new URL.
- If the page opens on the host but not on phones, check the host and phones are on the same Wi-Fi, allow Node through the private firewall, verify the host IP/port, and check that the access point allows device-to-device traffic.
- Some college Wi-Fi networks deliberately isolate clients. If phones cannot reach the host even after firewall approval, use a dedicated Wi-Fi router with client isolation disabled. The router does not need internet service.
- Do not port-forward the auction port or expose it to the public internet. The design is for a trusted private LAN.

## Operator workflow

- **Teams:** Add/edit/remove franchises before the auction starts. The purse is stored as an integer number of rupees. Optional PINs are salted and hashed locally; PIN values are never returned to the browser. Team details and budgets lock after the auction begins.
- **Players:** Add players manually or use CSV import. CSV validation reports every bad row before the all-or-nothing import commit. Player IDs must be unique; supported primary roles are Batter, Bowler, All-rounder and Wicketkeeper. Categories and statistics are optional.
- **Rules:** Configure the default purse for new teams, currency symbol, default and price-tier bid increments, squad size and role requirements, purse visibility, upcoming-player reveal, unsold reintroduction, bid overrides and team PIN requirements. Role maximums are enforced when bidding and selling; minimums are displayed as squad requirements.
- **Bidding:** A bid is provisional and does not reserve or deduct purse. The server checks auction status, player eligibility, increments, team activity, remaining purse and squad maximums. A sale is committed only if the winning team and price match the accepted highest bid, unless an enabled, explicitly confirmed override is used.
- **Results:** SOLD updates player ownership, purchase price, squad and budget in one serialized transaction. UNSOLD never assigns a team. The operator manually selects the next player.
- **Undo:** The latest sale can be reversed when no later transaction depends on it. The original sale stays in history as reversed, an undo record is added, purse/squad calculations are restored, and the state is persisted. Older sales are not silently rewound.
- **Reset:** Reset requires an explicit confirmation. It resets all players to Available, clears transaction history and sale results, and keeps team/player definitions and rules. The audit log records the reset; an automatic backup preserves the prior state.
- **Reports:** The report includes team squads, purse summary, role counts, unsold players, overall spend, average sale and highest-priced player. Export JSON/CSV or print it from the report page.

## Data, backups and privacy

Runtime data is local to this folder and is not served as static web content:

```text
data/auction.json           Current committed auction state
data/backups/                Timestamped recovery copies (latest 40 retained)
public/uploads/              Locally uploaded player/team images
```

The server writes a temporary JSON file and replaces the state file only after validation and a successful disk write. A backup is created before committed changes. On startup, the last valid state is loaded. If the active JSON is invalid, the server searches backups and reports recovery; if no valid copy exists, it stops rather than silently creating a fresh auction. A sale is not acknowledged until the save succeeds.

Sessions are kept in server memory and expire after 12 hours; after a server restart, users sign in again. The persistent file stores credential hashes, not PIN text. Full JSON exports omit administrator/team PIN hashes; restoring an export preserves the current local credentials. Local server backups contain the full recoverable state and should be treated as private files.

## CSV files

Download the templates and example records under `samples/` (also linked in the admin pages):

- `samples/players-template.csv`
- `samples/players-demo.csv`
- `samples/teams-template.csv`
- `samples/teams-demo.csv`

The demo CSV files are optional test data only; the first run starts with an empty team and player pool. Import your actual APL records or create them manually. Player prices and team purses are plain integer rupees (for example `1000000`, not a formatted `₹10,00,000`). Player photo and team logo paths are optional; use the local image upload control in the admin form to add photos.

## Commands

```bash
npm install             # one-time dependency installation, while internet is available
npm start                # start on 0.0.0.0:3000 (or PORT)
npm test                 # automated auction-rule, finance, CSV, LAN sync and restart-recovery tests
```

`start.bat` starts the same server on Windows. To stop safely, focus the server terminal and press **Ctrl+C**; all accepted changes have already been committed to disk. `stop.bat` prints this instruction.

## What the tests cover

The test suite checks authoritative purse math, increment validation and override handling, duplicate-sale protection, serialized concurrent sale attempts, UNSOLD handling and reintroduction, sale undo and audit reversal, CSV validation, persistence-failure safety, report calculations, administrator mutation protection, multi-client Socket.IO updates, reconnect synchronization and state restoration after a server restart.

The browser-facing application uses local static files and the server's bundled Socket.IO client. It does not request remote fonts, player images, analytics or other internet resources.
