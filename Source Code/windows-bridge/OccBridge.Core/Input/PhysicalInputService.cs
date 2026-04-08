using HidSharp;
using OccBridge.Core.Diagnostics;
using OccBridge.Core.Models;

namespace OccBridge.Core.Input;

public sealed class PhysicalInputService
{
    private readonly FileLog _log;

    public PhysicalInputService(FileLog log)
    {
        _log = log;
    }

    public async Task<bool> ReadUntilDisconnectAsync(
        DeviceCandidate candidate,
        Func<OccState, Task> onState,
        CancellationToken cancellationToken)
    {
        var hidDevice = DeviceList.Local.GetHidDevices()
            .FirstOrDefault(device => string.Equals(device.DevicePath, candidate.DevicePath, StringComparison.OrdinalIgnoreCase));

        if (hidDevice is null)
        {
            return false;
        }

        if (!hidDevice.TryOpen(out HidStream? stream))
        {
            _log.Warn($"Failed to open HID stream for {candidate.ProductName}.");
            return false;
        }

        using var streamScope = stream;
        using var registration = cancellationToken.Register(() =>
        {
            try
            {
                stream.Close();
            }
            catch
            {
                // ignored
            }
        });

        var buffer = new byte[Math.Max(hidDevice.GetMaxInputReportLength(), 16)];
        _log.Info($"Opened physical HID controller: {candidate.ProductName}");

        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                int count;

                try
                {
                    count = await Task.Run(() => stream.Read(buffer, 0, buffer.Length), cancellationToken)
                        .ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (IOException)
                {
                    return false;
                }
                catch (ObjectDisposedException)
                {
                    return false;
                }

                if (count <= 0)
                {
                    continue;
                }

                if (OccReportParser.TryParse(buffer.AsSpan(0, count), out var state))
                {
                    await onState(state).ConfigureAwait(false);
                }
            }
        }
        finally
        {
            _log.Info($"Closed physical HID controller: {candidate.ProductName}");
        }

        return true;
    }
}
