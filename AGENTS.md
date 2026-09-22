# Working in this repo

This is Patrick's Linux fork of the Madden Deluxe texture downloader. The mod author's repo is
`upstream`; this fork is `origin`. Fleet-wide rules live in `~/.claude/CLAUDE.md` and apply here.

## The worker log and the handoff

* **Agents maintain [`worker_log.md`](worker_log.md).** It is your job, not the human's. Every
  piece of work that changes a file or investigates something gets one entry, in **two halves**:
  the heading and the **Starting** line **before** your first change or first investigative
  command, and Did / Checked / Found / Next **after**. Commit it on the same branch as the work.
  Read the recent entries when you start.
* **Entries are append-only.** Never edit or delete one, yours or anyone's; correct it with a new
  entry that points back. The file merges with git's `union` driver (`.gitattributes`), which
  only works if nobody rewrites lines.
* **Agents keep [`handoff.md`](handoff.md) current.** It says where things stand right now and
  what to do next; it is rewritten, not appended. Update its RESUME HERE block before you stop.
* **Write what happened.** A check that did not run is logged as not run. A skip is not a pass.

## Building and testing

* Linux bundles are built on the NAS in a container, never by dispatching CI:
  `tools/linux-build/build.sh --game <id>`. See `handoff.md` for the host and paths.
* `tools/linux-build/check-appimage-opener.py` needs a runner whose glibc matches the jammy build
  image. It will not run on the WSL dev box; use the container or CI.
* The whole `validate` job runs locally: `games.py`, `check-versions.py`, the opener source check
  and the executable-bit check. Run them before you say a change is done.

## This fork's `main` is not upstream's `main`

Since 2026-09-22 the fork's `main` is upstream's `main` plus files that exist only here: this
guide, the worker log, the handoff, `.gitattributes`, and `tools/upstream/`. They are listed in
[`tools/upstream/FORK-ONLY`](tools/upstream/FORK-ONLY). **Never cut a pull request for the mod
author by hand from this `main`.** Keep `main` current with `git merge upstream/main`.

## Proposing work upstream

1. Do the work on a topic branch off `main`, named `dm4800/<topic>`: the fleet push guard refuses
   any branch pushed from this machine without that prefix.
2. Derive the pull request. Rehearse first; it keeps nothing:

   ```
   tools/upstream/derive-pr.py prepare --slug <slug> --paths <every path it may touch> \
     --title "<title>" --message-file <commit message> --body-file <PR body> --rehearse
   ```

   Then the same without `--rehearse`. It builds `dm4800/up-<slug>`: one commit on
   `upstream/main` carrying exactly your change minus every fork-only path. It refuses a head
   that does not contain `upstream/main`, a path outside `--paths`, an empty change, a reused
   slug, a derived tree that fails the repo's own checks, and a tripwire hit (attribution, LAN
   addresses, local paths, machine and fleet-internal names) in the added lines, the title, the
   message or the body. Write the message and body for the mod author's readers: what the change
   does and why, never how this fork works.
3. Commit the ledger row and the staged files it leaves under `tools/upstream/` on the fork,
   with a worker-log entry, and write the owner's publish command into `handoff.md`. The
   command is the fleet publish hand-off from `fleet-toolkit/tools/` in branch mode, with the
   arguments `prepare` prints. It may only be written in `handoff.md` or `worker_log.md`; the
   publish guard refuses it anywhere else. Run that command's `--dry-run` before calling it
   ready.
4. When the mod author merges it: `tools/upstream/derive-pr.py record-merged --slug <slug>`,
   then `git merge upstream/main` into `main`. `derive-pr.py status` shows every row and its
   live state upstream.

`tools/upstream/derive-pr.py --self-test` proves each refusal fires, and for the reason it names.

## Publishing

The agent never pushes to a public repo or opens a pull request, and this fork is public: that
includes pushing its `main`. Prepare the branch, then hand the owner the command; `handoff.md`
carries the current one.
