"""Physics-informed neural networks for the MFE-280 nozzle, checked against analytic solutions and CFD.

Torch only (no ffsc import), so it runs from its own environment. Sources: Liang et al., Sci. Rep. 14:3822
(2024) for the 1-D nozzle recipe; Wagenaar, MSc thesis, TU Delft (2023), code wagenaartje/pinn4hcf (MIT), for
the 2-D formulation. Both are reimplemented here from their equations.
"""
