#!/usr/bin/env bash
# validate-build.sh — Pre-build validation of all NeurOS component files.
# Run this BEFORE building the ISO to catch configuration errors early.
#
# Usage:
#   ./validate-build.sh           # Full validation
#   ./validate-build.sh --quick   # Fast check only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASSED=0
FAILED=0
WARNINGS=0

pass() {
    echo -e "  ${GREEN}[PASS]${NC} $1"
    PASSED=$((PASSED + 1))
}

fail() {
    echo -e "  ${RED}[FAIL]${NC} $1"
    FAILED=$((FAILED + 1))
}

warn() {
    echo -e "  ${YELLOW}[WARN]${NC} $1"
    WARNINGS=$((WARNINGS + 1))
}

check_executable() {
    local file="$1"
    local label="${2:-$file}"
    if [[ -x "$file" ]]; then
        pass "$label is executable"
    else
        fail "$label is NOT executable"
    fi
}

check_exists() {
    local file="$1"
    local label="${2:-$file}"
    if [[ -f "$file" ]]; then
        pass "$label exists"
    else
        fail "$label is MISSING"
    fi
}

check_content() {
    local file="$1"
    local pattern="$2"
    local label="$3"
    if grep -q "$pattern" "$file" 2>/dev/null; then
        pass "$label"
    else
        fail "$label"
    fi
}

check_not_empty() {
    local file="$1"
    local label="${2:-$file}"
    if [[ -s "$file" ]]; then
        pass "$label is not empty"
    else
        fail "$label is EMPTY"
    fi
}

echo "=============================================="
echo "  NeurOS Pre-Build Validation"
echo "=============================================="
echo ""

# === Core CLI ===
echo "--- Core CLI ---"
check_executable "config/includes.chroot/usr/local/bin/nn" "nn CLI"
check_content "config/includes.chroot/usr/local/bin/nn" "OLLAMA_URL" "nn: Ollama URL defined"
check_content "config/includes.chroot/usr/local/bin/nn" "get_system_context" "nn: system context function"
check_content "config/includes.chroot/usr/local/bin/nn" "stream_response" "nn: streaming response"
check_content "config/includes.chroot/usr/local/bin/nn" "interactive_mode" "nn: interactive mode"

check_executable "config/includes.chroot/usr/local/bin/neuros-tray" "neuros-tray"
check_content "config/includes.chroot/usr/local/bin/neuros-tray" "AppIndicator3" "tray: AppIndicator import"
check_content "config/includes.chroot/usr/local/bin/neuros-tray" "update_status" "tray: status updates"

check_executable "config/includes.chroot/usr/local/bin/neuros-welcome" "neuros-welcome"
check_content "config/includes.chroot/usr/local/bin/neuros-welcome" "Gtk.Window" "welcome: GTK window"

echo ""
echo "--- Core Tools ---"
ALL_TOOLS=(
    "neuros-chat"
    "neuros-model"
    "neuros-snippets"
    "neuros-git"
    "neuros-agent"
    "neuros-voice"
    "neuros-speak"
    "neuros-mcp"
    "neuros-code"
    "neuros-docs"
    "neuros-translate"
    "neuros-shell"
    "neuros-learn"
    "neuros-analyze"
    "neuros-watch"
    "neuros-daemon"
    "neuros-knowledge"
    "neuros-memory"
    "neuros-summarize"
    "neuros-brief"
    "neuros-docker"
    "neuros-test"
    "neuros-debug"
    "neuros-sql"
    "neuros-network"
    "neuros-security"
    "neuros-image"
    "neuros-workflow"
    "neuros-pipe"
    "neuros-batch"
    "neuros-notify"
    "neuros-schedule"
    "neuros-backup"
    "neuros-profile"
    "neuros-lint"
    "neuros-api"
    "neuros-firewall"
    "neuros-screenshot"
    "neuros-ocr"
    "neuros-template"
    "neuros-bench"
    "neuros-health"
    "neuros-config"
    "neuros-fix"
    "neuros-refactor"
    "neuros-scan"
)
for tool in "${ALL_TOOLS[@]}"; do
    TOOL_PATH="config/includes.chroot/usr/local/bin/$tool"
    if [[ -f "$TOOL_PATH" ]]; then
        check_exists "$TOOL_PATH" "$tool"
        check_content "$TOOL_PATH" "#!/usr/bin/env python3" "$tool: correct shebang"
    fi
done

check_executable "config/includes.chroot/usr/local/bin/neuros-firstboot" "neuros-firstboot"
check_content "config/includes.chroot/usr/local/bin/neuros-firstboot" "MARKER" "firstboot: done marker"

# Check zshrc has new aliases
check_content "config/includes.chroot/etc/skel/.zshrc" "nfix" "zshrc: nfix alias"
check_content "config/includes.chroot/etc/skel/.zshrc" "nhealth" "zshrc: nhealth alias"
check_content "config/includes.chroot/etc/skel/.zshrc" "nconfig" "zshrc: nconfig alias"

# === Systemd Services ===
echo ""
echo "--- Systemd Services ---"
check_exists "config/includes.chroot/etc/systemd/system/neuros-llm.service" "neuros-llm.service"
check_content "config/includes.chroot/etc/systemd/system/neuros-llm.service" "Ollama" "service: mentions Ollama"
check_content "config/includes.chroot/etc/systemd/system/neuros-llm.service" "Restart=always" "service: auto-restart"
check_content "config/includes.chroot/etc/systemd/system/neuros-llm.service" "11434" "service: correct port"

check_exists "config/includes.chroot/etc/systemd/user/neuros-firstboot.service" "firstboot user service"
check_content "config/includes.chroot/etc/systemd/user/neuros-firstboot.service" "ConditionFirstBoot" "firstboot: condition set"

# === Hooks ===
echo ""
echo "--- Build Hooks ---"
HOOKS=(
    "0100-install-ollama"
    "0200-install-vscode"
    "0300-configure-gnome"
    "0400-remove-telemetry"
    "0500-configure-system"
    "0600-install-gnome-extensions"
    "0700-install-neuros-tools"
)

for hook in "${HOOKS[@]}"; do
    HOOK_PATH="config/hooks/live/${hook}.hook.chroot"
    check_executable "$HOOK_PATH" "hook: $hook"
    check_content "$HOOK_PATH" "#!/bin/bash" "hook $hook: has shebang"
    check_content "$HOOK_PATH" "set -e" "hook $hook: has set -e"
    check_not_empty "$HOOK_PATH" "hook: $hook"
done

# Check hook content integrity
echo ""
echo "--- Hook Content Checks ---"
check_content "config/hooks/live/0100-install-ollama.hook.chroot" "ollama pull" "hook 0100: pulls model"
check_content "config/hooks/live/0200-install-vscode.hook.chroot" "install -y code" "hook 0200: installs VS Code"
check_content "config/hooks/live/0400-remove-telemetry.hook.chroot" "telemetry" "hook 0400: removes telemetry"
check_content "config/hooks/live/0500-configure-system.hook.chroot" "ufw --force enable" "hook 0500: enables UFW"
check_content "config/hooks/live/0500-configure-system.hook.chroot" "neuros-firstboot.service" "hook 0500: enables firstboot service"

# === Config Files ===
echo ""
echo "--- Config Files ---"
check_exists "config/includes.chroot/etc/skel/.config/neuros/llm.conf" "llm.conf"
check_content "config/includes.chroot/etc/skel/.config/neuros/llm.conf" "model" "llm.conf: model setting"
check_content "config/includes.chroot/etc/skel/.config/neuros/llm.conf" "11434" "llm.conf: correct port"

check_exists "config/includes.chroot/etc/skel/.continue/config.json" "continue config"
check_content "config/includes.chroot/etc/skel/.continue/config.json" "ollama" "continue: ollama provider"
check_content "config/includes.chroot/etc/skel/.continue/config.json" "mistral" "continue: mistral model"
check_content "config/includes.chroot/etc/skel/.continue/config.json" "false" "continue: telemetry off"

check_exists "config/includes.chroot/etc/skel/.zshrc" ".zshrc"
check_content "config/includes.chroot/etc/skel/.zshrc" "oh-my-zsh" "zshrc: oh-my-zsh"
check_content "config/includes.chroot/etc/skel/.zshrc" "alias ai" "zshrc: nn alias"

check_exists "config/includes.chroot/etc/skel/.config/nvim/init.vim" "nvim init.vim"
check_content "config/includes.chroot/etc/skel/.config/nvim/init.vim" "ollama" "nvim: ollama plugin"
check_content "config/includes.chroot/etc/skel/.config/nvim/init.vim" "vim.schedule" "nvim: deferred require"

check_exists "config/includes.chroot/etc/skel/.config/Code/User/settings.json" "VS Code settings"
check_content "config/includes.chroot/etc/skel/.config/Code/User/settings.json" "telemetry.telemetryLevel" "vscode: telemetry off"

# === Package Lists ===
echo ""
echo "--- Package Lists ---"
check_exists "config/package-lists/neuros.list.chroot" "neuros package list"
check_content "config/package-lists/neuros.list.chroot" "gnome-shell" "packages: gnome-shell"
check_content "config/package-lists/neuros.list.chroot" "python3-gi" "packages: python3-gi for tray"
check_content "config/package-lists/neuros.list.chroot" "neovim" "packages: neovim"

check_exists "config/package-lists/remove.list.chroot" "remove package list"
check_content "config/package-lists/remove.list.chroot" "ubuntu-report" "removals: ubuntu-report"
check_content "config/package-lists/remove.list.chroot" "whoopsie" "removals: whoopsie"

# === Build Infrastructure ===
echo ""
echo "--- Build Infrastructure ---"
check_executable "build.sh" "build.sh"
check_content "build.sh" "check_prerequisites" "build.sh: prerequisite check"
check_content "build.sh" "build_iso" "build.sh: build function"
check_content "build.sh" "run_vm_test" "build.sh: VM test function"

check_exists "Makefile" "Makefile"
check_content "Makefile" "all: build" "Makefile: all target"

check_exists "LICENSE" "LICENSE"
check_exists "README.md" "README.md"
check_content "README.md" "Hardware Requirements" "README: hardware requirements"
check_content "README.md" "Building from Source" "README: build instructions"

# === Autostart ===
echo ""
echo "--- Autostart ---"
check_exists "config/includes.chroot/etc/skel/.config/autostart/neuros-tray.desktop" "tray autostart"
check_content "config/includes.chroot/etc/skel/.config/autostart/neuros-tray.desktop" "neuros-tray" "autostart: tray exec"
check_content "config/includes.chroot/etc/skel/.config/autostart/neuros-tray.desktop" "X-GNOME-Autostart-enabled=true" "autostart: enabled"

check_exists "config/includes.chroot/etc/skel/.config/autostart/neuros-welcome.desktop" "welcome autostart"

# === Summary ===
echo ""
echo "=============================================="
echo "  Validation Summary"
echo "=============================================="
echo -e "  ${GREEN}Passed:  $PASSED${NC}"
echo -e "  ${RED}Failed:  $FAILED${NC}"
echo -e "  ${YELLOW}Warnings: $WARNINGS${NC}"
echo ""

if [[ $FAILED -gt 0 ]]; then
    echo -e "${RED}VALIDATION FAILED — $FAILED checks failed.${NC}"
    echo "Fix the FAILED checks before building the ISO."
    exit 1
else
    echo -e "${GREEN}All checks passed!${NC}"
    echo "Ready to build: ./build.sh"
    exit 0
fi
