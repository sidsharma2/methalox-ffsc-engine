#!/bin/bash
# Inviscid (Euler) rerun of a nozzle-only case, on the same mesh: the fair reference for a PINN with no boundary
# layer, and the difference from the RANS run splits the nozzle loss into its 2-D and viscous parts.
#
# Copies a saved time of a nozzle-only run, then sets slip walls, laminar with mu = 0 (rhoCentralFoam then takes its
# inviscid path) and continues LTS at the same maxCo. The RANS field is a good start: only the wall layer has to relax.
#
#   bash cfd/euler_nozzle.sh <nozzle run dir> <new run dir> <time> [nProcs] [endTime]
#
# Adds files in <new run dir> only. Re-running continues from the latest processor time. PREP_ONLY=1 stops before
# the solver.
SRC=$(realpath "$1"); DST=$2; TS=$3; NP=${4:-4}; END=${5:-44000}
[ -n "$WM_PROJECT_DIR" ] || . /usr/lib/openfoam/openfoam2306/etc/bashrc
set -e
MPIFLAGS="--bind-to none"; [ "$(id -u)" = 0 ] && MPIFLAGS="$MPIFLAGS --allow-run-as-root"

if [ ! -d "$DST/processor0" ]; then
    mkdir -p "$DST"
    cp -r "$SRC/constant" "$SRC/system" "$SRC/case_info.json" "$DST/"
    cp -r "$SRC/$TS" "$DST/$TS"
    cd "$DST"
    for w in wall_chamber wall_bell lip wall_outer; do
        foamDictionary -entry "boundaryField/$w" -set "{ type slip; }" "$TS/U" > /dev/null
    done
    rm -f "$TS/k" "$TS/omega" "$TS/nut" "$TS/alphat" "$TS/yPlus"
    foamDictionary -entry simulationType -set laminar constant/turbulenceProperties > /dev/null
    foamDictionary -entry mixture/transport/As -set 0 constant/thermophysicalProperties > /dev/null
    # these need a turbulence model or a viscous stress
    foamDictionary -entry functions/yPlus -remove system/controlDict > /dev/null
    foamDictionary -entry functions/innerWallForces -remove system/controlDict > /dev/null
    foamDictionary -entry numberOfSubdomains -set "$NP" system/decomposeParDict > /dev/null
    decomposePar -latestTime > log.decomposePar 2>&1 || { rm -rf processor*; echo "decomposePar failed, see log.decomposePar"; exit 1; }
else
    cd "$DST"
fi
[ -z "$PREP_ONLY" ] || { echo "prepared $DST (PREP_ONLY set, solver not started)"; exit 0; }

foamDictionary -entry maxCo -set 0.15 system/controlDict > /dev/null
foamDictionary -entry endTime -set "$END" system/controlDict > /dev/null
echo "rhoCentralFoam Euler to $END ($(date))"
mpirun $MPIFLAGS -np "$NP" rhoCentralFoam -parallel > log.rhoCentralFoam 2>&1 \
    || { echo "rhoCentralFoam failed, see log.rhoCentralFoam"; exit 1; }
reconstructPar -latestTime > log.reconstructPar 2>&1
echo "done ($(date))"
