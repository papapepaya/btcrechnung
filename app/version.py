"""Versionsinfo: Git-Tag wenn verfügbar, sonst Fallback (für Frozen-Builds)."""
import os
import subprocess

FALLBACK_VERSION = "1.6.0"


def get_version() -> str:
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        tag = subprocess.check_output(
            ["git", "-C", here, "describe", "--tags", "--abbrev=0"],
            stderr=subprocess.DEVNULL, timeout=5).decode().strip()
        if tag.startswith("v"):
            tag = tag[1:]
        if tag:
            return tag
    except Exception:
        pass
    return FALLBACK_VERSION
