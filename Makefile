# NeurOS Makefile
# Automates the ISO build, VM testing, and cleanup pipeline.
#
# Usage:
#   make              Build the ISO
#   make build        Same as above
#   make test-vm      Build ISO and launch test VM
#   make vm           Launch VM with existing ISO
#   make clean        Remove build artifacts
#   make deep-clean   Full clean including live-build config
#   make wallpaper    Generate wallpaper SVG
#   make help         Show this help

.PHONY: all build test-vm vm clean deep-clean wallpaper help

ISO := live-image-amd64.hybrid.iso
BUILD_LOG := build.log
WALLPAPER_SVG := config/includes.chroot/usr/share/backgrounds/neuros.svg
WALLPAPER_PNG := config/includes.chroot/usr/share/backgrounds/neuros.png

all: build

build:
	@chmod +x build.sh
	@./build.sh

test-vm: build
	@./build.sh --test-vm

vm:
	@./build.sh --vm-only

wallpaper:
	@python3 scripts/generate-wallpaper.py
	@echo "Converting SVG to PNG..."
	@if command -v rsvg-convert &>/dev/null; then \
		rsvg-convert -w 1920 -h 1080 -o $(WALLPAPER_PNG) $(WALLPAPER_SVG); \
		echo "  Wallpaper: $(WALLPAPER_PNG)"; \
	else \
		echo "  rsvg-convert not found. Install: sudo apt install librsvg2-bin"; \
	fi

clean:
	@./build.sh --clean

deep-clean: clean
	@echo "Removing live-build configuration..."
	@rm -rf auto/ 2>/dev/null || true
	@echo "Deep clean complete."

help:
	@echo "NeurOS Build Targets:"
	@echo ""
	@echo "  make               Build the ISO"
	@echo "  make build         Same as above"
	@echo "  make test-vm       Build and launch test VM"
	@echo "  make vm            Launch VM with existing ISO"
	@echo "  make wallpaper     Generate wallpaper SVG/PNG"
	@echo "  make clean         Remove build artifacts"
	@echo "  make deep-clean    Full clean (including lb config)"
	@echo "  make help          Show this help"
