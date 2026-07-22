#!/usr/bin/env python3
"""
generate-wallpaper.py — Generate the NeurOS wallpaper as an SVG.
Creates a minimal, dark-themed wallpaper with the NeurOS brain icon.
Can be converted to PNG with: rsvg-convert -o neuros.png neuros.svg
"""

import sys
import os

# Project root is parent of scripts/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "config", "includes.chroot", "usr", "share", "backgrounds")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "neuros.svg")

WALLPAPER_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" width="1920" height="1080">
  <defs>
    <radialGradient id="bg" cx="50%" cy="50%" r="70%">
      <stop offset="0%" stop-color="#1a1a2e"/>
      <stop offset="100%" stop-color="#0a0a15"/>
    </radialGradient>
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#6c5ce7"/>
      <stop offset="100%" stop-color="#a29bfe"/>
    </linearGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>

  <!-- Background -->
  <rect width="1920" height="1080" fill="url(#bg)"/>

  <!-- Subtle grid pattern -->
  <pattern id="grid" width="60" height="60" patternUnits="userSpaceOnUse">
    <path d="M 60 0 L 0 0 0 60" fill="none" stroke="#ffffff" stroke-opacity="0.03" stroke-width="0.5"/>
  </pattern>
  <rect width="1920" height="1080" fill="url(#grid)"/>

  <!-- Center brain icon (stylized) -->
  <g transform="translate(960, 500)" filter="url(#glow)">
    <!-- Brain outline - stylized neurons logo -->
    <path d="
      M -60,-40
      C -80,-60 -100,-30 -95,0
      C -90,30 -70,50 -50,60
      C -30,70 -10,65 -5,55
      C 0,45 -10,40 -20,45
      C -30,50 -50,45 -55,30
      C -60,15 -50,-5 -40,-15
      C -30,-25 -20,-30 -15,-20
      C -10,-10 -15,0 -20,5
      M 0,-50
      C 0,-70 20,-70 30,-55
      C 35,-45 30,-25 25,-15
      C 20,-5 10,0 0,-5
      C -10,-10 -15,-20 -10,-30
      M 15,-20
      C 25,-10 45,-5 55,15
      C 65,35 60,55 50,60
      C 40,65 25,60 20,50
      C 15,40 20,35 30,40
      C 40,45 50,40 50,25
      C 50,10 40,0 30,-5
      C 20,-10 10,-10 15,-20
      M -20,-40
      C -30,-50 -50,-45 -55,-30
      C -60,-15 -50,5 -40,15
      C -30,25 -20,25 -15,15
      M 40,-40
      C 45,-50 55,-45 60,-30
      C 65,-15 55,5 45,15
      C 40,20 35,20 30,10
    " fill="none" stroke="url(#accent)" stroke-width="3" stroke-linecap="round"/>

    <!-- Neural connection nodes -->
    <circle cx="-40" cy="-15" r="4" fill="#a29bfe"/>
    <circle cx="-5" cy="-45" r="4" fill="#a29bfe"/>
    <circle cx="45" cy="-20" r="4" fill="#a29bfe"/>
    <circle cx="-50" cy="40" r="3" fill="#6c5ce7"/>
    <circle cx="50" cy="40" r="3" fill="#6c5ce7"/>
    <circle cx="0" cy="-50" r="5" fill="#a29bfe" stroke="#a29bfe" stroke-width="1"/>
  </g>

  <!-- NeurOS text -->
  <text x="960" y="600" text-anchor="middle"
        font-family="Ubuntu, sans-serif"
        font-size="48" font-weight="bold"
        fill="url(#accent)"
        filter="url(#glow)">
    NeurOS
  </text>
  <text x="960" y="640" text-anchor="middle"
        font-family="Ubuntu, sans-serif"
        font-size="18"
        fill="#8888aa"
        opacity="0.7">
    Linux with a brain. Fully local. Fully yours.
  </text>
</svg>
'''


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(OUTPUT_FILE, 'w') as f:
        f.write(WALLPAPER_SVG)

    print(f"Wallpaper generated: {OUTPUT_FILE}")
    print(f"Convert to PNG: rsvg-convert -o {os.path.join(OUTPUT_DIR, 'neuros.png')} {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
