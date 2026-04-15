namespace OccBridge.Core.Models;

public sealed class DeviceCandidate
{
    public ControllerBackend Backend { get; init; } = ControllerBackend.Hid;

    public required string ProductName { get; init; }

    public required string DevicePath { get; init; }

    public string? InstanceId { get; init; }

    public string? RuntimeInstanceId { get; init; }

    public string? SerialNumber { get; init; }

    public int VendorId { get; init; }

    public int ProductId { get; init; }

    public int InputReportLength { get; init; }

    public int OutputReportLength { get; init; }

    public bool IsWireless { get; init; }

    public bool IsOccController { get; init; }

    public string? OccDetectionReason { get; init; }

    public override string ToString()
    {
        var occLabel = IsOccController ? "OCC" : "Other";
        return $"{ProductName} (VID {VendorId:X4}, PID {ProductId:X4}) [{GetBackendLabel()} | {occLabel}]";
    }

    private string GetBackendLabel() => Backend switch
    {
        ControllerBackend.Hid => "HID",
        ControllerBackend.WinRtGamepad => "Gamepad API",
        ControllerBackend.WinRtRawGameController => "Raw Game Controller API",
        _ => Backend.ToString(),
    };
}
