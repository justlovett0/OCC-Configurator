using OccBridge.Core.Models;

namespace OccBridge.Core.Input;

internal static class OccControllerClassifier
{
    private const int OccVendorId = 0x2E8A;
    private const int Xbox360VendorId = 0x045E;
    private const int Xbox360ProductId = 0x028E;
    private const string BleHidServiceMarker = "00001812-0000-1000-8000-00805F9B34FB";

    public static bool TryClassify(DeviceCandidate candidate, out string reason)
    {
        if (HasOccPnpIdentity(candidate, out reason))
        {
            return true;
        }

        if (HasKnownOccCompatibilityIdentity(candidate, out reason))
        {
            return true;
        }

        if (HasOccReportHeuristic(candidate, out reason))
        {
            return true;
        }

        reason = "No OCC identity matched.";
        return false;
    }

    public static bool PrefersHidParsing(DeviceCandidate candidate)
    {
        if (candidate.Backend != ControllerBackend.Hid)
        {
            return false;
        }

        return candidate.VendorId == Xbox360VendorId &&
               candidate.ProductId == Xbox360ProductId &&
               candidate.IsWireless &&
               LooksBluetoothBacked(candidate.InstanceId, candidate.DevicePath, candidate.RuntimeInstanceId);
    }

    private static bool HasOccPnpIdentity(DeviceCandidate candidate, out string reason)
    {
        var values = new[]
        {
            candidate.InstanceId,
            candidate.DevicePath,
            candidate.RuntimeInstanceId,
            candidate.SerialNumber,
            candidate.ProductName,
        };

        if (values.Any(value => ContainsOccMarker(value)))
        {
            reason = "Matched OCC marker in HID/PnP metadata.";
            return true;
        }

        if (candidate.VendorId == OccVendorId)
        {
            reason = "Matched OCC USB vendor ID.";
            return true;
        }

        reason = string.Empty;
        return false;
    }

    private static bool HasKnownOccCompatibilityIdentity(DeviceCandidate candidate, out string reason)
    {
        if (candidate.Backend is ControllerBackend.Hid or ControllerBackend.WinRtGamepad or ControllerBackend.WinRtRawGameController &&
            candidate.VendorId == Xbox360VendorId &&
            candidate.ProductId == Xbox360ProductId &&
            candidate.IsWireless &&
            LooksBluetoothBacked(candidate.InstanceId, candidate.DevicePath, candidate.RuntimeInstanceId))
        {
            reason = candidate.Backend == ControllerBackend.Hid
                ? "Matched OCC BLE guitar Xbox 360 compatibility identity over HID."
                : "Matched OCC BLE guitar Xbox 360 compatibility identity over WinRT.";
            return true;
        }

        reason = string.Empty;
        return false;
    }

    private static bool HasOccReportHeuristic(DeviceCandidate candidate, out string reason)
    {
        if (candidate.InputReportLength >= 12 &&
            candidate.ProductName.Contains("GUITAR", StringComparison.OrdinalIgnoreCase) &&
            candidate.Backend is ControllerBackend.Hid or ControllerBackend.WinRtGamepad or ControllerBackend.WinRtRawGameController)
        {
            reason = "Matched fallback OCC report-layout heuristic.";
            return true;
        }

        reason = string.Empty;
        return false;
    }

    private static bool ContainsOccMarker(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return false;
        }

        return value.Contains("OCC", StringComparison.OrdinalIgnoreCase) ||
               value.Contains("OPEN CONTROLLER", StringComparison.OrdinalIgnoreCase);
    }

    private static bool LooksBluetoothBacked(params string?[] values)
    {
        foreach (var value in values)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                continue;
            }

            if (value.Contains("BTH", StringComparison.OrdinalIgnoreCase) ||
                value.Contains("BLE", StringComparison.OrdinalIgnoreCase) ||
                value.Contains("BLUETOOTH", StringComparison.OrdinalIgnoreCase) ||
                value.Contains(BleHidServiceMarker, StringComparison.OrdinalIgnoreCase) ||
                value.Contains("{00001812-0000-1000-8000-00805f9b34fb}", StringComparison.OrdinalIgnoreCase) ||
                value.Contains("_DEV_VID&", StringComparison.OrdinalIgnoreCase) ||
                value.Contains("_LOCALMFG&", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        return false;
    }
}
