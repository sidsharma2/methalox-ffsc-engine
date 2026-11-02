"""Replace the ambient_side entry of a p field file with a characteristic far-field pressure condition.

p is held at ambient (as the fixedValue it replaces) except where the cell next to the face flows OUT of the domain
supersonically (normal Mach Mn = u.n / sqrt(gamma p / rho) > 1), where it blends to zero gradient (Mn 0.9 -> 1.1),
because a supersonic outflow takes no boundary information from outside. With Mn < 0.9 on every face the condition
is exactly the fixedValue it replaces. gamma = 1.12504 is the I1 case's hConst gas (I2-C: 1.12600; edit ENTRY
before using it there). exprMixed (parsed at run time), because OpenFOAM refuses compiled coded conditions when run
as root, as the WSL runs are. Used for I1 run 4c on processor*/8000/p (see cfd/README.md, "Boundary conditions").
usage: python3 side_bc.py FILE [FILE ...]   (edits in place; back the files up first)
"""
import re
import sys

ENTRY = """    ambient_side
    {
        type            exprMixed;
        value           uniform 101325;
        variables
        (
            "Mn = (internalField(U) & face())/area()/sqrt(1.12504*internalField(p)/internalField(rho))"
        );
        valueExpr       "101325";
        gradientExpr    "0";
        fractionExpr    "(Mn < 0.9) ? 1 : ((Mn > 1.1) ? 0 : (1.1 - Mn)/0.2)";
    }
"""

for path in sys.argv[1:]:
    text = open(path).read()
    b = text.index("\nboundaryField")
    m = re.compile(r"^    ambient_side\s*\n    \{\n.*?^    \}\n", re.S | re.M).search(text, b)
    if not m:
        sys.exit(f"{path}: no ambient_side entry")
    if "exprMixed" in m.group(0):
        print(f"{path}: already exprMixed, left as is")
        continue
    if "fixedValue" not in m.group(0):
        sys.exit(f"{path}: ambient_side is not fixedValue, stop:\n{m.group(0)}")
    open(path, "w").write(text[:m.start()] + ENTRY + text[m.end():])
    print(f"{path}: ambient_side -> exprMixed")
