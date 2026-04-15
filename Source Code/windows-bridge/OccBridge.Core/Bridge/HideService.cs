using Nefarius.Drivers.HidHide;
using OccBridge.Core.Diagnostics;

namespace OccBridge.Core.Bridge;

public sealed class HideService
{
    private readonly FileLog _log;
    private readonly HidHideControlService _control = new();

    public HideService(FileLog log)
    {
        _log = log;
    }

    public bool IsOperational => _control.IsOperational;

    public void EnsureApplicationWhitelisted(string applicationPath)
    {
        if (!_control.IsOperational)
        {
            return;
        }

        if (_control.ApplicationPaths.Contains(applicationPath, StringComparer.OrdinalIgnoreCase))
        {
            return;
        }

        _control.AddApplicationPath(applicationPath, true);
        _log.Info($"Added application to HidHide whitelist: {applicationPath}");
    }

    public bool CanHideInstance(string? instanceId)
    {
        if (!_control.IsOperational || string.IsNullOrWhiteSpace(instanceId))
        {
            return false;
        }

        // HidHide expects a real PnP instance ID, not a WinRT non-roamable ID.
        // BLE HID instance IDs legitimately contain braces because the HID service
        // UUID is embedded in the hardware identifier, so brace checks are too strict.
        return LooksLikePnpInstanceId(instanceId);
    }

    public bool ApplyHide(string? instanceId)
    {
        if (!CanHideInstance(instanceId))
        {
            return false;
        }

        var safeInstanceId = instanceId!;

        if (!_control.BlockedInstanceIds.Contains(safeInstanceId, StringComparer.OrdinalIgnoreCase))
        {
            _control.AddBlockedInstanceId(safeInstanceId);
            _log.Info($"Added HidHide blocked instance: {safeInstanceId}");
        }

        if (!_control.IsActive)
        {
            _control.IsActive = true;
            _log.Info("Enabled HidHide filtering.");
        }

        return true;
    }

    public void RemoveHide(string? instanceId)
    {
        if (!_control.IsOperational || string.IsNullOrWhiteSpace(instanceId))
        {
            return;
        }

        if (_control.BlockedInstanceIds.Contains(instanceId, StringComparer.OrdinalIgnoreCase))
        {
            _control.RemoveBlockedInstanceId(instanceId);
            _log.Info($"Removed HidHide blocked instance: {instanceId}");
        }
    }

    private static bool LooksLikePnpInstanceId(string instanceId)
    {
        if (!instanceId.Contains('\\'))
        {
            return false;
        }

        return instanceId.StartsWith("HID\\", StringComparison.OrdinalIgnoreCase) ||
               instanceId.StartsWith("USB\\", StringComparison.OrdinalIgnoreCase) ||
               instanceId.StartsWith("BTH\\", StringComparison.OrdinalIgnoreCase) ||
               instanceId.StartsWith("ROOT\\", StringComparison.OrdinalIgnoreCase);
    }
}
