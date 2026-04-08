namespace OccBridge.Core.Models;

public sealed class AppConfiguration
{
    public bool AutoStartAtLogon { get; set; } = true;

    public bool HidePhysicalController { get; set; } = true;

    public bool StartMinimizedToTray { get; set; } = true;

    public BoundControllerConfiguration? BoundController { get; set; }

    public static AppConfiguration CreateDefault() => new();
}
