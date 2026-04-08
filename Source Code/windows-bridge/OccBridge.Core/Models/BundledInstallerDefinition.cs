namespace OccBridge.Core.Models;

public sealed class BundledInstallerDefinition
{
    public required string Id { get; init; }

    public required string DisplayName { get; init; }

    public required string Description { get; init; }

    public required bool Required { get; init; }

    public required string RelativeInstallerPath { get; init; }

    public required string EmbeddedResourceName { get; init; }

    public string Arguments { get; init; } = string.Empty;

    public bool IsMsi { get; init; }
}
