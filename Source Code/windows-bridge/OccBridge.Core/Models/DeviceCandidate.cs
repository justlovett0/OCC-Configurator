namespace OccBridge.Core.Models;

public sealed class DeviceCandidate
{
    public required string ProductName { get; init; }

    public required string DevicePath { get; init; }

    public string? InstanceId { get; init; }

    public string? SerialNumber { get; init; }

    public int VendorId { get; init; }

    public int ProductId { get; init; }

    public int InputReportLength { get; init; }

    public int OutputReportLength { get; init; }

    public override string ToString() => $"{ProductName} (VID {VendorId:X4}, PID {ProductId:X4})";
}
