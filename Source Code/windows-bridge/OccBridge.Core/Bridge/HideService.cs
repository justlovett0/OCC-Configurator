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

    public void ApplyHide(string? instanceId)
    {
        if (!_control.IsOperational || string.IsNullOrWhiteSpace(instanceId))
        {
            return;
        }

        if (!_control.BlockedInstanceIds.Contains(instanceId, StringComparer.OrdinalIgnoreCase))
        {
            _control.AddBlockedInstanceId(instanceId);
            _log.Info($"Added HidHide blocked instance: {instanceId}");
        }

        if (!_control.IsActive)
        {
            _control.IsActive = true;
            _log.Info("Enabled HidHide filtering.");
        }
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
}
