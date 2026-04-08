namespace OccBridge.Core.Models;

public sealed class BridgeRuntimeStatus
{
    public bool IsRunning { get; init; }

    public bool PrerequisitesReady { get; init; }

    public bool VirtualControllerConnected { get; init; }

    public bool HideApplied { get; init; }

    public string StatusText { get; init; } = "Idle";

    public string? ActiveDeviceName { get; init; }

    public string? LastError { get; init; }

    public static BridgeRuntimeStatus Idle(string? message = null) => new()
    {
        StatusText = message ?? "Idle",
    };
}
