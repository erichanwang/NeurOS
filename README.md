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

Implements the Model Context Protocol over HTTP and JSON-RPC:
`initialize`, `tools/list`, `tools/call`, and `resources/list`, with
tools for `read_file`, `list_directory`, `run_command`, `ask_llm`,
`get_system_info`, and `git_status`. `run_command` is checked against
shell-metacharacter injection; see `tests/test_mcp.py`.

### Container primitive (`neuros-container`)

A from-scratch container runner built directly on `unshare(2)` and
cgroup v2, no runc/containerd/libcontainer:

```sh
neuros-container run --mem 256M --pids 64 --hostname box -- bash
neuros-container list
```

Resource limits are real cgroup v2 accounting: `--mem` sets
`memory.max` on a fresh leaf cgroup, `--pids` sets `pids.max`, and
`--cpu` sets `cpu.weight` when the controller is delegated. Because a
cgroup that already holds member processes can't enable
`subtree_control` for children (cgroup v2's "no internal process"
rule), the tool walks up from its own cgroup to the nearest ancestor
that already delegates the wanted controller, so it works from an
ordinary interactive shell without root. Verified on this machine:
a `--mem 16M` cgroup holding a process that touches 200MB of
`bytearray` keeps `memory.current` at the 16MB ceiling instead of
growing past it, and a `--pids 4` cgroup stops a 20-iteration fork
loop after 3 children (see `tests/test_container.py`).

Namespace isolation (mount, UTS, PID, IPC) needs either root or an
unprivileged user namespace; on Ubuntu 24.04+ the latter is blocked by
default for unconfined processes
(`kernel.apparmor_restrict_unprivileged_userns=1`). Without either,
`neuros-container` says so on stderr and runs the command under the
cgroup limits without namespace isolation, rather than silently
pretending to sandbox it.

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
│   │   │   ├── neuros-mcp      # MCP server
│   │   │   ├── neuros-container # namespace + cgroup container runner
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
  `tools-call`/`resources` over HTTP and JSON-RPC, verified end-to-end
  against a live Ollama instance.
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
./validate-build.sh
```

## Contributing

Fork the repo, create a feature branch, and submit a pull request with
a clear description of the change.

## License

GPL-3.0. See [LICENSE](LICENSE).
