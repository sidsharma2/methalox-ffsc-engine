#!/bin/bash
# Seed a plume case with a converged nozzle-only solution (cfd/nozzle_only.sh).
#
# The chamber and nozzle blocks of the plume mesh are the same blocks as in the nozzle-only mesh, so
# mapFields copies the converged interior exactly; the plume region keeps the 1-D initial field of
# make_case.py (exit-state column + still ambient air). The plume run then only has to develop the
# external flow instead of re-converging the low-Mach chamber as well.
#
#   bash cfd/plume_from_nozzle.sh <plume run dir> <nozzle-only run dir>
#
# Maps the latest reconstructed time of the nozzle-only run onto time 0 of the plume case.
[ -n "$WM_PROJECT_DIR" ] || . /usr/lib/openfoam/openfoam2306/etc/bashrc
set -e
DST=$(realpath "$1"); SRC=$(realpath "$2")
cd "$DST"
[ ! -d processor0 ] || { echo "$DST is already decomposed: map before the first Allrun"; exit 1; }
TS=$(cd "$SRC" && foamListTimes -latestTime | tail -1)
[ -n "$TS" ] || { echo "no reconstructed time in $SRC"; exit 1; }
cat > system/mapFieldsDict <<EOF
FoamFile { version 2.0; format ascii; class dictionary; object mapFieldsDict; }
// nozzle interior only: same inlet and wall patches, the nozzle-only outlet is the plume's exit plane
patchMap ( inlet inlet wall_chamber wall_chamber wall_bell wall_bell );
cuttingPatches ( );
EOF
mapFields "$SRC" -sourceTime "$TS" > log.mapFields 2>&1 || { echo "mapFields failed, see log.mapFields"; exit 1; }
echo "mapped $SRC time $TS onto $DST/0"
