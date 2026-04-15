using HidSharp;
using Nefarius.Utilities.DeviceManagement.PnP;
using OccBridge.Core.Diagnostics;
using OccBridge.Core.Models;
using Windows.Gaming.Input;

namespace OccBridge.Core.Input;

public sealed class DeviceBindingService
{
    private const string BleHidServiceMarker = "00001812-0000-1000-8000-00805F9B34FB";
    private readonly FileLog? _log;

    public DeviceBindingService(FileLog? log = null)
    {
        _log = log;
    }

    public IReadOnlyList<DeviceCandidate> GetCandidates()
    {
        var hidCandidates = DeviceList.Local
            .GetHidDevices()
            .Select(TryCreateCandidate)
            .Where(candidate => candidate is not null)
            .Select(candidate => candidate!)
            .Where(candidate => candidate.InputReportLength >= 12)
            .ToList();

        var gamepadCandidates = Gamepad.Gamepads
            .Select(gamepad => TryCreateGamepadCandidate(gamepad, hidCandidates))
            .Where(candidate => candidate is not null)
            .Select(candidate => candidate!)
            .ToList();

        var rawGameControllerCandidates = RawGameController.RawGameControllers
            .Select(controller => TryCreateRawGameControllerCandidate(controller, hidCandidates))
            .Where(candidate => candidate is not null)
            .Select(candidate => candidate!)
            .ToList();

        var candidates = hidCandidates
            .Concat(gamepadCandidates)
            .Concat(rawGameControllerCandidates)
            .Where(candidate => candidate.IsOccController)
            .Where(candidate => !string.IsNullOrWhiteSpace(candidate.ProductName))
            .GroupBy(GetCandidateIdentity, StringComparer.OrdinalIgnoreCase)
            .Select(group => group.OrderBy(GetBackendPriority).First())
            .OrderBy(candidate => candidate.ProductName, StringComparer.OrdinalIgnoreCase)
            .ThenBy(candidate => candidate.VendorId)
            .ThenBy(candidate => candidate.ProductId)
            .ToList();

        _log?.Info($"Bind scan found {hidCandidates.Count} HID, {gamepadCandidates.Count} Gamepad API, {rawGameControllerCandidates.Count} Raw Game Controller API candidates; {candidates.Count} unique total.");
        foreach (var candidate in candidates)
        {
            _log?.Info(
                $"Bind candidate: {candidate.ProductName} [{candidate.Backend}] VID={candidate.VendorId:X4} PID={candidate.ProductId:X4} RuntimeId={candidate.RuntimeInstanceId ?? candidate.DevicePath} PnP={candidate.InstanceId ?? "<none>"} OCC={candidate.IsOccController} Reason={candidate.OccDetectionReason ?? "<none>"}");
        }

        return candidates;
    }

    public BoundControllerConfiguration Bind(DeviceCandidate candidate) => new()
    {
        Backend = candidate.Backend,
        ProductName = candidate.ProductName,
        DevicePath = candidate.DevicePath,
        InstanceId = candidate.InstanceId,
        RuntimeInstanceId = candidate.RuntimeInstanceId,
        SerialNumber = candidate.SerialNumber,
        VendorId = candidate.VendorId,
        ProductId = candidate.ProductId,
        InputReportLength = candidate.InputReportLength,
    };

    public DeviceCandidate? ResolveBoundDevice(BoundControllerConfiguration configuration)
    {
        var candidates = GetCandidates();

        var directMatch = candidates.FirstOrDefault(candidate =>
                   candidate.Backend == configuration.Backend &&
                   !string.IsNullOrWhiteSpace(configuration.InstanceId) &&
                   string.Equals(candidate.InstanceId, configuration.InstanceId, StringComparison.OrdinalIgnoreCase))
               ?? candidates.FirstOrDefault(candidate =>
                   candidate.Backend == configuration.Backend &&
                   !string.IsNullOrWhiteSpace(configuration.RuntimeInstanceId) &&
                   string.Equals(candidate.RuntimeInstanceId, configuration.RuntimeInstanceId, StringComparison.OrdinalIgnoreCase))
               ?? candidates.FirstOrDefault(candidate =>
                   candidate.Backend == configuration.Backend &&
                   string.Equals(candidate.DevicePath, configuration.DevicePath, StringComparison.OrdinalIgnoreCase))
               ?? candidates.FirstOrDefault(candidate =>
                   candidate.Backend == configuration.Backend &&
                   candidate.VendorId == configuration.VendorId &&
                   candidate.ProductId == configuration.ProductId &&
                   string.Equals(candidate.ProductName, configuration.ProductName, StringComparison.OrdinalIgnoreCase));

        if (directMatch is not null && !OccControllerClassifier.PrefersHidParsing(directMatch))
        {
            var hidReplacement = candidates.FirstOrDefault(candidate =>
                candidate.Backend == ControllerBackend.Hid &&
                SamePhysicalController(candidate, directMatch));

            if (hidReplacement is not null)
            {
                _log?.Info(
                    $"Migrating bound OCC controller from backend '{directMatch.Backend}' to HID parsing for '{hidReplacement.ProductName}'.");
                return hidReplacement;
            }
        }

        return directMatch;
    }

    private DeviceCandidate? TryCreateCandidate(HidDevice device)
    {
        try
        {
            return ToCandidate(device);
        }
        catch (Exception ex)
        {
            _log?.Warn($"Skipping HID device during bind enumeration: {device.DevicePath} ({ex.GetType().Name}: {ex.Message})");
            return null;
        }
    }

    private static DeviceCandidate ToCandidate(HidDevice device)
    {
        string? instanceId = null;
        int inputReportLength;
        int outputReportLength;

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

        inputReportLength = SafeGet(device.GetMaxInputReportLength);
        outputReportLength = SafeGet(device.GetMaxOutputReportLength);
        var derivedVendorId = TryExtractBluetoothCompatHexId(instanceId, "VID&")
                              ?? TryExtractHexId(instanceId, "VID&", 4)
                              ?? TryExtractHexId(device.DevicePath, "VID_", 4);
        var derivedProductId = TryExtractBluetoothCompatHexId(instanceId, "PID&")
                               ?? TryExtractHexId(instanceId, "PID&", 4)
                               ?? TryExtractHexId(device.DevicePath, "PID_", 4);
        var vendorId = device.VendorID != 0 ? device.VendorID : derivedVendorId ?? 0;
        var productId = device.ProductID != 0 ? device.ProductID : derivedProductId ?? 0;
        var isWireless = IsWirelessDevice(instanceId, device.DevicePath, productName);

        var candidate = new DeviceCandidate
        {
            Backend = ControllerBackend.Hid,
            ProductName = productName,
            DevicePath = device.DevicePath,
            InstanceId = instanceId,
            RuntimeInstanceId = device.DevicePath,
            SerialNumber = SafeGet(device.GetSerialNumber),
            VendorId = vendorId,
            ProductId = productId,
            InputReportLength = inputReportLength,
            OutputReportLength = outputReportLength,
            IsWireless = isWireless,
        };

        return ClassifyCandidate(candidate);
    }

    private DeviceCandidate? TryCreateGamepadCandidate(Gamepad gamepad, IReadOnlyList<DeviceCandidate> hidCandidates)
    {
        try
        {
            var raw = RawGameController.FromGameController(gamepad);
            if (raw is null)
            {
                return null;
            }

            var pnpInstanceId = ResolvePnPInstanceId(raw, hidCandidates);
            var candidate = new DeviceCandidate
            {
                Backend = ControllerBackend.WinRtGamepad,
                ProductName = string.IsNullOrWhiteSpace(raw.DisplayName) ? "Bluetooth Gamepad" : raw.DisplayName,
                DevicePath = raw.NonRoamableId ?? string.Empty,
                InstanceId = pnpInstanceId,
                RuntimeInstanceId = raw.NonRoamableId,
                SerialNumber = null,
                VendorId = raw.HardwareVendorId,
                ProductId = raw.HardwareProductId,
                InputReportLength = 12,
                OutputReportLength = 0,
                IsWireless = raw.IsWireless || IsWirelessDevice(pnpInstanceId, raw.NonRoamableId, raw.DisplayName),
            };

            return ClassifyCandidate(candidate);
        }
        catch (Exception ex)
        {
            _log?.Warn($"Skipping Gamepad API candidate during bind enumeration ({ex.GetType().Name}: {ex.Message})");
            return null;
        }
    }

    private DeviceCandidate? TryCreateRawGameControllerCandidate(RawGameController controller, IReadOnlyList<DeviceCandidate> hidCandidates)
    {
        try
        {
            var pnpInstanceId = ResolvePnPInstanceId(controller, hidCandidates);
            var candidate = new DeviceCandidate
            {
                Backend = ControllerBackend.WinRtRawGameController,
                ProductName = string.IsNullOrWhiteSpace(controller.DisplayName) ? "Bluetooth Game Controller" : controller.DisplayName,
                DevicePath = controller.NonRoamableId ?? string.Empty,
                InstanceId = pnpInstanceId,
                RuntimeInstanceId = controller.NonRoamableId,
                SerialNumber = null,
                VendorId = controller.HardwareVendorId,
                ProductId = controller.HardwareProductId,
                InputReportLength = 12,
                OutputReportLength = 0,
                IsWireless = controller.IsWireless || IsWirelessDevice(pnpInstanceId, controller.NonRoamableId, controller.DisplayName),
            };

            return ClassifyCandidate(candidate);
        }
        catch (Exception ex)
        {
            _log?.Warn($"Skipping Raw Game Controller API candidate during bind enumeration ({ex.GetType().Name}: {ex.Message})");
            return null;
        }
    }

    private static string GetCandidateIdentity(DeviceCandidate candidate)
    {
        if (OccControllerClassifier.PrefersHidParsing(candidate) &&
            !string.IsNullOrWhiteSpace(candidate.InstanceId))
        {
            return $"BT-HID:{candidate.InstanceId}";
        }

        if (candidate.VendorId == 0x045E &&
            candidate.ProductId == 0x028E &&
            candidate.IsWireless &&
            !string.IsNullOrWhiteSpace(candidate.InstanceId))
        {
            return $"BT-HID:{candidate.InstanceId}";
        }

        if (!string.IsNullOrWhiteSpace(candidate.InstanceId))
        {
            return candidate.InstanceId;
        }

        if (!string.IsNullOrWhiteSpace(candidate.RuntimeInstanceId))
        {
            return candidate.RuntimeInstanceId;
        }

        if (!string.IsNullOrWhiteSpace(candidate.DevicePath))
        {
            return candidate.DevicePath;
        }

        return $"{candidate.ProductName}|{candidate.VendorId:X4}|{candidate.ProductId:X4}";
    }

    private static int GetBackendPriority(DeviceCandidate candidate) => candidate.Backend switch
    {
        ControllerBackend.Hid when OccControllerClassifier.PrefersHidParsing(candidate) => 0,
        ControllerBackend.WinRtGamepad => 1,
        ControllerBackend.WinRtRawGameController => 2,
        ControllerBackend.Hid => 3,
        _ => 9,
    };

    private static DeviceCandidate ClassifyCandidate(DeviceCandidate candidate)
    {
        var isOccController = OccControllerClassifier.TryClassify(candidate, out var reason);

        return new DeviceCandidate
        {
            Backend = candidate.Backend,
            ProductName = candidate.ProductName,
            DevicePath = candidate.DevicePath,
            InstanceId = candidate.InstanceId,
            RuntimeInstanceId = candidate.RuntimeInstanceId,
            SerialNumber = candidate.SerialNumber,
            VendorId = candidate.VendorId,
            ProductId = candidate.ProductId,
            InputReportLength = candidate.InputReportLength,
            OutputReportLength = candidate.OutputReportLength,
            IsWireless = candidate.IsWireless,
            IsOccController = isOccController,
            OccDetectionReason = reason,
        };
    }

    private static string? ResolvePnPInstanceId(RawGameController controller, IReadOnlyList<DeviceCandidate> hidCandidates)
    {
        if (!string.IsNullOrWhiteSpace(controller.NonRoamableId) &&
            LooksLikePnpInstanceId(controller.NonRoamableId))
        {
            return controller.NonRoamableId;
        }

        var bestMatch = hidCandidates
            .Select(candidate => new { Candidate = candidate, Score = ScoreHidMatch(candidate, controller) })
            .Where(match => match.Score > 0)
            .OrderByDescending(match => match.Score)
            .ThenBy(match => match.Candidate.ProductName, StringComparer.OrdinalIgnoreCase)
            .Select(match => match.Candidate)
            .FirstOrDefault();

        return bestMatch?.InstanceId;
    }

    private static int ScoreHidMatch(DeviceCandidate hidCandidate, RawGameController controller)
    {
        var score = 0;

        if (hidCandidate.VendorId == controller.HardwareVendorId)
        {
            score += 4;
        }

        if (hidCandidate.ProductId == controller.HardwareProductId)
        {
            score += 4;
        }

        if (!string.IsNullOrWhiteSpace(controller.DisplayName) &&
            string.Equals(hidCandidate.ProductName, controller.DisplayName, StringComparison.OrdinalIgnoreCase))
        {
            score += 3;
        }

        if (hidCandidate.IsWireless == controller.IsWireless)
        {
            score += 2;
        }

        if (IsWirelessDevice(hidCandidate.InstanceId, hidCandidate.DevicePath, hidCandidate.ProductName))
        {
            score += 1;
        }

        if (hidCandidate.InputReportLength >= 12)
        {
            score += 1;
        }

        return score;
    }

    private static bool LooksLikePnpInstanceId(string? value)
    {
        return !string.IsNullOrWhiteSpace(value) && value.Contains('\\') && !value.Contains('{');
    }

    private static bool IsWirelessDevice(params string?[] values)
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
                value.Contains("WIRELESS", StringComparison.OrdinalIgnoreCase) ||
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

    private static int? TryExtractHexId(string? value, string marker, int digits)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        var markerIndex = value.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
        if (markerIndex < 0)
        {
            return null;
        }

        var start = markerIndex + marker.Length;
        if (value.Length < start + digits)
        {
            return null;
        }

        var hex = value.Substring(start, digits);
        return int.TryParse(hex, System.Globalization.NumberStyles.HexNumber, null, out var parsed)
            ? parsed
            : null;
    }

    private static int? TryExtractBluetoothCompatHexId(string? value, string marker)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        var markerIndex = value.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
        if (markerIndex < 0)
        {
            return null;
        }

        var start = markerIndex + marker.Length;
        var end = start;

        while (end < value.Length && Uri.IsHexDigit(value[end]))
        {
            end++;
        }

        var hexLength = end - start;
        if (hexLength < 4)
        {
            return null;
        }

        var hex = value.Substring(end - 4, 4);
        return int.TryParse(hex, System.Globalization.NumberStyles.HexNumber, null, out var parsed)
            ? parsed
            : null;
    }

    private static bool SamePhysicalController(DeviceCandidate left, DeviceCandidate right)
    {
        if (!string.IsNullOrWhiteSpace(left.InstanceId) &&
            !string.IsNullOrWhiteSpace(right.InstanceId) &&
            string.Equals(left.InstanceId, right.InstanceId, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        return left.VendorId == right.VendorId &&
               left.ProductId == right.ProductId &&
               left.IsWireless == right.IsWireless &&
               string.Equals(left.ProductName, right.ProductName, StringComparison.OrdinalIgnoreCase);
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

    private static int SafeGet(Func<int> getter)
    {
        try
        {
            return getter();
        }
        catch
        {
            return 0;
        }
    }
}
