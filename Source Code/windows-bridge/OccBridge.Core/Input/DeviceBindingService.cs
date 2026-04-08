using HidSharp;
using Nefarius.Utilities.DeviceManagement.PnP;
using OccBridge.Core.Models;

namespace OccBridge.Core.Input;

public sealed class DeviceBindingService
{
    public IReadOnlyList<DeviceCandidate> GetCandidates()
    {
        return DeviceList.Local
            .GetHidDevices()
            .Where(device => device.GetMaxInputReportLength() >= 12)
            .Select(ToCandidate)
            .Where(candidate => !string.IsNullOrWhiteSpace(candidate.ProductName))
            .OrderBy(candidate => candidate.ProductName, StringComparer.OrdinalIgnoreCase)
            .ThenBy(candidate => candidate.VendorId)
            .ThenBy(candidate => candidate.ProductId)
            .ToList();
    }

    public BoundControllerConfiguration Bind(DeviceCandidate candidate) => new()
    {
        ProductName = candidate.ProductName,
        DevicePath = candidate.DevicePath,
        InstanceId = candidate.InstanceId,
        SerialNumber = candidate.SerialNumber,
        VendorId = candidate.VendorId,
        ProductId = candidate.ProductId,
        InputReportLength = candidate.InputReportLength,
    };

    public DeviceCandidate? ResolveBoundDevice(BoundControllerConfiguration configuration)
    {
        var candidates = GetCandidates();

        return candidates.FirstOrDefault(candidate =>
                   !string.IsNullOrWhiteSpace(configuration.InstanceId) &&
                   string.Equals(candidate.InstanceId, configuration.InstanceId, StringComparison.OrdinalIgnoreCase))
               ?? candidates.FirstOrDefault(candidate =>
                   string.Equals(candidate.DevicePath, configuration.DevicePath, StringComparison.OrdinalIgnoreCase))
               ?? candidates.FirstOrDefault(candidate =>
                   candidate.VendorId == configuration.VendorId &&
                   candidate.ProductId == configuration.ProductId &&
                   string.Equals(candidate.ProductName, configuration.ProductName, StringComparison.OrdinalIgnoreCase));
    }

    private static DeviceCandidate ToCandidate(HidDevice device)
    {
        string? instanceId = null;

        try
        {
            instanceId = PnPDevice.GetInstanceIdFromInterfaceId(device.DevicePath);
        }
        catch
        {
            instanceId = null;
        }

        var productName = SafeGet(device.GetProductName) ??
                          SafeGet(device.GetFriendlyName) ??
                          "Unnamed HID Device";

        return new DeviceCandidate
        {
            ProductName = productName,
            DevicePath = device.DevicePath,
            InstanceId = instanceId,
            SerialNumber = SafeGet(device.GetSerialNumber),
            VendorId = device.VendorID,
            ProductId = device.ProductID,
            InputReportLength = device.GetMaxInputReportLength(),
            OutputReportLength = device.GetMaxOutputReportLength(),
        };
    }

    private static string? SafeGet(Func<string?> getter)
    {
        try
        {
            return getter();
        }
        catch
        {
            return null;
        }
    }
}
