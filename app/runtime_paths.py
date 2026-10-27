"""Dedicated local storage for the desktop application."""
import os
import sys
from pathlib import Path


def data_directory() -> Path:
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent.parent / "instance"
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("Windows LOCALAPPDATA is unavailable")
    return Path(local) / "StudentScoreAnalysis"
