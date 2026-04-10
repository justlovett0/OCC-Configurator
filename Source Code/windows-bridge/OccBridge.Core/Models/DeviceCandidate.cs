namespace OccBridge.Core.Models;

public sealed class DeviceCandidate
{
    public ControllerBackend Backend { get; init; } = ControllerBackend.Hid;

    public required string ProductName { get; init; }

    public required string DevicePath { get; init; }

    public string? InstanceId { get; init; }

    public string? SerialNumber { get; init; }

    public int VendorId { get; init; }

    public int ProductId { get; init; }

    public int InputReportLength { get; init; }

    public int OutputReportLength { get; init; }

    public override string ToString() => $"{ProductName} (VID {VendorId:X4}, PID {ProductId:X4}) [{GetBackendLabel()}]";

    private string GetBackendLabel() => Backend switch
    {
        ControllerBackend.Hid => "HID",
        ControllerBackend.WinRtGamepad => "Gamepad API",
        ControllerBackend.WinRtRawGameController => "Raw Game Controller API",
        _ => Backend.ToString(),
    };
}
