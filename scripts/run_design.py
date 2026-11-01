"""Run the baseline design point and write results/design.json, contour.csv, cooling_profile.csv."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ffsc.design import design

if __name__ == "__main__":
    design()
