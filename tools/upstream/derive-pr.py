#!/usr/bin/env python3
"""Derive a pull request for the mod author's repo from work in this fork.

WHY THIS EXISTS. From 2026-09-22 this fork's `main` carries files that belong to the fork alone:
the worker log, the handoff, an agent guide, the pipeline you are reading. Cutting a pull request
from it by hand means remembering, every time, which files must not go. This does the
remembering, the way emulator-release-repo's Workflow B does for the emulators, scaled down: the
owner rates this repo low-stakes, so there is one derive, one ledger and no release machinery.

WHAT A PULL REQUEST IS HERE. Exactly this, by construction:

    diff( upstream/main , HEAD minus the paths in tools/upstream/FORK-ONLY )

restricted to the paths the caller names with --paths. It lands as ONE commit on a branch based
on upstream/main, named dm4800/up-<slug> (the fleet push guard refuses a branch from this
machine without the device prefix). The owner then publishes that branch with the fleet's
publish hand-off in branch mode, the path PR #6 proved; the exact command is written into
handoff.md, the one file where it may be written. This tool never publishes and never pushes.

IT REFUSES, naming the reason, when:
  * HEAD does not contain upstream/main. The diff would silently revert upstream's newer work.
  * a --paths entry is itself fork-only, or nothing crosses at all.
  * a path crosses that --paths does not cover. Unrelated pending work does not ride along;
    name it or leave it out.
  * a fleet-convention file (worker_log.md, handoff.md) would cross from anywhere in the tree.
  * a tripwire hits in an added line, the title, the commit message or the PR body: an
    attribution line, a LAN address, a local path, a machine or fleet-internal name. Three of
    those four are prose a person wrote, and the path filter never sees prose.
  * the repo's own validate checks fail on the DERIVED tree. A check that does not exist
    upstream yet is reported as not run, never as passed.
  * the slug or its branch is already used: in the ledger, locally, on the fork, or upstream.
  * the fleet push guard, asked offline, would refuse the branch.

  derive-pr.py prepare --slug S --paths P[,P..] --title T --message-file M --body-file B
                       [--head REF] [--rehearse]
  derive-pr.py status                  the ledger, with each PR's live state upstream
  derive-pr.py record-merged --slug S  mark a row MERGED once the mod author merges it
  derive-pr.py --self-test

A real `prepare` leaves three things for the caller to commit on the fork, with a worker-log
entry: the ledger row in tools/upstream/prs.jsonl, and tools/upstream/prs/<slug>/{COMMIT_MSG.txt,
BODY.md}. The derived branch itself is a local git ref.

TOOLS INDEX (H-16). Searched first: toolindex "derive pull request fork upstream patch filter"
and "prepare pr against upstream from fork exclude fork-only files" -> pcsx2-VR
70-fork-integrity.sh, xbox360-static-recomp run-gates.sh, unrelated validators; the new-tool hook
added games.py (a per-game manifest reader), build.sh and strip-bundled-wayland.sh. None derives
a patch. emulator-release-repo/tools/pr-prepare.py is the model but is bound to that repo's
targets/, ledgers and a tools/release/derive.py this repo does not have.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPSTREAM_SLUG = "maddendeluxe/maddendeluxe-textures-downloader-v2"
BRANCH_PREFIX = "dm4800/up-"
IDENTITY = os.environ.get("DERIVE_IDENTITY", "Patrick Carey <patrickfcarey@gmail.com>")
PUSH_GUARD = Path.home() / ".git-templates" / "hooks" / "pre-push"
CONVENTION_FILES = {"worker_log.md", "handoff.md"}
STAGING = Path("tools") / "upstream" / "prs"
LEDGER = Path("tools") / "upstream" / "prs.jsonl"

# Prose and added lines that must never reach the mod author's repo. (name, pattern)
TRIPWIRES = [
    ("attribution trailer", r"co-authored-by"),
    ("assistant attribution", r"noreply@anthropic\.com|generated with \[?claude|claude\.ai/code|\bclaude\b"),
    ("LAN address", r"\b192\.168\.\d{1,3}\.\d{1,3}\b"),
    ("local path", r"/home/pacarey|/mnt/c/|C:\\Users\\root|/tank/|/turret/"),
    ("login or machine name", r"pacarey@|\bdm4800\b|laptop-dm4800|valve-steam-machine"),
    ("fleet-internal name",
     r"worker_log|handoff\.md|star-command|fleet-toolkit|retro-vr-framework|emulator-release-repo|TASK-CLASS"),
]


class Refusal(Exception):
    pass


def git(root, *args, check=True):
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise Refusal(f"git {' '.join(args[:3])} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def is_ancestor(root, older, newer):
    return subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", older, newer]).returncode == 0


def load_fork_only(path):
    return [l.strip().strip("/") for l in Path(path).read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")]


def under(path, root):
    return path == root or path.startswith(root + "/")


def excludes(fork_only):
    return [f":(exclude){p}" for p in fork_only]


def tripwire_hits(label, text):
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        for name, pattern in TRIPWIRES:
            if re.search(pattern, line, re.I):
                hits.append(f"{label}:{number}: {name}: {line.strip()[:100]}")
    return hits


def added_lines(patch):
    """The '+' lines of a patch, each with the file it lands in, so a hit says where it is."""
    out, current = [], "?"
    for line in patch.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+"):
            out.append((current, line[1:]))
    return out


def validate_derived(tree):
    """The repo's own validate checks, run inside the derived tree. -> (ran, not_run, failures)"""
    ran, not_run, failures = [], [], []
    for name, script, args in (
            ("games.py validate", "tools/games.py", ["validate"]),
            ("check-versions.py", "tools/check-versions.py", []),
            ("opener source guard", "tools/linux-build/check-appimage-opener.py", ["--source"])):
        if not (tree / script).exists():
            not_run.append(f"{name} (not in upstream yet)")
            continue
        proc = subprocess.run([sys.executable, script, *args], cwd=tree, capture_output=True,
                              text=True, timeout=180)
        ran.append(name)
        if proc.returncode != 0:
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
            failures.append(f"{name} exited {proc.returncode}: " + " | ".join(tail))
    # The same executable-bit rule upstream's CI enforces on tools/.
    bad = [l.split("\t", 1)[1] for l in git(tree, "ls-files", "--stage", "--", "tools").splitlines()
           if l and not l.startswith("100755") and re.search(r"\.(sh|py)$", l)]
    ran.append("executable bits")
    if bad:
        failures.append("not executable in git: " + ", ".join(bad))
    return ran, not_run, failures


def read_ledger(root):
    path = root / LEDGER
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def write_ledger(root, rows):
    path = root / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def gh_prs(branch, state="all"):
    """Pull requests upstream whose head is this branch. None when gh cannot answer."""
    proc = subprocess.run(
        ["gh", "pr", "list", "--repo", UPSTREAM_SLUG, "--head", branch, "--state", state,
         "--json", "number,state,url,mergeCommit,mergedAt"],
        capture_output=True, text=True)
    return json.loads(proc.stdout or "[]") if proc.returncode == 0 else None


def repo_root():
    return Path(git(".", "rev-parse", "--show-toplevel").strip())


def prepare(args):
    root = repo_root()
    fork_only = load_fork_only(args.fork_only)
    paths = [p.strip().strip("/") for p in args.paths.split(",") if p.strip()]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,48}", args.slug):
        raise Refusal(f"slug {args.slug!r}: use 2-49 characters of a-z, 0-9 and '-'")
    branch = BRANCH_PREFIX + args.slug
    if not paths:
        raise Refusal("--paths is empty; name every path this pull request may touch")
    for p in paths:
        hit = next((f for f in fork_only if under(p, f)), None)
        if hit:
            raise Refusal(f"--paths entry {p!r} is fork-only ({hit} in FORK-ONLY); it can never cross")
    try:
        message = Path(args.message_file).read_text()
        body = Path(args.body_file).read_text()
    except OSError as exc:
        raise Refusal(str(exc))

    if not args.offline:
        url = git(root, "remote", "get-url", "upstream").strip()
        if UPSTREAM_SLUG not in url:
            raise Refusal(f"remote 'upstream' is {url}, not {UPSTREAM_SLUG}")
    if not args.no_fetch:
        git(root, "fetch", "upstream", "--quiet")
    base = git(root, "rev-parse", "--verify", "upstream/main^{commit}").strip()
    head = git(root, "rev-parse", "--verify", f"{args.head}^{{commit}}").strip()
    if not is_ancestor(root, base, head):
        raise Refusal(f"{args.head} does not contain upstream/main ({base[:7]}). Merge upstream/main into "
                      "it first; otherwise the diff would revert upstream's newer work.")

    crossing = [p for p in git(root, "diff", "--name-only", "-z", "--no-renames", base, head,
                               "--", ".", *excludes(fork_only)).split("\0") if p]
    if not crossing:
        raise Refusal(f"nothing crosses: every change between upstream/main and {args.head} is fork-only")
    convention = [p for p in crossing if Path(p).name in CONVENTION_FILES]
    if convention:
        raise Refusal("a fleet-convention file would cross: " + ", ".join(convention))
    stray = [p for p in crossing if not any(under(p, q) for q in paths)]
    if stray:
        raise Refusal("these would cross but --paths does not cover them (name them, or keep them "
                      "out of this head): " + ", ".join(stray))

    patch = git(root, "diff", "--binary", "--full-index", "--no-renames", base, head,
                "--", *paths, *excludes(fork_only))
    hits = tripwire_hits("title", args.title) + tripwire_hits("message", message) + tripwire_hits("body", body)
    for file, line in added_lines(patch):
        for name, pattern in TRIPWIRES:
            if re.search(pattern, line, re.I):
                hits.append(f"{file}: {name}: {line.strip()[:100]}")
    if hits:
        raise Refusal("tripwire:\n  " + "\n  ".join(hits))

    if any(r["slug"] == args.slug for r in read_ledger(root)):
        raise Refusal(f"slug {args.slug!r} is already in the ledger; pick a new one")
    if git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).strip():
        raise Refusal(f"branch {branch} already exists locally")
    if not args.offline:
        if git(root, "ls-remote", "--heads", "origin", branch).strip():
            raise Refusal(f"branch {branch} already exists on the fork")
        prs = gh_prs(branch)
        if prs is None:
            raise Refusal("could not ask the upstream repo whether this branch already has a pull request")
        if prs:
            raise Refusal(f"{branch} already has pull request #{prs[0]['number']} upstream ({prs[0]['state']})")

    workdir = Path(tempfile.mkdtemp(prefix="derive-pr-"))
    tree = workdir / "tree"
    try:
        git(root, "worktree", "add", "--detach", "--quiet", str(tree), base)
        (workdir / "PATCH.diff").write_text(patch)
        git(tree, "apply", "--index", "--binary", str(workdir / "PATCH.diff"))
        ran, not_run, failures = validate_derived(tree)
        if failures:
            raise Refusal("the derived tree fails its own checks:\n  " + "\n  ".join(failures))
        name, email = re.fullmatch(r"(.+?)\s*<(.+)>", IDENTITY).groups()
        env = {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
               "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}
        (workdir / "COMMIT_MSG").write_text(message)
        proc = subprocess.run(["git", "-C", str(tree), "commit", "--quiet", "-F", str(workdir / "COMMIT_MSG")],
                              env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            raise Refusal(f"commit failed: {proc.stderr.strip()[:300]}")
        derived = git(tree, "rev-parse", "HEAD").strip()
        if git(tree, "diff", "--binary", "--full-index", "--no-renames", base, derived) != patch:
            raise Refusal("internal: the derived commit is not exactly the derived patch")
    finally:
        subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(tree)], capture_output=True)
        subprocess.run(["git", "-C", str(root), "worktree", "prune"], capture_output=True)
        shutil.rmtree(workdir, ignore_errors=True)

    guard = "not run (--offline)"
    if not args.offline:
        if not PUSH_GUARD.exists():
            guard = f"not run ({PUSH_GUARD} is missing)"
        else:
            origin = git(root, "remote", "get-url", "origin").strip()
            proc = subprocess.run([str(PUSH_GUARD), "origin", origin], cwd=root,
                                  input=f"refs/heads/{branch} {derived} refs/heads/{branch} {'0' * 40}\n",
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                reason = next((l.strip() for l in (proc.stdout + proc.stderr).splitlines() if "reason" in l), "")
                raise Refusal(f"the fleet push guard would refuse {branch}: {reason}")
            guard = "allows the push"

    print(f"derived {len(crossing)} file(s) from {args.head} ({head[:7]}) onto upstream/main ({base[:7]}):")
    for p in crossing:
        print(f"  {p}")
    print(f"checks ran: {', '.join(ran)}; not run: {', '.join(not_run) or 'none'}")
    print(f"push guard: {guard}")
    if args.rehearse:
        print(f"REHEARSAL GREEN. Nothing kept: no branch, no ledger row. It would be {branch} at {derived[:7]}.")
        return 0

    git(root, "branch", branch, derived)
    staged = root / STAGING / args.slug
    staged.mkdir(parents=True, exist_ok=True)
    (staged / "COMMIT_MSG.txt").write_text(message)
    (staged / "BODY.md").write_text(body)
    rows = read_ledger(root)
    rows.append({"slug": args.slug, "state": "PREPARED", "branch": branch, "commit": derived,
                 "base": base, "head": head, "paths": paths, "title": args.title,
                 "prepared": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    write_ledger(root, rows)
    print(f"PREPARED {branch} at {derived[:7]}, one commit over upstream/main.")
    print("Publish it with the fleet hand-off in branch mode, from the owner's own terminal, with:")
    print(f"  --repo {root} --upstream {UPSTREAM_SLUG} --branch {branch} --expect-commits 1 "
          f"--base main --remote origin --title {json.dumps(args.title)} --body-file {staged / 'BODY.md'}")
    print("Write that command into handoff.md, then commit the ledger and the staged files on the fork.")
    return 0


def status(args):
    root = repo_root()
    rows = read_ledger(root)
    if not rows:
        print("ledger is empty")
    for r in rows:
        live = ""
        if r["state"] == "PREPARED":
            prs = gh_prs(r["branch"])
            live = "  upstream: " + ("could not ask" if prs is None else
                                      ", ".join(f"#{p['number']} {p['state']}" for p in prs) or "not opened")
        print(f"{r['slug']:32} {r['state']:9} {r['commit'][:7]}  {r['title']}{live}")
    return 0


def record_merged(args):
    root = repo_root()
    rows = read_ledger(root)
    row = next((r for r in rows if r["slug"] == args.slug), None)
    if row is None:
        raise Refusal(f"no ledger row for slug {args.slug!r}")
    if row["state"] == "MERGED":
        raise Refusal(f"{args.slug} is already recorded MERGED as #{row.get('pr')}")
    prs = gh_prs(row["branch"], state="merged")
    if prs is None:
        raise Refusal("could not ask the upstream repo")
    if not prs:
        raise Refusal(f"{row['branch']} has no merged pull request upstream yet")
    pr = prs[0]
    row.update({"state": "MERGED", "pr": pr["number"], "url": pr["url"], "merged": pr["mergedAt"],
                "merge_commit": (pr.get("mergeCommit") or {}).get("oid")})
    write_ledger(root, rows)
    print(f"{args.slug}: MERGED as #{pr['number']} ({pr['url']})")
    return 0


# ------------------------------------------------------------------------------------ self-test
# Every refusal above has a case here that is shown firing, plus a negative control proving the
# FORK-ONLY filter, not something else, is what keeps fork files out. All offline, in temp repos.

def _fixture(tmp):
    """An upstream repo, and a fork of it: fork-only files on the fork's main, a topic on top."""
    up, fork = tmp / "up", tmp / "fork"

    def run(where, *a):
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=f@example.invalid",
                        "-C", str(where), *a], check=True, capture_output=True)

    def write(where, rel, text, mode=None):
        f = where / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        if mode:
            f.chmod(mode)

    up.mkdir()
    run(up, "init", "-q", "-b", "main")
    write(up, "README.md", "upstream\n")
    write(up, "src/a.txt", "a1\n")
    write(up, "tools/t.sh", "#!/bin/sh\necho t\n", 0o755)
    run(up, "add", "-A")
    run(up, "update-index", "--chmod=+x", "tools/t.sh")
    run(up, "commit", "-q", "-m", "U1")
    subprocess.run(["git", "clone", "-q", str(up), str(fork)], check=True, capture_output=True)
    run(fork, "remote", "add", "upstream", str(up))
    run(fork, "fetch", "-q", "upstream")
    for rel in ("worker_log.md", "handoff.md", "AGENTS.md", ".gitattributes", "tools/upstream/x.txt"):
        write(fork, rel, "fork only\n")
    run(fork, "add", "-A")
    run(fork, "commit", "-q", "-m", "F1 fork-only files")
    run(fork, "branch", "fork-main")
    write(fork, "src/a.txt", "a1\na2\n")
    write(fork, "src/b.txt", "b\n")
    write(fork, "tools/t.sh", "#!/bin/sh\necho t2\n", 0o755)
    run(fork, "add", "-A")
    run(fork, "commit", "-q", "-m", "T1 topic")
    return up, fork, run, write


def _prepare(tmp, *extra, fork_only, slug="add-b", paths="src,tools/t.sh", title="Add b",
             message="Add b\n", body="Adds b.\n", head="HEAD"):
    (tmp / "m.txt").write_text(message)
    (tmp / "b.md").write_text(body)
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "prepare", "--offline", "--no-fetch",
         "--fork-only", str(fork_only), "--slug", slug, "--paths", paths, "--title", title,
         "--message-file", str(tmp / "m.txt"), "--body-file", str(tmp / "b.md"), "--head", head, *extra],
        cwd=tmp / "fork", capture_output=True, text=True)


def _outcome_clean(tmp, fork):
    g = lambda *a: subprocess.run(["git", "-C", str(fork), *a], capture_output=True, text=True).stdout
    branch = BRANCH_PREFIX + "add-b"
    base = g("rev-parse", "upstream/main").strip()
    if g("rev-parse", f"{branch}~1").strip() != base:
        return "the derived commit is not directly on upstream/main"
    files = set(g("diff", "--name-only", base, branch).split())
    if files != {"src/a.txt", "src/b.txt", "tools/t.sh"}:
        return f"derived files are {sorted(files)}"
    tree = g("ls-tree", "-r", "--name-only", branch)
    if any(p in tree for p in ("worker_log.md", "handoff.md", "AGENTS.md", ".gitattributes", "tools/upstream")):
        return "a fork-only file is in the derived tree"
    if not g("ls-tree", branch, "tools/t.sh").startswith("100755"):
        return "tools/t.sh lost its executable bit"
    ids = g("log", "-1", "--format=%an <%ae>|%cn <%ce>", branch).strip()
    if ids != f"{IDENTITY}|{IDENTITY}":
        return f"author|committer is {ids}"
    if g("diff", "--binary", base, branch) != g("diff", "--binary", base, "HEAD", "--", "src", "tools/t.sh"):
        return "the derived patch is not the topic's own change"
    rows = [json.loads(l) for l in (fork / LEDGER).read_text().splitlines()]
    if len(rows) != 1 or rows[0]["state"] != "PREPARED" or rows[0]["commit"] != g("rev-parse", branch).strip():
        return f"ledger is {rows}"
    if not (fork / STAGING / "add-b" / "BODY.md").exists():
        return "the PR body was not staged in the fork"
    return None


def _outcome_nothing_kept(tmp, fork):
    g = lambda *a: subprocess.run(["git", "-C", str(fork), *a], capture_output=True, text=True).stdout
    if g("branch", "--list", BRANCH_PREFIX + "*").strip():
        return "a rehearsal left a branch"
    if (fork / LEDGER).exists() or (fork / STAGING).exists():
        return "a rehearsal wrote the ledger or staged files"
    return None


def self_test():
    failed = 0
    real = HERE / "FORK-ONLY"
    scratch = Path(tempfile.mkdtemp(prefix="derive-selftest-"))
    empty = scratch / "EMPTY-FORK-ONLY"
    empty.write_text("# nothing is fork-only\n")

    def case(label, want_ok, setup=None, outcome=None, extra=(), fork_only=real, reason=None, **kw):
        """A refusal only counts if it is a REFUSED line naming `reason`: a crash, or a refusal
        for some other cause, would otherwise pass as the case it is not."""
        nonlocal failed
        tmp = Path(tempfile.mkdtemp(dir=scratch))
        up, fork, run, write = _fixture(tmp)
        if setup:
            setup(up, fork, run, write, tmp)
        proc = _prepare(tmp, *extra, fork_only=fork_only, **kw)
        detail = None
        if (proc.returncode == 0) != want_ok:
            out = (proc.stdout + proc.stderr).strip().splitlines()
            detail = f"exit {proc.returncode}: {out[-1] if out else ''}"
        elif not want_ok and not (proc.stderr.startswith("REFUSED:") and reason in proc.stderr):
            detail = f"refused for the wrong reason (wanted {reason!r}): {proc.stderr.strip()[:160]}"
        elif outcome:
            detail = outcome(tmp, fork)
        failed += bool(detail)
        print(("ok   " if not detail else "FAIL ") + label + ("" if not detail else f"  -> {detail}"))

    def edit_worker_log(up, fork, run, write, tmp):
        write(fork, "worker_log.md", "fork only\nmore\n")
        run(fork, "commit", "-q", "-am", "log")

    def upstream_moved(up, fork, run, write, tmp):
        write(up, "README.md", "upstream v2\n")
        run(up, "commit", "-q", "-am", "U2")
        run(fork, "fetch", "-q", "upstream")

    def lan_address(up, fork, run, write, tmp):
        write(fork, "src/b.txt", "b\nsee 192.168.68.185\n")
        run(fork, "commit", "-q", "-am", "ip")

    def nested_handoff(up, fork, run, write, tmp):
        write(fork, "src/handoff.md", "notes\n")
        run(fork, "add", "-A")
        run(fork, "commit", "-q", "-m", "nested")

    def failing_check(up, fork, run, write, tmp):
        write(fork, "tools/check-versions.py", "import sys\nsys.exit(1)\n", 0o755)
        run(fork, "add", "-A")
        run(fork, "update-index", "--chmod=+x", "tools/check-versions.py")
        run(fork, "commit", "-q", "-m", "a check that fails")

    def lost_x_bit(up, fork, run, write, tmp):
        write(fork, "tools/new.sh", "#!/bin/sh\n")
        run(fork, "add", "-A")
        run(fork, "update-index", "--chmod=-x", "tools/new.sh")
        run(fork, "commit", "-q", "-m", "no x bit")

    def slug_used(up, fork, run, write, tmp):
        first = _prepare(tmp, fork_only=real)
        if first.returncode != 0:
            raise RuntimeError("setup: the first prepare should have passed")

    print("passes:")
    case("  a clean topic: one commit on upstream/main, fork-only files absent, exec bit and "
         "identity right, ledger and body staged", True, outcome=_outcome_clean)
    case("  a rehearsal, keeping nothing", True, extra=("--rehearse",), outcome=_outcome_nothing_kept)
    case("  a topic that also edits worker_log.md", True, setup=edit_worker_log)
    print("refuses:")
    case("  the same topic with FORK-ONLY emptied (negative control: the filter is what kept it out)",
         False, setup=edit_worker_log, fork_only=empty, reason="fleet-convention file would cross")
    case("  a stray path outside --paths", False, paths="src", reason="--paths does not cover")
    case("  --paths naming a fork-only file", False, paths="src,tools/t.sh,handoff.md", reason="is fork-only")
    case("  a head carrying nothing but fork-only changes", False, head="fork-main", reason="nothing crosses")
    case("  a head that does not contain upstream/main", False, setup=upstream_moved,
         reason="does not contain upstream/main")
    case("  a handoff.md from a subdirectory", False, setup=nested_handoff, paths="src,tools/t.sh",
         reason="fleet-convention file would cross: src/handoff.md")
    case("  a LAN address in an added line", False, setup=lan_address, reason="src/b.txt: LAN address")
    case("  an attribution trailer in the commit message", False,
         message="Add b\n\nCo-Authored-By: Someone <x@y.z>\n", reason="message:3: attribution trailer")
    case("  a local path in the PR body", False, body="Built from /home/pacarey/x.\n", reason="body:1: local path")
    case("  a machine name in the title", False, title="Add b from dm4800", reason="title:1: login or machine name")
    case("  a fleet-internal name in the PR body", False, body="See handoff.md.\n",
         reason="body:1: fleet-internal name")
    case("  a derived tree that fails its own checks", False, setup=failing_check, paths="src,tools",
         reason="check-versions.py exited 1")
    case("  a script committed without its executable bit", False, setup=lost_x_bit, paths="src,tools",
         reason="not executable in git: tools/new.sh")
    case("  a slug already in the ledger", False, setup=slug_used, reason="already in the ledger")
    case("  a malformed slug", False, slug="Bad Slug", reason="slug 'Bad Slug'")
    shutil.rmtree(scratch, ignore_errors=True)
    print("SELF-TEST GREEN" if not failed else f"SELF-TEST RED ({failed} failed)")
    return 1 if failed else 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--slug", required=True)
    p.add_argument("--paths", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--message-file", required=True)
    p.add_argument("--body-file", required=True)
    p.add_argument("--head", default="HEAD")
    p.add_argument("--rehearse", action="store_true")
    p.add_argument("--fork-only", default=str(HERE / "FORK-ONLY"), help=argparse.SUPPRESS)
    p.add_argument("--offline", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--no-fetch", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("status")
    r = sub.add_parser("record-merged")
    r.add_argument("--slug", required=True)
    args = ap.parse_args(argv)
    try:
        return {"prepare": prepare, "status": status, "record-merged": record_merged}[args.cmd](args)
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
