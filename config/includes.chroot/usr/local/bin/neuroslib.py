#!/usr/bin/env python3
"""
neuroslib — Shared utility library for NeurOS tools.
All NeurOS tools import from this module for config loading,
LLM querying, encrypted storage, and file operations.

Usage (in other neuros-* tools):
    from neuroslib import load_config, query_llm, load_db, save_db

This eliminates code duplication across 70+ Neuros tools.
"""

import base64
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime

# === Paths ===
CONFIG_DIR = os.path.expanduser("~/.config/neuros")
LLM_CONF = os.path.join(CONFIG_DIR, "llm.conf")


# ═══════════════════════════════════════════════════════════════════════
# Config Loading
# ═══════════════════════════════════════════════════════════════════════

def load_config():
    """Load llm.conf settings. Returns dict with model, host, port."""
    cfg = {"model": "mistral", "host": "localhost", "port": "11434"}
    try:
        if os.path.exists(LLM_CONF):
            with open(LLM_CONF) as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        cfg[k.strip()] = v.strip()
    except Exception:
        pass
    return cfg


# ═══════════════════════════════════════════════════════════════════════
# LLM Query (Ollama)
# ═══════════════════════════════════════════════════════════════════════

def query_llm(prompt, system="You are a helpful AI assistant.", timeout=120):
    """Query the local Ollama instance. Returns response string or None."""
    config = load_config()
    try:
        import urllib.request
        url = f"http://{config['host']}:{config['port']}/api/generate"
        data = json.dumps({
            "model": config["model"],
            "prompt": prompt,
            "system": system,
            "stream": False,
        }).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("response", "").strip()
    except Exception:
        return None


def query_llm_stream(prompt, system="You are a helpful AI assistant.", timeout=120):
    """Query Ollama with streaming response. Yields tokens."""
    config = load_config()
    try:
        import urllib.request
        url = f"http://{config['host']}:{config['port']}/api/generate"
        data = json.dumps({
            "model": config["model"],
            "prompt": prompt,
            "system": system,
            "stream": True,
        }).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for line in resp:
                try:
                    token = json.loads(line).get("response", "")
                    if token:
                        yield token
                except json.JSONDecodeError:
                    continue
    except Exception:
        yield None


def is_ollama_available():
    """Check if Ollama is reachable. Returns bool."""
    config = load_config()
    try:
        import urllib.request
        url = f"http://{config['host']}:{config['port']}/api/tags"
        urllib.request.urlopen(url, timeout=5)
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════
# Database Helpers (JSON)
# ═══════════════════════════════════════════════════════════════════════

def load_db(db_path, default=None):
    """Load a JSON database file. Creates the config dir if needed.
    Bare filenames (no directory) are resolved relative to CONFIG_DIR."""
    if default is None:
        default = {}
    # Resolve bare filenames to CONFIG_DIR
    if os.path.dirname(db_path) == "":
        db_path = os.path.join(CONFIG_DIR, db_path)
    os.makedirs(os.path.dirname(db_path) or CONFIG_DIR, exist_ok=True)
    if os.path.exists(db_path):
        try:
            with open(db_path) as f:
                return json.load(f)
        except json.JSONDecodeError:
            return default
    return default


def save_db(db_path, data):
    """Save a JSON database file atomically via temp file + os.replace.
    Bare filenames (no directory) are resolved relative to CONFIG_DIR."""
    # Resolve bare filenames to CONFIG_DIR
    if os.path.dirname(db_path) == "":
        db_path = os.path.join(CONFIG_DIR, db_path)
    os.makedirs(os.path.dirname(db_path) or CONFIG_DIR, exist_ok=True)
    tmp = db_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, db_path)


# ═══════════════════════════════════════════════════════════════════════
# Encryption (AES-256-GCM with PBKDF2 fallback)
# ═══════════════════════════════════════════════════════════════════════

def get_machine_key():
    """Derive a 256-bit key from machine ID + user identity."""
    try:
        with open("/etc/machine-id") as f:
            machine_id = f.read().strip()
    except Exception:
        machine_id = "fallback-machine-id"
    user = os.getenv("USER", "unknown")
    home = os.path.expanduser("~")
    salt = f"neuros-secrets-v2:{machine_id}:{user}:{home}"
    return hashlib.pbkdf2_hmac("sha256", salt.encode(), b"neuros-secret-key", 200000, dklen=32)


def encrypt_value(plaintext, key=None):
    """Encrypt using AES-256-GCM (if cryptography is installed) or PBKDF2-XOR fallback."""
    if key is None:
        key = get_machine_key()
    # Try AES-GCM first
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = os.urandom(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
        return base64.b64encode(b"AES:" + nonce + ciphertext).decode()
    except ImportError:
        pass
    # Fallback: PBKDF2-based XOR with random salt
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", key, salt, 100000, dklen=max(len(plaintext), 32))
    encrypted = bytes(a ^ b for a, b in zip(plaintext.encode(), derived[:len(plaintext)]))
    return base64.b64encode(b"XOR:" + salt + encrypted).decode()


def decrypt_value(encrypted_b64, key=None):
    """Decrypt a value encrypted with encrypt_value."""
    if key is None:
        key = get_machine_key()
    try:
        raw = base64.b64decode(encrypted_b64)
    except Exception:
        return None

    # Check prefix
    if raw[:4] == b"AES:":
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            payload = raw[4:]
            if len(payload) > 12:
                nonce = payload[:12]
                ciphertext = payload[12:]
                aesgcm = AESGCM(key)
                return aesgcm.decrypt(nonce, ciphertext, None).decode()
        except Exception:
            pass
    elif raw[:4] == b"XOR:":
        try:
            payload = raw[4:]
            if len(payload) > 16:
                salt = payload[:16]
                encrypted = payload[16:]
                derived = hashlib.pbkdf2_hmac("sha256", key, salt, 100000, dklen=max(len(encrypted), 32))
                decrypted = bytes(a ^ b for a, b in zip(encrypted, derived[:len(encrypted)]))
                return decrypted.decode()
        except Exception:
            pass
    else:
        # Legacy XOR fallback (from v1 secrets)
        try:
            result = bytearray()
            for i, b in enumerate(raw):
                result.append(b ^ key[i % len(key)])
            return result.decode()
        except Exception:
            pass

    return None


# ═══════════════════════════════════════════════════════════════════════
# System Helpers
# ═══════════════════════════════════════════════════════════════════════

def run_cmd(args_list, sudo=False, timeout=30, capture=True):
    """Run a command safely (list args, no shell injection)."""
    cmd = (["sudo", "-n"] if sudo else []) + args_list
    try:
        result = subprocess.run(
            cmd, capture_output=capture, text=True, timeout=timeout
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", -1
    except Exception as e:
        return "", str(e), -1


def format_bytes(b):
    """Format bytes to human readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if b < 1024:
            return f"{b:.1f}{unit}"
        b /= 1024
    return f"{b:.1f}PB"


def confirm(msg="Continue? [y/N]", default_no=True):
    """Ask user for confirmation. Returns bool."""
    try:
        resp = input(f"{msg} ").strip().lower()
        return resp in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        return not default_no


# ═══════════════════════════════════════════════════════════════════════
# File Helpers
# ═══════════════════════════════════════════════════════════════════════

def read_file(path):
    """Read file content with error handling."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def write_file(path, content):
    """Write file content atomically."""
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    # Self-test
    cfg = load_config()
    print(f"Config: model={cfg['model']}, host={cfg['host']}:{cfg['port']}")
    print(f"Ollama available: {is_ollama_available()}")

    # Test encryption
    test_val = "super-secret-api-key-12345"
    enc = encrypt_value(test_val)
    dec = decrypt_value(enc)
    print(f"Encryption test: {'PASS' if dec == test_val else 'FAIL'}")
    print(f"  Encrypted: {enc[:40]}...")
    print(f"  Decrypted: {dec}")
