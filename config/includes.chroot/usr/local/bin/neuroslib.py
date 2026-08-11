#!/usr/bin/env python3
"""
neuroslib — Shared utility library for NeurOS tools.
All NeurOS tools import from this module for config loading,
LLM querying, encrypted storage, and file operations.

Usage (in other neuros-* tools):
    from neuroslib import load_config, get_default_model, get_context_config,
                            query_llm, load_db, save_db

This eliminates code duplication across 70+ Neuros tools.
"""

import base64
import configparser
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

# === Defaults ===
DEFAULT_MODEL = "mistral"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = "11434"

# Opt-in context sources. Every source defaults to False (off).
DEFAULT_CONTEXT_SOURCES = frozenset({"window_title", "clipboard", "recent_files"})

# Truthy string values for boolean coercion in llm.conf.
_TRUTHY = frozenset({"true", "1", "yes", "on"})


# ═══════════════════════════════════════════════════════════════════════
# Config Loading
# ═══════════════════════════════════════════════════════════════════════

def _parse_bool(text):
    if text is None:
        return False
    return text.strip().lower() in _TRUTHY


def _strip_quotes(text):
    """Drop one pair of surrounding matching single/double quotes
    from a configparser value. configparser preserves quotation verbatim;
    the previous naive key=value loop stripped quotes so existing
    llm.conf files (most of which write ``model = "mistral"``) still
    round-trip identically under the new parser."""
    if text is None:
        return None
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        return text[1:-1].strip()
    return text


def _read_parser(path):
    """Return a configparser.RawConfigParser with interpolation off
    (we use '=' in model names like 'qwen2.5:7b' that would otherwise
    confuse interpolators). Returns a defaults-only parser if the
    file is missing, unreadable, or empty.

    The previous naive parser happily consumed flat ``key = value``
    files written without a section header. configparser does not —
    it raises ``MissingSectionHeaderError``. To preserve back-compat
    with existing llm.conf files in the wild, we detect the no-section
    case and wrap the content in a synthetic ``[llm]`` block before
    handing it to configparser."""
    parser = configparser.RawConfigParser(
        interpolation=None,
        allow_no_value=True,
        inline_comment_prefixes=("#",),
    )
    # Default fallbacks; overridden by values present in the file.
    parser.add_section("llm")
    parser.set("llm", "model", DEFAULT_MODEL)
    parser.set("llm", "host", DEFAULT_HOST)
    parser.set("llm", "port", DEFAULT_PORT)

    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
        except (OSError, UnicodeDecodeError):
            return parser
        try:
            if raw.lstrip().startswith("["):
                parser.read_string(raw)
            else:
                parser.read_string("[llm]\n" + raw)
        except configparser.Error:
            return parser
    return parser


def load_config(path=None):
    """Load llm.conf as a flat dict with section-prefixed keys (e.g.
    'llm.model', 'context.window_title'). When ``path`` is None the
    default ``LLM_CONF`` is read. A missing or unreadable file returns
    defaults — callers don't need to guard. Quoted string values are
    unquoted on the way out so files written by the old naive parser
    (``model = "mistral"``) still round-trip identically under
    configparser, which preserves quotes verbatim."""
    parser = _read_parser(path or LLM_CONF)
    flat = {
        "llm.model": _strip_quotes(parser.get("llm", "model", fallback=DEFAULT_MODEL)),
        "llm.host": _strip_quotes(parser.get("llm", "host", fallback=DEFAULT_HOST)),
        "llm.port": _strip_quotes(parser.get("llm", "port", fallback=DEFAULT_PORT)),
    }
    # Always include every known context source at False so callers
    # don't need to guard for missing keys; absent [context] section
    # is a valid configuration state, not a malformed one.
    for key in DEFAULT_CONTEXT_SOURCES:
        flat[f"context.{key}"] = _parse_bool(
            parser.get("context", key, fallback=None)
        )
    for section in parser.sections():
        if section in ("llm", "context"):
            continue
        for key, value in parser.items(section):
            flat[f"{section}.{key}"] = _strip_quotes(value)
    return flat


def get_default_model(path=None):
    """Return the configured default model, falling back to DEFAULT_MODEL."""
    cfg = load_config(path)
    model = cfg.get("llm.model", DEFAULT_MODEL).strip().strip('"').strip("'")
    return model or DEFAULT_MODEL


def get_context_config(path=None):
    """Return the dict of opt-in system-context sources, all False by
    default. See the [context] section of llm.conf."""
    cfg = load_config(path)
    return {
        source: bool(cfg.get(f"context.{source}", False))
        for source in DEFAULT_CONTEXT_SOURCES
    }


def set_default_model(name, path=None):
    """Persist a new default model in llm.conf under [llm]. Creates the
    file and parent directories if needed. Existing lines in [llm] are
    preserved; only the ``model`` key is overwritten. The write goes
    through a ``.tmp`` + ``os.replace`` so a crash mid-write leaves
    either the previous file or the new file, never a half-written
    one — and the ``.tmp`` is cleaned up on failure."""
    config_path = path or LLM_CONF
    parser = _read_parser(config_path)
    if not parser.has_section("llm"):
        parser.add_section("llm")
    parser.set("llm", "model", name)

    target_dir = os.path.dirname(config_path) or CONFIG_DIR
    os.makedirs(target_dir, exist_ok=True)
    tmp = config_path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            parser.write(f)
        os.replace(tmp, config_path)
    except Exception:
        # ``parser.write(f)`` raising mid-write would leave the tmp
        # file behind; unlink it so the user's config dir doesn't
        # accumulate orphan .tmp files.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
