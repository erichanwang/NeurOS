# 🧠 NeurOS

**Linux with a brain. Fully local. Fully yours.**

NeurOS is a custom Ubuntu 24.04 LTS-based Linux distribution with a local LLM (Ollama + Mistral 7B) baked in as a first-class OS feature. Not a chatbot you open in a browser. Not a cloud API you pay per token. An AI that lives on your machine, knows your system, and is accessible everywhere — terminal, IDE, system tray.

> **Your AI, your hardware, your data. Nothing leaves the machine.**

---

## Why NeurOS?

| Traditional AI Setup | NeurOS |
|----------------------|--------|
| Cloud API sends your code to external servers | 100% local — your data stays on your machine |
| Manual setup of Ollama, models, configs | Pre-installed, pre-configured, zero setup |
| AI feels bolted-on, separate from the OS | AI is a first-class OS feature — terminal, IDE, tray |
| Telemetry, accounts, subscriptions required | No telemetry. No accounts. Free and open source. |

---

## Features

### 🖥️ Terminal Assistant (`nn`)
Press `Ctrl+Space` or type `nn "your question"` in any terminal. The AI knows your current directory, git branch, and can read files you point it to.

```bash
nn "how do I reverse a list in Python"
nn "what does this repo do"                    # reads README + file tree
nn explain ./src/auth.py                       # reads and explains a file
nn "find the bug" ./src/auth.py                # debug a file
nn "summarize changes since last commit"       # reads git diff
nn -i                                          # interactive chat mode
```

### 🧩 System Tray Applet
Click the brain icon in your GNOME panel for:
- Model status and RAM usage at a glance
- Quick Ask — type a question without opening terminal
- Pause/Resume the LLM daemon
- Launch terminal assistant

### 📝 Code Completion
- **VS Code**: [Continue.dev](https://www.continue.dev/) pre-installed, pointing to local Ollama
- **Neovim**: [ollama.nvim](https://github.com/nomnivore/ollama.nvim) pre-configured
- No API keys, no internet, no telemetry

### 🛡️ Privacy by Default
- No telemetry: `ubuntu-report`, `apport`, `whoopsie`, `popularity-contest` all removed
- UFW firewall enabled (default deny incoming)
- VS Code telemetry disabled globally
- All LLM inference runs on `localhost:11434` only
- No cloud accounts, no opt-in prompts, no data collection

### 🎨 Developer-Ready Desktop
- GNOME 46 with dark theme
- Zsh + Oh-My-Zsh with plugins (git, docker, fzf, autosuggestions)
- Neovim with LSP, fzf, and Ollama integration
- btop, ripgrep, bat, eza pre-installed
- Custom keyboard shortcuts for AI features

---

## Hardware Requirements

| Spec | Minimum | Recommended |
|------|---------|-------------|
| RAM | 8 GB | 16 GB+ |
| Storage | 20 GB | 50 GB+ |
| CPU | x86_64, 4 cores | 8+ cores |
| GPU | Not required (CPU inference) | NVIDIA GPU w/ 6GB+ VRAM |

> **Note:** Mistral 7B (quantized) is ~4 GB. The ISO is ~7-8 GB total.

---

## Quick Start

### 1. Download the ISO
Download the latest ISO from [GitHub Releases](https://github.com/neuros/neuros/releases).

### 2. Flash to USB

```bash
# Linux
sudo dd if=live-image-amd64.hybrid.iso of=/dev/sdX bs=4M status=progress

# Windows / macOS
# Use balenaEtcher or Rufus
```

### 3. Boot and Go
Boot from USB, and you're ready:
```bash
nn "hello world"                # Ask the local AI
nn -i                           # Interactive chat
code .                          # VS Code with AI autocomplete
```

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Space` (in terminal) | Open `nn` inline mode |
| `Super+A` | Quick Ask from system tray |
| `Super+Shift+A` | Pause / Resume LLM daemon |

---

## Architecture

```
┌─────────────────────────────────────────┐
│                 NeurOS                   │
│  ┌───────────────────────────────────┐  │
│  │         GNOME 46 Desktop           │  │
│  │  ┌─────────┐  ┌────────────────┐  │  │
│  │  │ System  │  │ Terminal (nn)   │  │  │
│  │  │ Tray    │  │ Ctrl+Space      │  │  │
│  │  └────┬────┘  └───────┬────────┘  │  │
│  └───────┼───────────────┼───────────┘  │
│          │               │               │
│  ┌───────┴───────────────┴───────────┐  │
│  │        neuros-llm.service          │  │
│  │    Ollama @ localhost:11434        │  │
│  │    Model: Mistral 7B (quantized)   │  │
│  └────────────────┬──────────────────┘  │
│                   │                      │
│  ┌────────────────┴──────────────────┐  │
│  │   IDE Integration                  │  │
│  │   VS Code + Continue.dev            │  │
│  │   Neovim + ollama.nvim              │  │
│  └───────────────────────────────────┘  │
│                                          │
│  UFW Firewall  │  No Telemetry  │  Zsh  │
└─────────────────────────────────────────┘
```

---

## Building from Source

### Prerequisites
- Ubuntu 24.04 host (or VM)
- 20 GB free disk space
- Internet connection (for package downloads)

### Build Steps

```bash
# Install build tools
sudo apt update
sudo apt install -y live-build qemu-system-x86 ovmf

# Clone the repo
git clone https://github.com/neuros/neuros.git
cd neuros

# Build the ISO (20-40 minutes)
sudo lb build 2>&1 | tee build.log
```

The ISO will be at `live-image-amd64.hybrid.iso`.

### Test in VM

```bash
qemu-system-x86_64 \
  -m 8192 \
  -smp 4 \
  -cdrom live-image-amd64.hybrid.iso \
  -boot d \
  -vga virtio \
  -display sdl
```

---

## Project Structure

```
neuros/
├── config/
│   ├── hooks/live/
│   │   ├── 0100-install-ollama.hook.chroot     # Install Ollama + pull Mistral
│   │   ├── 0200-install-vscode.hook.chroot     # VS Code + Continue.dev
│   │   ├── 0300-configure-gnome.hook.chroot    # GNOME dark theme, dock, fonts
│   │   ├── 0400-remove-telemetry.hook.chroot   # Privacy hardening
│   │   └── 0500-configure-system.hook.chroot   # UFW, zsh, hostname
│   ├── includes.chroot/
│   │   ├── usr/local/bin/
│   │   │   ├── nn              # Terminal assistant CLI
│   │   │   ├── neuros-tray     # System tray applet
│   │   │   └── neuros-welcome  # First-boot welcome screen
│   │   ├── etc/systemd/system/
│   │   │   └── neuros-llm.service  # Ollama daemon service
│   │   └── etc/skel/
│   │       ├── .zshrc                  # Zsh config with nn aliases
│   │       ├── .config/neuros/llm.conf # NeurOS config
│   │       ├── .config/nvim/init.vim   # Neovim + ollama.nvim
│   │       ├── .continue/config.json   # Continue.dev config
│   │       └── .config/autostart/      # GNOME autostart entries
│   └── package-lists/
│       ├── neuros.list.chroot      # Packages to install
│       └── remove.list.chroot      # Telemetry packages to remove
├── docs/
│   ├── PRD.md
│   ├── MVP.md
│   └── INSTRUCTIONS.md
└── README.md
```

---

## Tech Stack

- **Base OS**: Ubuntu 24.04 LTS (Noble Numbat)
- **Desktop**: GNOME 46
- **LLM Runtime**: Ollama
- **Default Model**: Mistral 7B (quantized, ~4 GB)
- **Terminal Assistant**: Python 3 CLI
- **System Tray**: Python 3 + GTK3 + AppIndicator
- **Config**: TOML / JSON / systemd unit files
- **Build**: live-build

---

## What NeurOS Is NOT

- ❌ A cloud API wrapper — everything runs locally
- ❌ A chatbot app — AI is integrated at the OS level
- ❌ A model trainer — for inference only
- ❌ A replacement for ChatGPT/Claude for everything — 7B models are capable but not GPT-4 class
- ❌ An Android/ARM distro — x86_64 only for MVP

---

## Roadmap

### MVP (Current)
- [x] Bootable ISO based on Ubuntu 24.04
- [x] Ollama + Mistral 7B pre-installed
- [x] `nn` terminal assistant with file/context awareness
- [x] System tray applet
- [x] VS Code + Continue.dev integration
- [x] Neovim + ollama.nvim integration
- [x] Privacy hardening (no telemetry, UFW enabled)

### Post-MVP
- [ ] GUI chat application (Tauri)
- [ ] System-wide context (open apps, clipboard, recent files)
- [ ] Voice input / output
- [ ] Model switcher UI
- [ ] Fine-tuning pipeline
- [ ] MCP (Model Context Protocol) server
- [ ] ARM / NVIDIA CUDA builds

---

## Contributing

NeurOS is open source. Contributions welcome!

1. Fork the repo
2. Create a feature branch
3. Make your changes
4. Submit a PR with a clear description

---

## License

GPL-3.0 — see [LICENSE](LICENSE) for details.
