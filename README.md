# NeurOS

A custom Ubuntu 24.04 LTS-based Linux distribution with a local LLM
(Ollama plus a small Qwen or Mistral model) built into the OS as a first
class feature: a terminal assistant, a system tray applet, editor
integrations, and an MCP server, all running against a model on
`localhost`. No cloud API, no telemetry, no account.

## Why

Most "AI in your terminal" setups mean an API key, a subscription, and
your code leaving the machine. NeurOS installs Ollama and a model at
build time, wires them into the shell, the system tray, and your editor,
and removes the telemetry packages Ubuntu ships by default. Everything
runs on `localhost:11434`.

## Features

### Terminal assistant (`nn`)

```sh
nn "how do I reverse a list in Python"
nn "what does this repo do"              # reads README + file tree
nn explain ./src/auth.py                 # reads and explains a file
nn "find the bug" ./src/auth.py          # debug a file
nn "summarize changes since last commit" # reads git diff
nn -i                                    # interactive chat mode
```

`Ctrl+Space` in a terminal opens `nn` inline. It picks up the current
directory and git branch, and can read files you point it at.

`nn` can optionally include system-wide context — the active window
title, clipboard contents, and recently modified files under `$HOME` —
in the prompt it sends to Ollama. **All three are off by default.** They
are enabled per-source in `~/.config/neuros/llm.conf` under `[context]`:

```ini
[context]
window_title = false
clipboard = false
recent_files = false
```

Set any of these to `true` to opt in. Whatever is read is only ever
included in the prompt sent to Ollama on `localhost:11434`; nothing is
sent anywhere else. Window title reads `xdotool` if installed, clipboard
reads `xclip`/`xsel` if installed, and recent files uses `find` scoped to
`$HOME` (top 3 directory levels, last 7 days, dotfiles excluded).

### System tray applet

A GTK3 + AppIndicator tray icon showing model status and RAM usage,
with a quick-ask box, a "Switch Model" submenu, and a pause/resume
control for the LLM daemon. The model submenu lists installed models
(radio items, current default checked) and switches by shelling out to
`neuros-model switch <name>` — the tray doesn't reimplement any of
`neuros-model`'s logic. The pause/resume action goes through a scoped
polkit rule (`etc/polkit-1/rules.d/49-neuros-llm.rules`) so it doesn't
need a password prompt or run the tray process as root.

### Model management (`neuros-model`)

A CLI for listing, pulling, removing, switching, benchmarking, and
comparing installed models (`neuros-model list/pull/remove/switch/info/
search/benchmark/compare`). The system tray's "Switch Model" submenu is
a thin GUI over this CLI (see above).

### MCP server (`neuros-mcp`)

Implements the Model Context Protocol over two transports: HTTP/JSON-RPC
(`neuros-mcp`) and the spec's stdio transport (`neuros-mcp --stdio`),
which is what real MCP clients (Claude Code, Claude Desktop, etc.) use
to launch a local server as a subprocess. Both transports share one
dispatcher (`dispatch_request`) for `initialize`, `notifications/
initialized`, `tools/list`, `tools/call`, `resources/list`, and
`resources/read`, with tools for `read_file`, `list_directory`,
`run_command`, `ask_llm`, `get_system_info`, and `git_status`.
`run_command` is checked against shell-metacharacter injection. The
stdio transport was verified against the official `mcp` Python SDK
client (`ClientSession` over `stdio_client`): initialize handshake,
`tools/list`, and `tools/call` all round-trip correctly. See
`tests/test_mcp.py` for the dispatcher-level tests.

### Container primitive (`neuros-container`)

A from-scratch container runner built directly on `unshare(2)` and
cgroup v2, no runc/containerd/libcontainer:

```sh  neuros-container run --mem 256M --pids 64 --hostname box -- bash
  neuros-container run --cpu-quota 50000/100000 --read-only --net -- bash
  neuros-container run --user 1000:1000 --workdir /tmp --detach --name job -- sleep 60
  neuros-container run --env DB=postgres --env DEBUG=1 -- bash
  neuros-container run --env-from-file ./prod.env -- bash
  neuros-container run --cap-drop 'CAP_(NET_RAW|SYS_PTRACE|SYS_ADMIN)' -- bash
  neuros-container list --json
  neuros-container cleanup --all          # remove empty detached cgroups + state
```

Resource limits are real cgroup v2 accounting: `--mem` sets
`memory.max` on a fresh leaf cgroup, `--pids` sets `pids.max`,
`--cpu` sets `cpu.weight`, and `--cpu-quota "MAX/PERIOD"` writes the
PETF v2 cpu.max quota (e.g. `--cpu-quota 50000/100000` caps a workload
to half of one CPU). Because a cgroup that already holds member
processes can't enable `subtree_control` for children (cgroup v2's
"no internal process" rule), the tool walks up from its own cgroup to
the nearest ancestor that already delegates the wanted controller, so
it works from an ordinary interactive shell without root. If a
controller was requested and none were delegated all the way down,
the tool prints a single stderr warning rather than silently creating
an empty cgroup.

Verified on this machine: a `--mem 16M` cgroup holding a process that
touches 200MB of `bytearray` keeps `memory.current` at the 16MB
ceiling instead of growing past it, and a `--pids 4` cgroup stops a
20-iteration fork loop after 3 children (see
`tests/test_container.py`).

Namespace isolation (mount, UTS, PID, IPC, optionally network) needs
either root or an unprivileged user namespace; on Ubuntu 24.04+ the
latter is blocked by default for unconfined processes
(`kernel.apparmor_restrict_unprivileged_userns=1`). Without either,
`neuros-container` says so on stderr and runs the command under the
cgroup limits without namespace isolation, rather than silently
pretending to sandbox it.

`--env KEY=VALUE` (repeatable) injects environment variables into
the inner workload just before exec. `--env-from-file PATH` reads a
dotenv-style file (one `KEY=VALUE` per line; `#` comments and
optional `export ` prefixes are accepted) and merges it with any
explicit `--env` flags, with explicit `--env` winning on conflict.
Either path's injection always overrides whatever was inherited
from the parent shell, so `--env DEBUG=0` really forces `DEBUG=0`
even when the caller set it to `1`.
`--cap-drop REGEX` removes every Linux capability whose name matches
the regex from the bounding set via `prctl(PR_CAPBSET_DROP)`. The
bounding set is inherited across exec, so the workload sees the
dropped state directly. The drop requires the user namespace's
`CAP_SETPCAP`; outside a userns the call returns EPERM and the
helper prints a per-capability stderr line.

Detached runs (`--detach`) leave the child running and write a JSON
state file under `/run/neuros-container/<name>.json` describing the
inner pid and cgroup path; `cleanup` reaps those that have already
exited, refusing to remove cgroups that still hold live members.
`list` walks the cgroup subtree recursively (nested `neuros-*` leaves
inside parent `neuros-*` leaves are also found) and supports a
`--json` output mode.

All model and config parsing in `nn`, `neuros-model`, and the rest
of the `neuros-*` tools delegates to the shared `neuroslib.py`, which
reads `~/.config/neuros/llm.conf` as an INI document — the
`[llm]` section owns `model`/`host`/`port`, the `[context]` section
owns the opt-in system-context flags, and additional sections round-
trip through unchanged.

### Untrusted code sandbox (`neuros-sandbox`)

A safe-runner wrapper around `neuros-container`, tuned for running
scripts produced by an LLM agent or pulled from an untrusted source.
The hardcoded defaults are the point of the tool:

```sh
echo 'print("hello agent")' | neuros-sandbox run --json
neuros-sandbox run --mem 1G --timeout 60 ./smoke.py
neuros-sandbox run --bundle ./fixture.tar.gz --dry-run       # show argv
neuros-sandbox run --json ./post.sh                          # envelope
```

Every safe-mode invocation always passes `--net`, `--read-only`,
`--mem 256M`, `--pids 64`, `--cpu-quota 50000` (50% of one CPU),
and `--cap-drop 'CAP_(NET_RAW|SYS_ADMIN|SYS_PTRACE|SETUID|SETPCAP|
MAC_ADMIN|DAC_OVERRIDE|LINUX_IMMUTABLE|SYS_CHROOT|SYS_RAWIO|
SYS_RESOURCE)'` to the underlying `neuros-container run`. The
cap-drop baseline is the load-bearing piece of the default safety
posture and persists under `--unsafe` as well; only `--cap-drop-keep
REGEX` (active only under `--unsafe`) replaces it for untrusted
work that genuinely needs broader capabilities. Override regexes
are pre-validated with `re.compile` so a malformed pattern fails
at the wrapper, not deep inside the kernel-bridge ctypes call when
the primitive would otherwise reject it. The host environment is
scrubbed to a minimal `PATH` so `ANTHROPIC_API_KEY`,
`HOME`, and other secrets don't leak into the worker's process env.
Scripts are always piped to `python3 -u -` via stdin — no temp
files on the host, no script path visible via `/proc/<pid>/cmdline`.
A wall-clock watchdog (`--timeout`, default 30 s) SIGKILLs the
container on expiry and the wrapper exits 124 with `timeout_hit:
true` in the JSON envelope. `--json` emits one line of structured
output (`exit_code`, `stdout`, `stderr`, `wall_clock_ms`,
`timeout_hit`, `peak_mem_estimate`), suitable for orchestrator
consumption; in default human mode stdout/stderr pass through and a
single `[neuros-sandbox] exit=… wall_ms=… timeout_hit=…` trailer is
written to stderr. `peak_mem_estimate` is best-effort: the primitive
auto-cleans the cgroup on non-detached exit, so the `memory.peak`
file is often gone by the time we read it. For forensic-grade memory
accounting, run with `--unsafe --cap-drop-keep ''` plus an explicit
`--detach` and read `memory.peak` from `<cgroup>/` before invoking
`neuros-container cleanup <name>`.

`--unsafe` opts in to disabling `--net` and `--read-only` (with
`--cap-drop-keep REGEX` for replacing — not relaxing — the set of
dropped capabilities). `--bundle TAR` extracts a tarball into a
fresh tmp directory and uses it as the container's rootfs;
absolute paths and `..` traversal inside the tar are rejected at
extraction time. Tests in `tests/test_sandbox.py` mock
`subprocess.run` so no kernel cgroup delegation is required to
verify the argv shape, env scrubbing, JSON envelope, timeout
behavior, and bundle cleanup.

### Regression benchmark harness (`neuros-bench`)

A small driver that shells out to `neuros-sandbox run --json` with
a registry of canned workloads (CPU-bound recursion, memory growth,
regex compile, fork pressure, ctypes-bridge syscalls, file IO, JSON
parse, string ops), parses each envelope, and produces a metrics
JSON file that CI can diff against a stored baseline:

```sh
neuros-bench list                              # show the workload suite
neuros-bench batch --out baseline.json         # capture a baseline run
neuros-bench run mem_grow --out single.json    # run one workload
neuros-bench compare baseline.json candidate.json
  # exit 0 within tolerance, exit 1 on a row beyond threshold
```

The compare subcommand emits a grep-friendly table on stdout
(`workload`, `baseline_ms`, `candidate_ms`, `wall_pct`, `base_mem`,
`cand_mem`, `mem_pct`, `status=OK|REGRESSION|NEW|DROPPED`) and a
single verdict line on stderr. Tolerance defaults are 15% wall and
25% peak-mem; tighten via `--tolerance-wall-pct` / `--tolerance-mem-pct`
in CI. Each workload runs under `--timeout 60` (configurable) with
the sandbox's default `--mem 256M` and `--pids 64` so an unbounded
regression in any one workload can't stall the batch.Tests in `tests/test_bench.py` mock `subprocess.run` and let the workspace
run a regression check with no kernel/cgroup dependency.

### Runbook verifier (`neuros-runbook`)

A small assertion-driven runner that drives `neuros-sandbox` from a
JSON runbook file. Each step has a `script`, optional per-step
`limits` (mem/pids/timeout/cpu_quota), and an `expect` block that can
assert `exit_code`, regex-match `stdout`/`stderr`, or forbid
`timeout_hit=true`. Step verdicts roll up into a JSON envelope (with
`--json`) or a grep-friendly table on stdout (default). Exit 0 if
every step passes, 1 on any failure; `--only-violations` filters the
human table to just the failed rows.

```sh
neuros-runbook run ./runbooks/smoke.json
neuros-runbook run --only-violations ./runbooks/prod-checks.json
neuros-runbook run --json ./runbooks/regression.json | jq '.steps[] | select(.passed==false)'
```

Example runbook:

```json
[
  {"name": "imports-stdlib",
   "script": "import sys; print(sys.version_info[:2])",
   "expect": {"exit_code": 0, "stdout_matches": "^\\(3, [0-9]+\\)$"}},
  {"name": "network-blocked",
   "script": "import socket; socket.gethostbyname('example.com'); print('UP')",
   "limits": {"timeout": 5},
   "expect": {"exit_code": "any", "timeout_forbidden": false}},
  {"name": "no-tracebacks",
   "script": "import sys; sys.exit(0)",
   "expect": {"exit_code": 0, "stderr_matches": "^$"}}
]
```

The runbook parser pre-validates each `expect.*_matches` regex at
load time so a malformed pattern fails loudly when the runbook is
loaded, not at the assertion site. Tests in `tests/test_runbook.py`
mock `subprocess.run` for full coverage without kernel/cgroup
dependency.

### Declarative security policy (`neuros-policy`)

Hardened defaults are good until you need to *prove* which defaults
applied to a given run. `neuros-policy` is the place that
information lives: a JSON manifest naming a profile (`strict`,
`moderate`, `permissive`), declaring per-profile capability drops,
naming memory / PID / CPU-quota / timeout bounds, and pinning the
allowlist of env vars that may pass through to the container. The
three subcommands compose like this:

* `neuros-policy validate ./policy.json` — schema + bounds check.
  Bounds are conservative: mem 16K-1G, pids 1-4096, cpu_quota
  1000-1_000_000 (microseconds / 100ms CFS period), timeout
  1-3600s. Profile names must match `[a-z][a-z0-9_-]*`, cap names
  `^CAP_[A-Z_]+$`, env-allowlist names `^[A-Z][A-Z0-9_]*$`. Exits
  0 on success, 1 on any violation, 2 on malformed input.
* `neuros-policy check ./policy.json --envelope ./envelope.json` —
  parse a `neuros-sandbox --json` envelope and reconcile its
  `wall_clock_ms`, `peak_mem_estimate`, and `timeout_hit` against
  the policy's bounds. Exits 0 when the run conformed, 1 on a
  violation (printed to stderr in the form `[severity] rule:
  observed X, expected Y`), 2 on bad input.
* `neuros-policy transpile ./policy.json --profile strict` — emit
  the `neuros-sandbox --unsafe ...` argv fragment that realises
  the policy. A profile with an empty cap list transpiles to
  `--cap-drop '^_NEVER_MATCH_$'` so nothing is dropped, which is
  almost always a bug — but if you really mean it, the surface
  is unambiguous.

Sample manifest bundled in `tests/test_policy.py` (`_good_policy`).
Add `--json` to `validate` / `check` to emit a single-line envelope
that composes with the bench + runbook JSON surfaces downstream.

### Offline envelope diagnostics (`neuros-replay`)

When a `neuros-sandbox --json` envelope looks wrong, the typical
follow-up is either "how wrong?" (diff against an earlier good
run) or "what does this mean?" (humanize the metrics). Both are
now a single tool, no shell-out to `python3 -c`:

* `neuros-replay diff <a> <b>` — per-field regression verdict.
  Tolerances default to 10% wall-clock / 20% peak-mem (tighter
  than bench's 15%/25% because this is a single observation, not
  a batch aggregate). Each violation surfaces as a single grep-
  friendly rule string on stderr; `--json` emits a structured
  envelope with `ok`, `wall_clock_pct_delta`, `peak_mem_pct_
  delta`, `rule_violations`, and the tolerances that were
  applied. Exit 0 on conformant, 1 on any rule violation, 2 on
  bad input.
* `neuros-replay explain <envelope>` — sinkable one-line summary
  like `exit=0 wall=0ms peak=n/a timeout=False stdout_bytes=0
  stderr_bytes=0`. The exact numbers depend on the envelope,
  but the field order is fixed. Add `--json` for the structured
  equivalent with `neuros_replay_version`. Designed for CI grep.
* `neuros-replay extract <envelope> --stream stdout|stderr|both`
  — dump the embedded `stdout` / `stderr` payloads so standard
  host tools (`grep`, `jq`, `less`) read them without JSON
  escaping. The `both` stream mode inserts a single
  `===STDERR===` separator line so a downstream parser can tell
  the two streams apart without re-mapping field names.

`neuros-replay` is purely offline: it consumes envelopes the
other tools emit and never re-runs a workload. For replay-with-
execute, use `neuros-bench run <workload> --json` and pipe the
envelope into `neuros-replay`. Tests in `tests/test_replay.py`
exercise every branch without subprocess shell-out.

### Envelope-agnostic verifier (`neuros-verify`)

All five emitter tools (sandbox, bench, runbook, policy, replay)
produce a JSON envelope, but their shapes diverge. `neuros-verify`
is the single tool that reads *any* of them, auto-detects the
shape, and emits a normalized `verdict=PASS|FAIL` line so a CI
gate only needs one consumer in its pipeline:

* Kind detection is by version key first (`neuros_bench_version`
  / `neuros_policy_version` / `neuros_replay_version`) and by
  structural fingerprint second (`exit_code`+`wall_clock_ms`+
  `timeout_hit` => sandbox; `runbook_path`+`steps` => runbook).
  First match wins; unrecognized is treated as `FAIL` with the
  top-level keys listed for triage.
* Per-kind rules:
  - Sandbox envelope needs `--policy <path>` — the policy's
    `check_envelope_against_policy` is loaded via runtime
    `compile()+exec()` of the on-disk neuros-policy script
    (`mod.__file__` is set explicitly so the runtime loader can
    find the manifest). A defensive `hasattr` check turns a
    silent AttributeError later into a loud failure now if the
    policy tool ever renames its public verify names.
  - Bench metrics without `--bench-baseline` degrades to a
    crash check (every run's `exit_code == 0`). With
    `--bench-baseline`, each per-workload run is diffed against
    the baseline using the same tolerances as
    `neuros-bench compare` (15% wall / 25% mem).
  - Policy and replay verdicts are passed through `env["ok"]`;
    the downstream tool's `errors` / `rule_violations` lists are
    carried as the violations this tool reports.
  - Runbook envelopes get a structural smoke check (every step
    has `name` + `ok`). Step-level assertion semantics live in
    `neuros-runbook` itself.
* Multiple input files are **AND-merged**: any single failure
  fails the overall run.
* Text output mode prints a per-file `verdict=… source=…
  file=… violations=N` line (deterministic field order) plus
  a final `source=aggregate` line. `--quiet` suppresses per-
  file lines; only the aggregate remains. `--json` emits a
  single-line envelope with `{ok, aggregate, parts[],
  neuros_verify_version}` shaped like the other tools' machine
  output.

Exit codes: `0` all conformant; `1` any rule violation or
unrecognized envelope; `2` bad input (missing file, malformed
JSON, root not an object).

Tests in `tests/test_verify.py` cover all five kinds, the
unknown-envelope path, every dispatch surface (text, `--json`,
`--quiet`, multi-file AND-merge, bench-with-baseline), and the
runtime sandbox+policy integration end-to-end via a tempdir-
mounted manifest.

### Code completion

VS Code ships with Continue.dev pre-installed, pointed at local Ollama.
Neovim ships with ollama.nvim pre-configured. Neither needs an API key
or a network connection.

### Privacy hardening

`ubuntu-report`, `apport`, `whoopsie`, and `popularity-contest` are
removed at build time. VS Code telemetry is disabled globally. UFW is
enabled with a default-deny incoming policy. All inference happens on
`localhost:11434`; nothing about your prompts or files leaves the
machine.

### Desktop

GNOME 46 with a dark theme, zsh with oh-my-zsh (git, docker, fzf,
autosuggestions plugins), Neovim with LSP and fzf, and btop/ripgrep/bat/
eza pre-installed.

## Hardware Requirements

| Spec    | Minimum         | Recommended            |
|---------|-----------------|-------------------------|
| RAM     | 8 GB            | 16 GB or more           |
| Storage | 20 GB           | 50 GB or more           |
| CPU     | x86_64, 4 cores | 8+ cores                |
| GPU     | not required    | NVIDIA GPU, 6GB+ VRAM   |

A quantized 7B model is roughly 4 GB. The full ISO is around 7 to 8 GB.

## Benchmarks

Real numbers from `neuros-model benchmark`, run against a live Ollama
0.x instance on the prompt "Explain quantum computing in one paragraph.":

| Model          | Size   | Speed (tok/s) | Hardware                          |
|----------------|--------|---------------|------------------------------------|
| qwen2.5:0.5b   | 397 MB | 18–19.5       | 16-core x86_64 CPU, no GPU (3 runs) |
| llama3.2:1b    | 1.3 GB | 7.7–8.2       | 16-core x86_64 CPU, no GPU (3 runs) |

These were measured in a CPU-only sandboxed VM, which is not the
hardware NeurOS recommends (see [Hardware Requirements](#hardware-requirements));
a GPU with 6GB+ VRAM will be substantially faster. Reproduce with:

```sh
neuros-model pull qwen2.5:0.5b
neuros-model benchmark qwen2.5:0.5b
```

The default model (`mistral`, 7B) was not benchmarked here — pulling it
requires several GB and minutes of download that weren't available in
this environment. Run the command above with `mistral` on real target
hardware to get that number.

## Building from Source (the ISO)

```sh
sudo apt update
sudo apt install -y live-build qemu-system-x86 ovmf
git clone https://github.com/erichanwang/NeurOS.git
cd NeurOS
sudo lb build 2>&1 | tee build.log
```

This takes 20 to 40 minutes and produces `live-image-amd64.hybrid.iso`.
Before building, `validate-build.sh` checks the repo for the kind of
mistake that's invisible until boot, most notably scripts and hooks
losing their executable bit in a fresh git clone (git tracks the mode
bit, and a mis-tracked script silently fails to run on first boot even
though the build itself succeeds).

```sh
./validate-build.sh
```

Test the ISO in a VM before writing it to real hardware:

```sh
qemu-system-x86_64 -m 8192 -smp 4 -cdrom live-image-amd64.hybrid.iso \
  -boot d -vga virtio -display sdl
```

### Reproducibility

"Reproducible" here means **pinned-inputs reproducibility**: every build
input that could otherwise drift (package versions, third-party
installers, GitHub release tarballs) is pinned to an explicit version or
commit, so the same commit of this repo installs the same software on
every rebuild. It does **not** mean bit-identical ISO output — timestamps
embedded by `mksquashfs`/`xorriso`, filesystem inode ordering, and
initramfs generation are not currently pinned or normalized, and would
need to be (via `SOURCE_DATE_EPOCH`, sorted file ordering, etc.) to make
that stronger claim. That's a separate, larger effort from pinning what
gets installed, and hasn't been done here.

Along the way, `build.sh`'s `lb config` call was also missing
`--mode ubuntu`. Without it, live-build defaults to Debian's own mirrors
for an Ubuntu suite name, and `lb config`/debootstrap would fail on a
genuinely clean checkout since Debian's archive has no `noble` suite.
That's fixed alongside the pinning below, verified with `lb config`
exiting 0 against `--mode ubuntu` in a clean container.

What's pinned, and how:

- **~60 apt packages** (`config/package-lists/neuros.list.chroot`): no
  per-package `=version` pins. Instead, `build.sh` points `lb config` at
  a fixed Ubuntu archive snapshot (`SNAPSHOT_TS` in `build.sh`, via
  [snapshot.ubuntu.com](https://snapshot.ubuntu.com)) for the bootstrap
  and chroot mirrors, so `apt` resolves the exact same package versions
  on every build regardless of what's since changed in the live Ubuntu
  archive. This was chosen over pinning every package to `=version`
  because a snapshot pins the whole dependency graph at once and doesn't
  need updating package-by-package as the archive rotates; Canonical
  commits to keeping snapshots available for at least 2 years. The
  shipped ISO's own `/etc/apt/sources.list` (`--mirror-binary`) is
  deliberately left on the regular live Ubuntu mirrors, not the
  snapshot, so a running NeurOS system keeps getting real security
  updates after install.
- **oh-my-zsh** (`0500-configure-system.hook.chroot`): pinned to a
  specific commit SHA instead of the `master` branch tip.
- **VS Code and the Continue.dev extension**
  (`0200-install-vscode.hook.chroot`): pinned to a specific `code`
  package version (Microsoft's apt repo keeps a long version history, so
  this doesn't go stale) and a specific Continue.dev marketplace version.
- **GNOME extensions** (`0600-install-gnome-extensions.hook.chroot`):
  blur-my-shell and caffeine are downloaded from a GitHub archive URL
  pinned to a commit SHA (not a tag name, which can be moved) for the
  same release each build.
- **Ollama installer** (`0100-install-ollama.hook.chroot`): the
  installer script is fetched from a pinned commit (the `v0.32.5` tag)
  instead of the floating `ollama.com/install.sh`, and `OLLAMA_VERSION`
  pins the installed binary itself.

While verifying package resolution, `config/package-lists/neuros.list.chroot`
was also found to list `also-utils`, which isn't a real package (the
intended package is `alsa-utils`); this would have failed `apt-get
install` regardless of pinning, so it's fixed alongside this work.

**Known gap, not fixed here:** `ollama pull mistral` still pulls
whatever the `mistral` tag in Ollama's library currently resolves to —
that tag can move to a different quantization over time. Pinning it to a
manifest digest (`mistral@sha256:...`) is possible in principle, but
verifying the digest reference actually works requires an `ollama pull`
of the full ~4GB model, which this environment intentionally does not
do. Left as a documented gap rather than shipped unverified.

**What was verified, and how:** `lb config` (with `--mode ubuntu` and the
pinned snapshot mirrors) was run in a clean `ubuntu:24.04` Docker
container and exits 0. `apt-get install --dry-run` against the pinned
snapshot for every package in `neuros.list.chroot` was run in the same
container and resolves cleanly (exit 0, no dry-run conflicts). All
pinned commit SHAs/tags/versions above were confirmed to resolve via the
GitHub API and package repositories at the time of pinning. What was
**not** verified: an actual `lb build` (needs 20GB+ disk and privileged
chroot/mount this environment doesn't have), and the `ollama pull` /
GNOME extension downloads were not executed end-to-end inside a real
chroot (only their URLs were confirmed to resolve and serve the expected
content).

## Project structure

```
NeurOS/
├── config/
│   ├── hooks/live/
│   │   ├── 0100-install-ollama.hook.chroot
│   │   ├── 0200-install-vscode.hook.chroot
│   │   ├── 0300-configure-gnome.hook.chroot
│   │   ├── 0400-remove-telemetry.hook.chroot
│   │   └── 0500-configure-system.hook.chroot
│   ├── includes.chroot/
│   │   ├── usr/local/bin/
│   │   │   ├── nn              # terminal assistant CLI
│   │   │   ├── neuros-tray     # system tray applet
│   │   │   ├── neuros-model    # model manager CLI
│   │   │   ├── neuros-mcp      # MCP server  │   │   │   ├── neuros-container # namespace + cgroup container runner
  │   │   │   ├── neuros-sandbox  # safe-runner wrapper for untrusted scripts
  │   │   │   ├── neuros-welcome  # first-boot welcome screen
  │   │   │   └── ...             # 70+ additional neuros-* utilities
│   │   ├── etc/systemd/system/
│   │   │   └── neuros-llm.service
│   │   ├── etc/polkit-1/rules.d/
│   │   │   └── 49-neuros-llm.rules
│   │   └── etc/skel/
│   │       ├── .zshrc
│   │       ├── .config/neuros/llm.conf
│   │       ├── .config/nvim/init.vim
│   │       └── .continue/config.json
│   └── package-lists/
│       ├── neuros.list.chroot
│       └── remove.list.chroot
├── tests/
└── README.md
```

## Tech stack

Ubuntu 24.04 LTS, GNOME 46, Ollama, a quantized 7B model by default, a
Python 3 terminal assistant, a Python 3 + GTK3 + AppIndicator tray
applet, and `live-build` for the ISO itself.

## What NeurOS is not

It isn't a wrapper around a cloud API; every model call stays on
`localhost`. It isn't a chatbot you open in a browser tab, though
`neuros-chat` provides an optional local browser UI on port 11435. It
doesn't train models, only runs inference on them. It targets x86_64
only; there's no ARM build.

## Roadmap

MVP (all present and covered by `validate-build.sh` and the test suite):
bootable ISO, Ollama with a default model pre-installed, the `nn`
terminal assistant, the system tray applet, VS Code and Neovim
integration, and privacy hardening.

Past MVP:
- MCP server: done. `neuros-mcp` implements `initialize`/`tools-list`/
  `tools-call`/`resources` over both HTTP/JSON-RPC and the MCP stdio
  transport (`--stdio`), verified end-to-end against a live Ollama
  instance and, for stdio, against the official `mcp` Python SDK
  client. Only 6 tools are exposed through MCP function-calling; the
  other ~80 `neuros-*` CLIs are standalone tools a user (or another
  agent via `run_command`) invokes directly, not entries in an LLM
  tool-call table.
- Model switcher: done, CLI and tray. `neuros-model` implements
  `list/pull/remove/switch/info/search/benchmark/compare`, and the
  system tray now has a "Switch Model" submenu that shells out to
  `neuros-model switch` rather than reimplementing it.
- System-wide context awareness: done, opt-in. `nn` can include the
  active window title, clipboard contents, and recently modified files
  under `$HOME` in its prompts, each gated behind its own `false`-by-
  default setting in `~/.config/neuros/llm.conf`'s `[context]` section.
  Nothing is transmitted anywhere but the local Ollama prompt.
- GUI chat application: a local browser-based chat UI exists
  (`neuros-chat`), not a native Tauri app.
- Container primitive: done. `neuros-container` runs a command under a
  real cgroup v2 leaf (memory/pids/cpu limits) and, given root or an
  unprivileged user namespace, Linux namespace isolation, without
  runc/containerd. See `tests/test_container.py` for the measured
  memory-cap and pids-cap enforcement.
- Still open: voice input and output, a fine-tuning pipeline, and
  ARM/CUDA builds.

Building and booting the actual ISO requires a full Ubuntu 24.04 host
with `live-build`, which this repo's automated checks don't attempt;
`validate-build.sh` and the Python test suite cover everything that can
be verified without producing and booting an image.

## Testing

```sh
python3 tests/test_nn.py
python3 tests/test_autofix.py
python3 tests/test_model.py
python3 tests/test_mcp.py
python3 tests/test_container.py
python3 tests/test_sandbox.py
./validate-build.sh
```

## Contributing

Fork the repo, create a feature branch, and submit a pull request with
a clear description of the change.

## License

GPL-3.0. See [LICENSE](LICENSE).
