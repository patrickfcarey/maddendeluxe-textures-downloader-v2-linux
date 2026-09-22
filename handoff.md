# Handoff

Where this fork stands and what to do next. Rewritten, not appended: the running history is in
[`worker_log.md`](worker_log.md). Read `AGENTS.md` first.

---

## RESUME HERE (2026-09-22)

**PR #6 is open upstream and waiting on the mod author to merge:**
https://github.com/maddendeluxe/maddendeluxe-textures-downloader-v2/pull/6, from
`patrickfcarey:dm4800/ci-opener-regression-tests`, head `7548a80`, one commit. It adds the CI tests
that would have caught the SteamOS link bug. Opened by the owner 2026-09-22 04:34 UTC. GitHub
records Patrick Carey as author and committer; no attribution lines. Its `validate` job passed in
12 s, which is the first run of `check-versions.py` and the opener's `--self-test` and `--source`
on GitHub's own runner. The twelve build jobs were queued when this was written; the worker log
records their result. When it merges, nothing further is owed for it.

**One branch is still waiting on the owner, unpushed:** `dm4800/handoff-and-worker-log`, this
file, `worker_log.md`, `AGENTS.md` and `.gitattributes`. These are fork-operational files. Whether
they go to the mod author's repo or only to the fork's own `main` is the owner's call; nothing is
prepared for upstream. Every branch pushed from this machine needs the `dm4800/` prefix, or the
fleet push guard refuses it.

**Nothing else is in flight.** The link fix (PR #5) is merged upstream and the build on main was
green for all twelve jobs.

## State (OBSERVED 2026-09-20)

- **Version 2.0.6** is on `upstream/main` (merge `4a7f120`; three README commits after it, tip
  `5af7c1a`). Every earlier Linux bundle should be treated as broken: 2.0.0 and 2.0.1 have the
  blank window and the library leak, 2.0.2 opens no link on SteamOS, 2.0.3 through 2.0.5 were
  test builds and must not ship.
- **All four games build and validate**, `tools/games.py validate --remote` GREEN. The Madden 05
  startup 404 is gone: its texture repo now carries `installer-data.json`.
- **The SteamOS link bug is fixed and confirmed by the owner** on a Valve Steam Machine. Two
  faults, both search order: the bundle's own `xdg-open` ran (no Plasma 6 case, exit 0), and
  `/usr/share` was promoted ahead of the Flatpak exports so a stub "Install Firefox" `.desktop`
  won. Mechanism and evidence: the header of `src-tauri/src/commands/open_external.rs`, and
  `worker_log.md` under 2026-09-19.
- **The app writes `~/textures-downloader-debug.log`**: version, OS, environment (secret-shaped
  names redacted), an opener survey, every opener attempt with the child's own output, and the
  webview console. Ask a user for it. A GitHub token cannot appear in it.
- **Working tree noise:** on this Windows drive every file shows modified from CRLF churn. HEAD
  stores LF. Convert a file to LF before staging it, and stage named files only
  (`git diff --ignore-cr-at-eol --stat HEAD` shows the real changes).

## Machines and paths

- **Build host:** the NAS, `ssh pacarey@192.168.68.185`. Checkout `/tank/builds/maddendeluxe-2.0.2`
  (the name is stale; contents track this fork). Build logs `/tank/builds/build-madden09-<ver>.log`.
  Container `tauri-linux-build:jammy`. The cargo target dir lives inside the checkout; keep it.
- **SteamOS test boxes:** `ssh valve-steam-machine` and `ssh steam-deck`, documented in
  `star-command/captured-reality/starbase/systems/`. Someone may be using the Steam Machine's
  screen (Plex); screenshot with `spectacle -b -n -f` before putting a window on it. Launch a GUI
  app with the session's environment (`/proc/$(pgrep -x plasmashell)/environ`) and act within the
  same SSH session, because the app dies when the session ends. XTEST clicks cannot raise a
  window under KWin; the app's `--diagnose-open` is the headless path.
- **Deliveries:** `C:\Users\root\Downloads\madden09-<ver>\`, never `Public\Downloads`. The owner
  runs builds from a Ventoy USB, `Ventoy/data/madden09-<ver>/`.
- **Commit identity:** Patrick Carey `<patrickfcarey@gmail.com>` as author AND committer, no
  attribution lines.

## Do not

- Push, open a PR, or dispatch CI to get a binary. Build on the NAS; publishing is the owner's.
- Ship anything numbered 2.0.3, 2.0.4 or 2.0.5.
- Run `check-appimage-opener.py` on the WSL box; its glibc is older than the build image and the
  failure is the environment, not the app.
- `pkill` an AppImage: its WebKit helpers SIGBUS when the FUSE mount vanishes.
- Add UI the owner did not ask for. A diagnostic banner was built and removed on 2026-09-20.
- Put a game name into shared source; games live under `games/<id>/`.

## Still owed

- The mod author merges PR #6.
- The owner decides where `dm4800/handoff-and-worker-log` goes.
- Optional: identify what the rig's `~/madden-linux-test/pr4.AppImage` was built from.
