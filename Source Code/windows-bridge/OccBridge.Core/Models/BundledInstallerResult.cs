namespace OccBridge.Core.Models;

public sealed class BundledInstallerResult
{
    public required BundledInstallerDefinition Installer { get; init; }

    public bool Success { get; init; }

    public bool RequiresReboot { get; init; }

    public int ExitCode { get; init; }

    public string Message { get; init; } = string.Empty;
}
