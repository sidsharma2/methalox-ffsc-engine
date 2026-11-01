"""Shared journal figure style (STIX serif, PDF + PNG), same as make_figures.py."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)
plt.rcParams.update({
    "font.family": "serif", "font.serif": ["STIXGeneral"], "mathtext.fontset": "stix",
    "font.size": 9, "axes.labelsize": 9, "axes.titlesize": 9, "legend.fontsize": 8,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "axes.linewidth": 0.7, "lines.linewidth": 1.2,
    "xtick.direction": "in", "ytick.direction": "in", "xtick.top": True, "ytick.right": True,
    "savefig.dpi": 300, "figure.dpi": 110, "legend.frameon": False,
})
C = {"cu": "#b5651d", "in": "#6b6f7a", "ox": "#1f5fa8", "fu": "#a8641f", "k": "#222222", "g": "#2e7d32",
     "r": "#b71c1c", "p": "#6a3d9a"}


def save(fig, name):
    fig.savefig(FIG / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(FIG / f"{name}.png", bbox_inches="tight")
    plt.close(fig)
