using Nefarius.ViGEm.Client;
using Nefarius.ViGEm.Client.Exceptions;
using Nefarius.ViGEm.Client.Targets;
using OccBridge.Core.Diagnostics;
using OccBridge.Core.Models;

namespace OccBridge.Core.Bridge;

public sealed class VirtualControllerService : IDisposable
{
    private readonly FileLog _log;
    private ViGEmClient? _client;
    private IXbox360Controller? _controller;

    public VirtualControllerService(FileLog log)
    {
        _log = log;
    }

    public bool IsConnected => _controller is not null;

    public void EnsureConnected()
    {
        if (_controller is not null)
        {
            return;
        }

        _client = new ViGEmClient();
        _controller = _client.CreateXbox360Controller();
        _controller.AutoSubmitReport = false;
        _controller.Connect();
        _log.Info("Connected virtual ViGEm Xbox 360 controller.");
    }

    public void Submit(OccState state)
    {
        EnsureConnected();
        CloneHeroMapper.Apply(_controller!, state);
    }

    public void Reset()
    {
        if (_controller is null)
        {
            return;
        }

        _controller.ResetReport();
        _controller.SubmitReport();
    }

    public void Disconnect()
    {
        if (_controller is null)
        {
            return;
        }

        try
        {
            _controller.Disconnect();
            _log.Info("Disconnected virtual ViGEm controller.");
        }
        catch (Exception ex)
        {
            _log.Exception("Failed to disconnect virtual controller cleanly", ex);
        }
        finally
        {
            _controller = null;
            _client?.Dispose();
            _client = null;
        }
    }

    public void Dispose()
    {
        Disconnect();
    }
}
