namespace OccBridge.Core.Models;

public sealed class PrerequisiteStatus
{
    public required string Name { get; init; }

    public bool IsInstalled { get; init; }

    public bool IsOperational { get; init; }

    public Version? InstalledVersion { get; init; }

    public string? InstallLocation { get; init; }

    public string? Message { get; init; }
}
