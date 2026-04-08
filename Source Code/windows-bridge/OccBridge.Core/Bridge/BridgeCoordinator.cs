using OccBridge.Core.Configuration;
using OccBridge.Core.Diagnostics;
using OccBridge.Core.Input;
using OccBridge.Core.Install;
using OccBridge.Core.Models;

namespace OccBridge.Core.Bridge;

public sealed class BridgeCoordinator : IDisposable
{
    private readonly AppConfigurationStore _configurationStore;
    private readonly DeviceBindingService _deviceBindingService;
    private readonly FileLog _log;
    private readonly PhysicalInputService _physicalInputService;
    private readonly PrerequisiteService _prerequisiteService;
    private readonly VirtualControllerService _virtualControllerService;
    private readonly HideService _hideService;

    private CancellationTokenSource? _cts;
    private Task? _worker;
    private string? _currentHiddenInstanceId;

    public BridgeCoordinator(
        AppConfigurationStore configurationStore,
        DeviceBindingService deviceBindingService,
        PhysicalInputService physicalInputService,
        PrerequisiteService prerequisiteService,
        VirtualControllerService virtualControllerService,
        HideService hideService,
        FileLog log)
    {
        _configurationStore = configurationStore;
        _deviceBindingService = deviceBindingService;
        _physicalInputService = physicalInputService;
        _prerequisiteService = prerequisiteService;
        _virtualControllerService = virtualControllerService;
        _hideService = hideService;
        _log = log;
        Status = BridgeRuntimeStatus.Idle();
    }

    public BridgeRuntimeStatus Status { get; private set; }

    public event Action<BridgeRuntimeStatus>? StatusChanged;

    public bool IsRunning => _worker is not null && !_worker.IsCompleted;

    public void Start()
    {
        if (IsRunning)
        {
            return;
        }

        var prerequisites = _prerequisiteService.Probe();
        if (!prerequisites.CanBridge)
        {
            PublishStatus(new BridgeRuntimeStatus
            {
                PrerequisitesReady = false,
                StatusText = "ViGEmBus is missing or not operational.",
                LastError = prerequisites.ViGEmBus.Message,
            });
            return;
        }

        var configuration = _configurationStore.Load();
        if (configuration.BoundController is null)
        {
            PublishStatus(new BridgeRuntimeStatus
            {
                PrerequisitesReady = true,
                StatusText = "Bind an OCC controller before starting the bridge.",
            });
            return;
        }

        _cts = new CancellationTokenSource();
        _worker = Task.Run(() => RunAsync(configuration, prerequisites, _cts.Token));
    }

    public async Task StopAsync()
    {
        if (_cts is null)
        {
            return;
        }

        _cts.Cancel();

        if (_worker is not null)
        {
            try
            {
                await _worker.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                // ignored
            }
        }

        _virtualControllerService.Disconnect();
        TryRemoveHide();
        _cts.Dispose();
        _cts = null;
        _worker = null;
        PublishStatus(BridgeRuntimeStatus.Idle("Bridge stopped."));
    }

    private async Task RunAsync(
        AppConfiguration configuration,
        PrerequisiteSummary prerequisites,
        CancellationToken cancellationToken)
    {
        PublishStatus(new BridgeRuntimeStatus
        {
            IsRunning = true,
            PrerequisitesReady = prerequisites.CanBridge,
            StatusText = "Waiting for bound OCC controller...",
        });

        try
        {
            var appPath = Environment.ProcessPath ?? string.Empty;
            if (!string.IsNullOrWhiteSpace(appPath))
            {
                _hideService.EnsureApplicationWhitelisted(appPath);
            }

            while (!cancellationToken.IsCancellationRequested)
            {
                var bound = configuration.BoundController!;
                var candidate = _deviceBindingService.ResolveBoundDevice(bound);

                if (candidate is null)
                {
                    PublishStatus(new BridgeRuntimeStatus
                    {
                        IsRunning = true,
                        PrerequisitesReady = prerequisites.CanBridge,
                        StatusText = "Waiting for bound OCC controller...",
                        ActiveDeviceName = bound.ProductName,
                    });

                    await Task.Delay(TimeSpan.FromSeconds(2), cancellationToken).ConfigureAwait(false);
                    continue;
                }

                if (configuration.HidePhysicalController && prerequisites.CanHide)
                {
                    _hideService.ApplyHide(candidate.InstanceId);
                    _currentHiddenInstanceId = candidate.InstanceId;
                }

                PublishStatus(new BridgeRuntimeStatus
                {
                    IsRunning = true,
                    PrerequisitesReady = prerequisites.CanBridge,
                    HideApplied = configuration.HidePhysicalController && prerequisites.CanHide,
                    StatusText = "Connected to physical OCC controller.",
                    ActiveDeviceName = candidate.ProductName,
                });

                bool completedNormally = await _physicalInputService.ReadUntilDisconnectAsync(
                    candidate,
                    state =>
                    {
                        _virtualControllerService.Submit(state);
                        PublishStatus(new BridgeRuntimeStatus
                        {
                            IsRunning = true,
                            PrerequisitesReady = prerequisites.CanBridge,
                            VirtualControllerConnected = true,
                            HideApplied = configuration.HidePhysicalController && prerequisites.CanHide,
                            StatusText = "Bridging OCC controller to virtual Xbox 360 pad.",
                            ActiveDeviceName = candidate.ProductName,
                        });
                        return Task.CompletedTask;
                    },
                    cancellationToken).ConfigureAwait(false);

                _virtualControllerService.Reset();

                if (!completedNormally && !cancellationToken.IsCancellationRequested)
                {
                    PublishStatus(new BridgeRuntimeStatus
                    {
                        IsRunning = true,
                        PrerequisitesReady = prerequisites.CanBridge,
                        StatusText = "Physical OCC controller disconnected. Waiting to reconnect...",
                        ActiveDeviceName = candidate.ProductName,
                    });
                    await Task.Delay(TimeSpan.FromSeconds(1), cancellationToken).ConfigureAwait(false);
                }
            }
        }
        catch (OperationCanceledException)
        {
            // ignored
        }
        catch (Exception ex)
        {
            _log.Exception("Bridge worker failed", ex);
            PublishStatus(new BridgeRuntimeStatus
            {
                PrerequisitesReady = prerequisites.CanBridge,
                StatusText = "Bridge failed.",
                LastError = ex.Message,
            });
        }
        finally
        {
            _virtualControllerService.Disconnect();
            TryRemoveHide();
        }
    }

    private void TryRemoveHide()
    {
        if (!string.IsNullOrWhiteSpace(_currentHiddenInstanceId))
        {
            _hideService.RemoveHide(_currentHiddenInstanceId);
            _currentHiddenInstanceId = null;
        }
    }

    private void PublishStatus(BridgeRuntimeStatus status)
    {
        Status = status;
        StatusChanged?.Invoke(status);
    }

    public void Dispose()
    {
        if (IsRunning)
        {
            StopAsync().GetAwaiter().GetResult();
        }
    }
}
