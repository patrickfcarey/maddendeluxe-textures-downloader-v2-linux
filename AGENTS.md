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

## Publishing

The agent never pushes to a public repo or opens a pull request. Prepare the branch, then hand the
owner the publish command from `fleet-toolkit/tools/`, with `--expect-commits N`; `handoff.md`
carries the current one.
