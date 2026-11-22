"""Shim that exposes the untouched legacy code pack in scs/ as importable modules.

scs/ is read-only; its modules import each other by bare name, so its directory
must be on sys.path before they are loaded.
"""

import sys
from pathlib import Path

SCS_DIR = Path(__file__).resolve().parents[2] / "scs"
if sys.path[0] != str(SCS_DIR):
    sys.path.insert(0, str(SCS_DIR))

import step1_model
import step2_simulate
import step5_plant

__all__ = ["step1_model", "step2_simulate", "step5_plant"]
