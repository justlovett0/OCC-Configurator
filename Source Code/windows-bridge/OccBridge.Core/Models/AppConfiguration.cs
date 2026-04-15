namespace OccBridge.Core.Models;

public sealed class AppConfiguration
{
    public bool AutoStartAtLogon { get; set; } = true;

    public bool HidePhysicalController { get; set; } = true;

    public bool AutoScanBtGuitarAlways { get; set; }

    public bool StartMinimizedToTray { get; set; } = true;

    public bool ControllerBoundByUser { get; set; }

    public BoundControllerConfiguration? BoundController { get; set; }

    public static AppConfiguration CreateDefault() => new();
}
