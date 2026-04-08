using OccBridge.Core.Models;

namespace OccBridge.Core.Install;

public static class BundledPrerequisiteCatalog
{
    public static IReadOnlyList<BundledInstallerDefinition> All { get; } =
    [
        new BundledInstallerDefinition
        {
            Id = "vigembus",
            DisplayName = "ViGEm Bus Driver",
            Description = "Required. Creates the virtual Xbox 360 controller used by the bridge.",
            Required = true,
            RelativeInstallerPath = Path.Combine("Prerequisites", "ViGEmBus_1.22.0.exe"),
            EmbeddedResourceName = "OccBridge.Install.Prerequisites.ViGEmBus_1.22.0.exe",
            IsMsi = false,
            Arguments = string.Empty,
        },
        new BundledInstallerDefinition
        {
            Id = "hidhide",
            DisplayName = "HidHide",
            Description = "Recommended. Hides the physical OCC Bluetooth controller from games to prevent duplicate inputs.",
            Required = false,
            RelativeInstallerPath = Path.Combine("Prerequisites", "HidHide_1.5.230.exe"),
            EmbeddedResourceName = "OccBridge.Install.Prerequisites.HidHide_1.5.230.exe",
            IsMsi = false,
            Arguments = string.Empty,
        },
    ];
}
