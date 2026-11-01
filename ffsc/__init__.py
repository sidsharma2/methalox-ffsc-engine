"""Design models for a methalox full-flow staged-combustion (FFSC) rocket engine."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
G0 = 9.80665


def load_config(path=None):
    """Read the design basis YAML (defaults to config/baseline.yaml)."""
    path = Path(path) if path else ROOT / "config" / "baseline.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
