#!/usr/bin/env bash
# build.sh — NeurOS ISO Build Automation
# Automates the full build pipeline from clean checkout to bootable ISO.
#
# Usage:
#   ./build.sh              # Full build
#   ./build.sh --test-vm    # Build and launch test VM
#   ./build.sh --clean      # Clean previous build artifacts
#   ./build.sh --help       # Show help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_LOG="$SCRIPT_DIR/build.log"
ISO_NAME="live-image-amd64.hybrid.iso"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[NeurOS]${NC} $1"
}

success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[!]${NC} $1"
}

error() {
    echo -e "${RED}[✗]${NC} $1"
    exit 1
}

check_prerequisites() {
    log "Checking prerequisites..."

    # Check OS
    if [[ "$(uname -s)" != "Linux" ]]; then
        error "NeurOS build requires a Linux host (Ubuntu 24.04 recommended)."
    fi

    # Check Ubuntu version
    if command -v lsb_release &>/dev/null; then
        DISTRO=$(lsb_release -is)
        VERSION=$(lsb_release -rs)
        if [[ "$DISTRO" != "Ubuntu" ]]; then
            warn "This build is designed for Ubuntu. You're running $DISTRO."
        fi
        if [[ "$VERSION" != "24.04" ]]; then
            warn "This build is tested on Ubuntu 24.04. You're running $VERSION."
        fi
    fi

    # Check for live-build
    if ! command -v lb &>/dev/null; then
        log "live-build not found. Installing..."
        sudo apt-get update
        sudo apt-get install -y live-build
        success "live-build installed."
    fi

    # Check for qemu (for VM testing)
    if ! command -v qemu-system-x86_64 &>/dev/null; then
        warn "qemu-system-x86_64 not found (optional, needed for --test-vm)."
    fi

    # Check disk space (need ~25GB free)
    AVAILABLE_GB=$(df -BG . | awk 'NR==2 {print $4}' | sed 's/G//')
    if [[ "$AVAILABLE_GB" -lt 20 ]]; then
        warn "Less than 20GB free disk space. Build may fail."
    fi

    success "All prerequisites satisfied."
}

configure_live_build() {
    log "Configuring live-build..."

    # Initialize live-build config if not already done
    if [[ ! -f "auto/config" ]]; then
        lb config \
            --distribution noble \
            --archive-areas "main restricted universe multiverse" \
            --debian-installer none \
            --memtest none \
            --binary-images iso-hybrid
        success "live-build configured."
    else
        warn "live-build config already exists. Using existing configuration."
    fi
}

verify_structure() {
    log "Verifying project structure..."

    local required=(
        "config/package-lists/neuros.list.chroot"
        "config/package-lists/remove.list.chroot"
        "config/includes.chroot/usr/local/bin/nn"
        "config/includes.chroot/usr/local/bin/neuros-tray"
        "config/includes.chroot/usr/local/bin/neuros-welcome"
        "config/includes.chroot/usr/local/bin/neuros-firstboot"
        "config/includes.chroot/usr/local/bin/neuros-chat"
        "config/includes.chroot/usr/local/bin/neuros-model"
        "config/includes.chroot/usr/local/bin/neuros-git"
        "config/includes.chroot/usr/local/bin/neuros-agent"
        "config/includes.chroot/usr/local/bin/neuros-mcp"
        "config/includes.chroot/etc/systemd/system/neuros-llm.service"
        "config/hooks/live/0100-install-ollama.hook.chroot"
        "config/hooks/live/0200-install-vscode.hook.chroot"
        "config/hooks/live/0300-configure-gnome.hook.chroot"
        "config/hooks/live/0400-remove-telemetry.hook.chroot"
        "config/hooks/live/0500-configure-system.hook.chroot"
        "config/hooks/live/0600-install-gnome-extensions.hook.chroot"
        "config/hooks/live/0700-install-neuros-tools.hook.chroot"
    )

    local missing=0
    for f in "${required[@]}"; do
        if [[ ! -f "$f" ]]; then
            error "Missing required file: $f"
            missing=1
        fi
    done

    if [[ $missing -eq 0 ]]; then
        success "Project structure verified."
    fi
}

build_iso() {
    log "Building NeurOS ISO..."

    START_TIME=$(date +%s)

    # Run live-build
    if sudo lb build 2>&1 | tee "$BUILD_LOG"; then
        END_TIME=$(date +%s)
        DURATION=$((END_TIME - START_TIME))
        MINUTES=$((DURATION / 60))
        SECONDS=$((DURATION % 60))

        if [[ -f "$ISO_NAME" ]]; then
            ISO_SIZE=$(du -h "$ISO_NAME" | cut -f1)
            success "Build complete in ${MINUTES}m ${SECONDS}s!"
            success "ISO: $ISO_NAME ($ISO_SIZE)"
        else
            error "Build completed but ISO not found at $ISO_NAME"
        fi
    else
        error "Build failed. Check $BUILD_LOG for details."
    fi
}

run_vm_test() {
    local iso_path="${1:-$ISO_NAME}"

    if [[ ! -f "$iso_path" ]]; then
        error "ISO not found: $iso_path. Build first or provide path."
    fi

    if ! command -v qemu-system-x86_64 &>/dev/null; then
        error "qemu-system-x86_64 not found. Install: sudo apt install qemu-system-x86"
    fi

    log "Launching NeurOS test VM..."
    log "Press Ctrl+Alt+G to release cursor."
    sleep 2

    qemu-system-x86_64 \
        -m 8192 \
        -smp 4 \
        -cdrom "$iso_path" \
        -boot d \
        -vga virtio \
        -display sdl \
        -name "NeurOS Test VM" \
        -enable-kvm \
        -cpu host 2>/dev/null || \
    qemu-system-x86_64 \
        -m 8192 \
        -smp 4 \
        -cdrom "$iso_path" \
        -boot d \
        -vga virtio \
        -display sdl \
        -name "NeurOS Test VM (no KVM)"
}

clean_build() {
    log "Cleaning build artifacts..."

    # Clean live-build artifacts
    if [[ -f "Makefile" ]] || [[ -d ".build" ]]; then
        sudo lb clean 2>/dev/null || true
    fi

    # Remove ISO
    rm -f "$ISO_NAME"
    rm -f "$BUILD_LOG"

    # Remove live-build generated dirs
    rm -rf cache/ 2>/dev/null || true
    rm -rf chroot/ 2>/dev/null || true
    rm -rf binary/ 2>/dev/null || true

    success "Build artifacts cleaned."
}

show_help() {
    cat << 'HELP'
NeurOS Build Automation
=======================

Usage: ./build.sh [OPTIONS]

Options:
  (none)        Full build from scratch
  --test-vm     Build and launch test VM
  --clean       Remove build artifacts
  --vm-only     Launch VM with existing ISO (skip build)
  --help        Show this help

Examples:
  ./build.sh              # Build the ISO
  ./build.sh --test-vm    # Build and test in QEMU
  ./build.sh --vm-only    # Just launch the VM

Requirements:
  - Ubuntu 24.04 host (recommended)
  - 20GB+ free disk space
  - sudo access
  - live-build (auto-installed if missing)

Output:
  live-image-amd64.hybrid.iso   (bootable ISO, ~7-8GB)
  build.log                     (full build log)
HELP
}

# === Main ===
main() {
    cd "$SCRIPT_DIR"

    case "${1:-}" in
        --help|-h)
            show_help
            exit 0
            ;;
        --clean)
            clean_build
            exit 0
            ;;
        --vm-only)
            run_vm_test "$ISO_NAME"
            exit 0
            ;;
        --test-vm)
            check_prerequisites
            verify_structure
            configure_live_build
            build_iso
            run_vm_test
            ;;
        *)
            check_prerequisites
            verify_structure
            configure_live_build
            build_iso

            echo ""
            log "To test in VM: ./build.sh --vm-only"
            log "To clean up:    ./build.sh --clean"
            ;;
    esac
}

main "$@"
