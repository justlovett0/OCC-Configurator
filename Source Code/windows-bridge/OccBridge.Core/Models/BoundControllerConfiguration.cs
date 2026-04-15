namespace OccBridge.Core.Models;

public sealed class BoundControllerConfiguration
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

    public DateTimeOffset BoundAtUtc { get; init; } = DateTimeOffset.UtcNow;
}
