#!/bin/bash
# Nozzle-only continuation of a plume run (chamber + nozzle, exit plane as outlet).
#
# The nozzle exit is supersonic and the sea-level nozzle is under-expanded (p_e/p_a ~ 1.2), so no
# disturbance from the ambient region can travel upstream of the exit plane and the wall boundary
# layer is not pushed into separation. Thrust and Isp then depend on the chamber and nozzle only.
# This script keeps the cells upstream of the exit plane from a saved time of a plume run, makes the
# exit plane a supersonic outlet patch (zeroGradient p, T; inletOutlet U) and continues rhoCentralFoam
# (LTS) on ~25 % of the cells, without the plume's starting transient. About 0.25 s per iteration on
# 4 ranks against 1.4-2.0 s for the plume run.
#
#   bash cfd/nozzle_only.sh <plume run dir> <new run dir> <time> [nProcs] [endTime]
#
# Reconstructs <time> in the plume run if it is not there yet (adds files, deletes nothing).
# Re-running continues from the latest processor time of <new run dir>. PREP_ONLY=1 stops before
# the solver.
SRC=$(realpath "$1"); DST=$2; TS=$3; NP=${4:-4}; END=${5:-24000}
[ -n "$WM_PROJECT_DIR" ] || . /usr/lib/openfoam/openfoam2306/etc/bashrc
set -e
# two of these jobs can share the CPU: let the kernel place the ranks instead of pinning both to cores 0-3
MPIFLAGS="--bind-to none"; [ "$(id -u)" = 0 ] && MPIFLAGS="$MPIFLAGS --allow-run-as-root"

if [ ! -d "$DST/processor0" ]; then
    [ -d "$SRC/$TS" ] || (cd "$SRC" && reconstructPar -time "$TS" > "log.reconstructPar.$TS" 2>&1)
    mkdir -p "$DST"
    cp -r "$SRC/constant" "$SRC/system" "$SRC/case_info.json" "$DST/"
    cp -r "$SRC/$TS" "$DST/$TS"
    cd "$DST"

    # exit and throat stations, expected cell count of the internal blocks
    read -r XE XT NEXP < <(python3 - case_info.json <<'EOF'
import json, sys
m = json.load(open(sys.argv[1]))["mesh"]
n = sum(v for k, v in m["cells_by_block"].items() if "-" in k)   # station-to-station blocks
print(repr(m["x_exit"]), repr(m["x_throat"]), n)
EOF
)
    cat > system/topoSetDict.nozzle <<EOF
FoamFile { version 2.0; format ascii; class dictionary; object topoSetDict; }
// cells upstream of the exit plane, then the connected region that contains the throat axis:
// this drops the ambient cells around the outside of the nozzle
actions
(
    { name upstream; type cellSet; action new; source boxToCell; box (-100 -100 -100) ($XE 100 100); }
    { name nozzle; type cellSet; action new; source regionToCell; set upstream; insidePoints (($XT 0.002 0)); }
);
EOF
    topoSet -dict system/topoSetDict.nozzle > log.topoSet.nozzle 2>&1
    NSET=$(grep -m1 -E '^[0-9]+$' "$(find . -path '*polyMesh/sets/nozzle' | head -1)")
    if [ "$NSET" != "$NEXP" ]; then
        echo "nozzle cellSet has $NSET cells, the internal blocks have $NEXP; see log.topoSet.nozzle"; exit 1
    fi
    subsetMesh nozzle -patch outlet -overwrite > log.subsetMesh 2>&1
    checkMesh -latestTime > log.checkMesh 2>&1 || true
    grep -E "^ *cells:|Mesh OK|Failed|^ *outlet " log.checkMesh || true

    # supersonic outlet at the exit plane (the subsonic wall-layer cells take the core pressure)
    for f in p T; do foamDictionary -entry boundaryField/outlet -set "{ type zeroGradient; }" "$TS/$f" > /dev/null; done
    foamDictionary -entry boundaryField/outlet -set \
        "{ type inletOutlet; inletValue uniform (0 0 0); value uniform (0 0 0); }" "$TS/U" > /dev/null
    for f in p T U; do
        echo "outlet $f: $(foamDictionary -entry boundaryField/outlet/type -value "$TS/$f")"
    done

    # exit monitors on the outlet patch; no lip or outer wall any more
    foamDictionary -entry functions/exitMassFlow/regionType -set patch system/controlDict > /dev/null
    foamDictionary -entry functions/exitMassFlow/name -set outlet system/controlDict > /dev/null
    foamDictionary -entry functions/wallSurfaces/surfaces/lipAndOuter -remove system/controlDict > /dev/null
    foamDictionary -entry numberOfSubdomains -set "$NP" system/decomposeParDict > /dev/null
    # a failed decomposePar leaves processor*/ with only constant/, which would skip this setup on a re-run
    decomposePar -latestTime > log.decomposePar 2>&1 || { rm -rf processor*; echo "decomposePar failed, see log.decomposePar"; exit 1; }
else
    cd "$DST"
fi
[ -z "$PREP_ONLY" ] || { echo "prepared $DST (PREP_ONLY set, solver not started)"; exit 0; }

latest() { foamListTimes -processor -latestTime 2>/dev/null | tail -1; }
stage() {  # stage <n> <maxCo> <endTime>
    t=$(latest); t=${t:-0}
    if awk -v a="$t" -v b="$3" 'BEGIN{exit !(a+0 >= b+0)}'; then echo "stage $1 already done (t = $t)"; return; fi
    foamDictionary -entry maxCo -set "$2" system/controlDict > /dev/null
    foamDictionary -entry endTime -set "$3" system/controlDict > /dev/null
    echo "stage $1: maxCo $2 until $3 ($(date))"
    mpirun $MPIFLAGS -np "$NP" rhoCentralFoam -parallel > "log.rhoCentralFoam.$1" 2>&1 \
        || { echo "rhoCentralFoam failed in stage $1, see log.rhoCentralFoam.$1"; exit 1; }
}
# maxCo 0.15 as in the plume runs. At 0.3 the wall cells next to the injector face went into a numerical
# limit cycle (static p up to 43 MPa against p0 = 35 MPa, inlet mass flow swinging by +/-13 %).
stage 1 0.15 "$END"
reconstructPar -latestTime > log.reconstructPar 2>&1
echo "done ($(date))"
