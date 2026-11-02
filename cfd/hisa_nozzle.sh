#!/bin/bash
# HiSA (implicit, density-based, coupled) version of a nozzle-only case, for a solver comparison.
#
# Starts from the same saved time as the rhoCentralFoam nozzle-only run (cfd/nozzle_only.sh), so both
# solvers converge from the same state on the same 43k-cell mesh. HiSA validated-v2306 (1.9.6) is
# built into the WSL user's OpenFOAM tree; source audit in ResearchOS cfg/open_source_review.yaml.
#
#   bash cfd/hisa_nozzle.sh <nozzle-only run dir> <new run dir> <time> [nProcs] [iterations]
#   PSEUDO_CO=<start Courant number> (default 5), PREP_ONLY=1 stops before the solver.
#
# Boundary conditions that change from the rhoCentralFoam case:
#   inlet   characteristicFarfield* (non-reflecting, Riemann invariants) with the 1-D static p, T and
#           u at the inlet station as the outside state. The inflow velocity stays free, so the throat
#           sets the mass flow; p0 can land slightly off 350 bar, which the exit-plane vacuum Isp does
#           not depend on. Not characteristicPressureInletOutlet: on subsonic inflow it sets the T
#           refValue to 0, and OpenFOAM's mixedEnergy then evaluates he(p, T = 0) = division by zero
#           (FPE on the first iteration, 2026-11-01).
#   walls   characteristicWallPressure / characteristicWallTemperature (adiabatic),
#           boundaryCorrectedFixedValue U = 0; wall functions unchanged (y+ ~ 50)
#   wedges  unchanged "type wedge": libhisaFiniteVolume registers its coupled wedge (and symmetry)
#           fields under the standard type names and replaces them when it loads
#   outlet  unchanged: zeroGradient p and T, inletOutlet U (supersonic exit)
SRC=$(realpath "$1"); DST=$2; TS=$3; NP=${4:-4}; NIT=${5:-3000}
[ -n "$WM_PROJECT_DIR" ] || . /usr/lib/openfoam/openfoam2306/etc/bashrc
set -e
command -v hisa > /dev/null || { echo "hisa not found in $FOAM_USER_APPBIN"; exit 1; }
MPIFLAGS="--bind-to none"; [ "$(id -u)" = 0 ] && MPIFLAGS="$MPIFLAGS --allow-run-as-root"

if [ ! -d "$DST/processor0" ]; then
    [ -d "$SRC/$TS" ] || { echo "$SRC/$TS not found (reconstructed time needed)"; exit 1; }
    mkdir -p "$DST"
    cp -r "$SRC/constant" "$SRC/system" "$SRC/case_info.json" "$DST/"
    mkdir -p "$DST/$TS"
    for f in p T U k omega nut alphat; do cp "$SRC/$TS/$f" "$DST/$TS/"; done
    cd "$DST"
    rm -f system/topoSetDict.nozzle

    read -r PIN TIN UIN < <(python3 - case_info.json <<'EOF'
import json, sys
s = json.load(open(sys.argv[1]))["mesh"]["stations"][0]      # 1-D isentropic state at the inlet plane
print(repr(s["p"]), repr(s["T"]), repr(s["u"]))
EOF
)
    EXT="U ($UIN 0 0); p $PIN; T $TIN;"
    set_bc() { foamDictionary -entry "boundaryField/$1" -set "$2" "$TS/$3" > /dev/null; }
    # solver-written fields list every patch explicitly, and an explicit entry beats a regex key:
    # set each patch by name
    set_bc inlet "{ type characteristicFarfieldPressure; $EXT value uniform $PIN; }" p
    set_bc inlet "{ type characteristicFarfieldTemperature; $EXT value uniform $TIN; }" T
    set_bc inlet "{ type characteristicFarfieldVelocity; $EXT value uniform ($UIN 0 0); }" U
    for w in wall_chamber wall_bell; do
        set_bc $w "{ type characteristicWallPressure; value uniform $PIN; }" p
        set_bc $w "{ type characteristicWallTemperature; value uniform $TIN; }" T
        set_bc $w "{ type boundaryCorrectedFixedValue; value uniform (0 0 0); }" U
    done
    # the plume patches have 0 faces here; waveTransmissive (advective) does not accept HiSA's dualTime ddt
    for w in ambient_inlet ambient_side; do set_bc $w "{ type zeroGradient; }" p; done
    for f in p T U; do
        echo "$f: inlet $(foamDictionary -entry boundaryField/inlet/type -value $TS/$f), wall_bell" \
             "$(foamDictionary -entry boundaryField/wall_bell/type -value $TS/$f)"
    done
    echo "inlet static p $PIN Pa, T $TIN K, u $UIN m/s"

    cat > system/fvSchemes <<'EOF'
FoamFile { version 2.0; format ascii; class dictionary; location "system"; object fvSchemes; }
fluxScheme      AUSMPlusUp;
lowMachAusm     true;           // chamber at M ~ 0.2
ddtSchemes      { default bounded dualTime rPseudoDeltaT steadyState; }
gradSchemes
{
    default     faceLeastSquares linear;
    grad(k)     cellLimited Gauss linear 0.1;
    grad(omega) cellLimited Gauss linear 0.1;
}
divSchemes
{
    default         none;
    div(tauMC)      Gauss linear;
    div(phi,k)      bounded Gauss upwind phi;
    div(phi,omega)  bounded Gauss upwind phi;
}
laplacianSchemes
{
    default                 Gauss linear corrected;
    laplacian(muEff,U)      Gauss linear compact;
    laplacian(alphaEff,e)   Gauss linear compact;
}
interpolationSchemes
{
    default             linear;
    reconstruct(rho)    wVanLeer;
    reconstruct(U)      wVanLeer;
    reconstruct(T)      wVanLeer;
}
snGradSchemes   { default corrected; }
wallDist        { method meshWave; }
EOF
    cat > system/fvSolution <<'EOF'
FoamFile { version 2.0; format ascii; class dictionary; location "system"; object fvSolution; }
solvers
{
    "(k|omega|rPseudoDeltaT)(|Final)"
    {
        solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0.1; minIter 1;
    }
}
flowSolver
{
    solver  GMRES;
    GMRES
    {
        inviscidJacobian    LaxFriedrichs;
        viscousJacobian     laplacian;
        preconditioner      LUSGS;
        maxIter             20;
        nKrylov             8;
        solverTolRel        1e-1 (1e-1 1e-1 1e-1) 1e-1;
    }
}
pseudoTime
{
    // HiSA sets Co = pseudoCoNum x (first residual / current residual), within the bounds below.
    // The start state is an already developed flow, so begin at 5 instead of ramping from 0.5.
    // Smoke test (40 iterations): stable at Co 4-7 while the residual rose 30 % after the inlet and
    // wall conditions changed, so the floor is 1 to keep that transient from dragging Co to 0.1.
    pseudoTol                       1e-8 (1e-8 1e-8 1e-8) 1e-8;
    pseudoCoNum                     PSEUDO_CO_START;
    pseudoCoNumMin                  1;
    pseudoCoNumMax                  100;
    pseudoCoNumMaxIncreaseFactor    1.2;
    localTimestepping               true;
}
EOF
    sed -i "s/PSEUDO_CO_START/${PSEUDO_CO:-5}/" system/fvSolution
    foamDictionary -entry application -set hisa system/controlDict > /dev/null
    # utilities (decomposePar, reconstructPar) then build the characteristic and coupled-wedge fields
    foamDictionary -entry libs -set '( "libhisaFiniteVolume.so" )' system/controlDict > /dev/null
    foamDictionary -entry writeInterval -set 500 system/controlDict > /dev/null
    foamDictionary -entry numberOfSubdomains -set "$NP" system/decomposeParDict > /dev/null
    # a failed decomposePar leaves processor*/ with only constant/, which would skip this setup on a re-run
    decomposePar -latestTime > log.decomposePar 2>&1 || { rm -rf processor*; echo "decomposePar failed, see log.decomposePar"; exit 1; }
else
    cd "$DST"
fi
[ -z "$PREP_ONLY" ] || { echo "prepared $DST (PREP_ONLY set, solver not started)"; exit 0; }

foamDictionary -entry endTime -set $((TS + NIT)) system/controlDict > /dev/null
echo "hisa: $NIT iterations from $TS on $NP ranks ($(date))"
mpirun $MPIFLAGS -np "$NP" hisa -parallel > log.hisa 2>&1 || { echo "hisa failed, see log.hisa"; exit 1; }
reconstructPar -latestTime > log.reconstructPar 2>&1
echo "done ($(date))"
