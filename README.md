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

### System tray applet

A GTK3 + AppIndicator tray icon showing model status and RAM usage,
with a quick-ask box and a pause/resume control for the LLM daemon. The
pause/resume action goes through a scoped polkit rule
(`etc/polkit-1/rules.d/49-neuros-llm.rules`) so it doesn't need a
password prompt or run the tray process as root.

### Model management (`neuros-model`)

A CLI for listing, pulling, removing, switching, benchmarking, and
comparing installed models (`neuros-model list/pull/remove/switch/info/
search/benchmark/compare`). There is no GUI or tray integration for this
yet, only the CLI.

### MCP server (`neuros-mcp`)

Implements the Model Context Protocol over HTTP and JSON-RPC:
`initialize`, `tools/list`, `tools/call`, and `resources/list`, with
tools for `read_file`, `list_directory`, `run_command`, `ask_llm`,
`get_system_info`, and `git_status`. `run_command` is checked against
shell-metacharacter injection; see `tests/test_mcp.py`.

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

## Hardware requirements

| Spec    | Minimum         | Recommended            |
|---------|-----------------|-------------------------|
| RAM     | 8 GB            | 16 GB or more           |
| Storage | 20 GB           | 50 GB or more           |
| CPU     | x86_64, 4 cores | 8+ cores                |
| GPU     | not required    | NVIDIA GPU, 6GB+ VRAM   |

A quantized 7B model is roughly 4 GB. The full ISO is around 7 to 8 GB.

## Building the ISO

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
- Model switcher: the CLI is implemented and tested
  (`neuros-model list/pull/remove/switch/info/search/benchmark/compare`);
  there's no GUI or tray integration for it yet.
- GUI chat application: a local browser-based chat UI exists
  (`neuros-chat`), not a native Tauri app.
- Still open: system-wide context awareness (open apps, clipboard,
  recent files), voice input and output, a fine-tuning pipeline, and
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
./validate-build.sh
```

## Contributing

Fork the repo, create a feature branch, and submit a pull request with
a clear description of the change.

## License

GPL-3.0. See [LICENSE](LICENSE).
