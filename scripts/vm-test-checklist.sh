#!/usr/bin/env bash
# vm-test-checklist.sh — Run this inside the NeurOS VM to verify everything works.
#
# Usage (inside the VM):
#   chmod +x vm-test-checklist.sh
#   ./vm-test-checklist.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASSED=0
FAILED=0
SKIPPED=0

check() {
    local desc="$1"
    local cmd="$2"
    echo -n "  [$desc] ... "
    if eval "$cmd" &>/dev/null; then
        echo -e "${GREEN}PASS${NC}"
        PASSED=$((PASSED + 1))
    else
        echo -e "${RED}FAIL${NC}"
        FAILED=$((FAILED + 1))
    fi
}

skip() {
    echo -e "  [$1] ... ${YELLOW}SKIP${NC}"
    SKIPPED=$((SKIPPED + 1))
}

echo "=============================================="
echo "  NeurOS VM Test Checklist"
echo "=============================================="
echo ""

# === Basic System ===
echo "--- Basic System ---"
check "Hostname is 'neuros'" "hostname | grep -q neuros"
check "Ubuntu 24.04" "lsb_release -rs | grep -q 24.04"
check "Zsh is installed" "command -v zsh"
check "Neovim is installed" "command -v nvim"
check "Git is installed" "command -v git"
check "Python 3 is installed" "command -v python3"

# === Ollama / LLM ===
echo ""
echo "--- Ollama / LLM ---"
check "Ollama binary exists" "command -v ollama"
check "neuros-llm service enabled" "systemctl is-enabled neuros-llm.service &>/dev/null"

if systemctl is-active neuros-llm.service &>/dev/null; then
    echo -e "  [LLM daemon running] ... ${GREEN}PASS${NC}"
    PASSED=$((PASSED + 1))

    check "Ollama API reachable" "curl -s http://localhost:11434/api/tags"
else
    echo -e "  [LLM daemon running] ... ${YELLOW}WARN (not running yet)${NC}"
    SKIPPED=$((SKIPPED + 1))
fi

# === nn CLI ===
echo ""
echo "--- nn CLI ---"
check "nn exists in PATH" "command -v nn"
check "nn --help works" "nn --help &>/dev/null"
check "nn is executable" "test -x /usr/local/bin/nn"

# === Firewall ===
echo ""
echo "--- Firewall ---"
check "UFW is installed" "command -v ufw"
if command -v ufw &>/dev/null; then
    if sudo -n ufw status 2>/dev/null | grep -q "Status: active"; then
        echo -e "  [Firewall active] ... ${GREEN}PASS${NC}"
        PASSED=$((PASSED + 1))
    else
        echo -e "  [Firewall active] ... ${RED}FAIL${NC}"
        FAILED=$((FAILED + 1))
    fi
fi

# === Telemetry Check ===
echo ""
echo "--- Telemetry ---"
for svc in apport whoopsie ubuntu-report popularity-contest; do
    if systemctl is-active "$svc.service" &>/dev/null 2>&1; then
        echo -e "  [$svc disabled] ... ${RED}FAIL (still running!)${NC}"
        FAILED=$((FAILED + 1))
    else
        echo -e "  [$svc disabled] ... ${GREEN}PASS${NC}"
        PASSED=$((PASSED + 1))
    fi
done

# === Config Files ===
echo ""
echo "--- Config Files ---"
check "llm.conf exists" "test -f ~/.config/neuros/llm.conf || test -f /etc/skel/.config/neuros/llm.conf"
check "Continue config exists" "test -f ~/.continue/config.json || test -f /etc/skel/.continue/config.json"
check "VS Code settings exist" "test -f ~/.config/Code/User/settings.json || test -f /etc/skel/.config/Code/User/settings.json"

# === VS Code ===
echo ""
echo "--- VS Code ---"
if command -v code &>/dev/null; then
    check "VS Code is installed" "code --version"
else
    skip "VS Code is installed" 
fi

# === Dev Tools ===
echo ""
echo "--- Dev Tools ---"
check "btop is installed" "command -v btop"
check "ripgrep (rg) is installed" "command -v rg"
check "fzf is installed" "command -v fzf"
check "bat is installed" "command -v bat"
check "eza is installed" "command -v eza"

# === Summary ===
echo ""
echo "=============================================="
echo "  VM Test Summary"
echo "=============================================="
echo -e "  ${GREEN}Passed:  $PASSED${NC}"
echo -e "  ${RED}Failed:  $FAILED${NC}"
echo -e "  ${YELLOW}Skipped: $SKIPPED${NC}"
echo ""

if [[ $FAILED -gt 0 ]]; then
    echo -e "${RED}Some checks failed.${NC}"
    exit 1
else
    echo -e "${GREEN}All checks passed! NeurOS is working correctly.${NC}"
    exit 0
fi
