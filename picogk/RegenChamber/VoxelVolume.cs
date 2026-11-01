using System.Reflection;
using System.Runtime.InteropServices;
using PicoGK;

namespace RegenChamber;

/// <summary>
/// PicoGK's voxel volume without the extra memory of Voxels.CalculateProperties.
/// CalculateProperties meshes the field, re-voxelizes that mesh (to drop the
/// zero-distance voxels that booleans leave behind) and counts voxels with the
/// native Voxels_fCalculateVolume. Called on the full field it holds the field,
/// its own mesh and the mesh-to-volume work at once (~4 GB at 0.15 mm, ~11 GB
/// projected at 0.10 mm). dFromMesh does the same steps on the mesh that is
/// exported anyway, after the source field has been freed. PicoGK keeps the
/// native handles internal, so they are read by reflection.
/// </summary>
public static class VoxelVolume
{
    /// <summary>Voxel-count volume (mm^3) of the re-voxelized mesh, as in Voxels.CalculateProperties.</summary>
    public static double dFromMesh(Mesh msh)
    {
        using Voxels vox = new(msh);
        return dDirect(vox);
    }

    [DllImport(Config.strPicoGKLib, CallingConvention = CallingConvention.Cdecl, EntryPoint = "Voxels_fCalculateVolume")]
    static extern float _fCalculateVolume(LibHandle hLib, VoxHandle hVoxels);

    const BindingFlags Internal = BindingFlags.NonPublic | BindingFlags.Instance;
    static readonly FieldInfo s_libHandle = typeof(Library).GetField("hThis", Internal)
                                            ?? throw new MissingFieldException("Library.hThis");
    static readonly FieldInfo s_voxHandle = typeof(Voxels).GetField("hThis", Internal)
                                            ?? throw new MissingFieldException("Voxels.hThis");

    /// <summary>Native voxel count (mm^3) of a field as it is (counts the zero-distance voxels too).</summary>
    public static double dDirect(Voxels vox)
        => _fCalculateVolume((LibHandle)s_libHandle.GetValue(vox.lib)!,
                             (VoxHandle)s_voxHandle.GetValue(vox)!);
}
