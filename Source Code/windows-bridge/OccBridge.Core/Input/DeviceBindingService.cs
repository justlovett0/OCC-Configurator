using HidSharp;
using Nefarius.Utilities.DeviceManagement.PnP;
using OccBridge.Core.Diagnostics;
using OccBridge.Core.Models;
using Windows.Gaming.Input;

namespace OccBridge.Core.Input;

public sealed class DeviceBindingService
{
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
            .Select(TryCreateGamepadCandidate)
            .Where(candidate => candidate is not null)
            .Select(candidate => candidate!)
            .ToList();

        var rawGameControllerCandidates = RawGameController.RawGameControllers
            .Select(TryCreateRawGameControllerCandidate)
            .Where(candidate => candidate is not null)
            .Select(candidate => candidate!)
            .ToList();

        var candidates = hidCandidates
            .Concat(gamepadCandidates)
            .Concat(rawGameControllerCandidates)
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
            _log?.Info($"Bind candidate: {candidate.ProductName} [{candidate.Backend}] VID={candidate.VendorId:X4} PID={candidate.ProductId:X4} Id={candidate.InstanceId ?? candidate.DevicePath}");
        }

        return candidates;
    }

    public BoundControllerConfiguration Bind(DeviceCandidate candidate) => new()
    {
        Backend = candidate.Backend,
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
                   candidate.Backend == configuration.Backend &&
                   !string.IsNullOrWhiteSpace(configuration.InstanceId) &&
                   string.Equals(candidate.InstanceId, configuration.InstanceId, StringComparison.OrdinalIgnoreCase))
               ?? candidates.FirstOrDefault(candidate =>
                   candidate.Backend == configuration.Backend &&
                   string.Equals(candidate.DevicePath, configuration.DevicePath, StringComparison.OrdinalIgnoreCase))
               ?? candidates.FirstOrDefault(candidate =>
                   candidate.Backend == configuration.Backend &&
                   candidate.VendorId == configuration.VendorId &&
                   candidate.ProductId == configuration.ProductId &&
                   string.Equals(candidate.ProductName, configuration.ProductName, StringComparison.OrdinalIgnoreCase));
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

        return new DeviceCandidate
        {
            Backend = ControllerBackend.Hid,
            ProductName = productName,
            DevicePath = device.DevicePath,
            InstanceId = instanceId,
            SerialNumber = SafeGet(device.GetSerialNumber),
            VendorId = device.VendorID,
            ProductId = device.ProductID,
            InputReportLength = inputReportLength,
            OutputReportLength = outputReportLength,
        };
    }

    private DeviceCandidate? TryCreateGamepadCandidate(Gamepad gamepad)
    {
        try
        {
            var raw = RawGameController.FromGameController(gamepad);
            if (raw is null)
            {
                return null;
            }

            return new DeviceCandidate
            {
                Backend = ControllerBackend.WinRtGamepad,
                ProductName = string.IsNullOrWhiteSpace(raw.DisplayName) ? "Bluetooth Gamepad" : raw.DisplayName,
                DevicePath = raw.NonRoamableId ?? string.Empty,
                InstanceId = raw.NonRoamableId,
                SerialNumber = null,
                VendorId = raw.HardwareVendorId,
                ProductId = raw.HardwareProductId,
                InputReportLength = 12,
                OutputReportLength = 0,
            };
        }
        catch (Exception ex)
        {
            _log?.Warn($"Skipping Gamepad API candidate during bind enumeration ({ex.GetType().Name}: {ex.Message})");
            return null;
        }
    }

    private DeviceCandidate? TryCreateRawGameControllerCandidate(RawGameController controller)
    {
        try
        {
            return new DeviceCandidate
            {
                Backend = ControllerBackend.WinRtRawGameController,
                ProductName = string.IsNullOrWhiteSpace(controller.DisplayName) ? "Bluetooth Game Controller" : controller.DisplayName,
                DevicePath = controller.NonRoamableId ?? string.Empty,
                InstanceId = controller.NonRoamableId,
                SerialNumber = null,
                VendorId = controller.HardwareVendorId,
                ProductId = controller.HardwareProductId,
                InputReportLength = 12,
                OutputReportLength = 0,
            };
        }
        catch (Exception ex)
        {
            _log?.Warn($"Skipping Raw Game Controller API candidate during bind enumeration ({ex.GetType().Name}: {ex.Message})");
            return null;
        }
    }

    private static string GetCandidateIdentity(DeviceCandidate candidate)
    {
        if (!string.IsNullOrWhiteSpace(candidate.InstanceId))
        {
            return candidate.InstanceId;
        }

        if (!string.IsNullOrWhiteSpace(candidate.DevicePath))
        {
            return candidate.DevicePath;
        }

        return $"{candidate.ProductName}|{candidate.VendorId:X4}|{candidate.ProductId:X4}";
    }

    private static int GetBackendPriority(DeviceCandidate candidate) => candidate.Backend switch
    {
        ControllerBackend.WinRtGamepad => 0,
        ControllerBackend.Hid => 1,
        ControllerBackend.WinRtRawGameController => 2,
        _ => 9,
    };

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
