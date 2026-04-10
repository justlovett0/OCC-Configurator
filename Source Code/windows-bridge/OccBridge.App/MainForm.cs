using System.Diagnostics;
using OccBridge.Core.Bridge;
using OccBridge.Core.Configuration;
using OccBridge.Core.Diagnostics;
using OccBridge.Core.Input;
using OccBridge.Core.Install;
using OccBridge.Core.Models;

namespace OccBridge.App;

public sealed class MainForm : Form
{
    private readonly bool _startHidden;
    private readonly AppConfigurationStore _configurationStore = new();
    private readonly FileLog _log = new();
    private readonly DeviceBindingService _deviceBindingService;
    private readonly PrerequisiteService _prerequisiteService = new();
    private readonly StartupRegistrationService _startupRegistrationService = new();
    private readonly BridgeCoordinator _bridgeCoordinator;

    private readonly Label _driverStatusValue = new() { AutoSize = true };
    private readonly Label _boundControllerValue = new() { AutoSize = true };
    private readonly Label _bridgeStatusValue = new() { AutoSize = true };
    private readonly CheckBox _startupCheckBox = new() { Text = "Start bridge app at logon", AutoSize = true };
    private readonly CheckBox _hideCheckBox = new() { Text = "Hide physical controller with HidHide when available", AutoSize = true };
    private readonly Button _bindButton = new() { Text = "Bind Controller", AutoSize = true };
    private readonly Button _installButton = new() { Text = "Install / Repair Prerequisites", AutoSize = true };
    private readonly Button _startButton = new() { Text = "Start Bridge", AutoSize = true };
    private readonly Button _stopButton = new() { Text = "Stop Bridge", AutoSize = true };
    private readonly Button _openLogsButton = new() { Text = "Open Logs", AutoSize = true };
    private readonly Button _exitButton = new() { Text = "Exit", AutoSize = true };
    private readonly TextBox _logTextBox = new()
    {
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Vertical,
        Dock = DockStyle.Fill,
    };

    private readonly NotifyIcon _notifyIcon;
    private bool _allowClose;
    private bool _updatingUi;

    public MainForm(bool startHidden)
    {
        _startHidden = startHidden;
        _deviceBindingService = new DeviceBindingService(_log);

        var physicalInputService = new PhysicalInputService(_log);
        var virtualControllerService = new VirtualControllerService(_log);
        var hideService = new HideService(_log);

        _bridgeCoordinator = new BridgeCoordinator(
            _configurationStore,
            _deviceBindingService,
            physicalInputService,
            _prerequisiteService,
            virtualControllerService,
            hideService,
            _log);

        Text = "OCC Bridge";
        Width = 860;
        Height = 620;
        StartPosition = FormStartPosition.CenterScreen;
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);

        _notifyIcon = new NotifyIcon
        {
            Text = "OCC Bridge",
            Icon = Icon ?? SystemIcons.Application,
            Visible = true,
            ContextMenuStrip = BuildTrayMenu(),
        };
        _notifyIcon.DoubleClick += (_, _) => ShowFromTray();

        BuildUi();
        WireEvents();
    }

    protected override void OnLoad(EventArgs e)
    {
        base.OnLoad(e);
        LoadConfigurationIntoUi();
        RefreshPrerequisiteStatus();

        if (_startHidden)
        {
            HideToTray();
            StartBridge();
        }
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (!_allowClose && e.CloseReason == CloseReason.UserClosing)
        {
            e.Cancel = true;
            HideToTray();
            return;
        }

        _notifyIcon.Visible = false;
        _bridgeCoordinator.Dispose();
        base.OnFormClosing(e);
    }

    private void BuildUi()
    {
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 4,
            Padding = new Padding(12),
        };
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var summary = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            AutoSize = true,
        };
        summary.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        summary.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));

        summary.Controls.Add(new Label { Text = "Driver Status:", AutoSize = true }, 0, 0);
        summary.Controls.Add(_driverStatusValue, 1, 0);
        summary.Controls.Add(new Label { Text = "Bound Controller:", AutoSize = true }, 0, 1);
        summary.Controls.Add(_boundControllerValue, 1, 1);
        summary.Controls.Add(new Label { Text = "Bridge Status:", AutoSize = true }, 0, 2);
        summary.Controls.Add(_bridgeStatusValue, 1, 2);

        var optionsPanel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.TopDown,
            AutoSize = true,
            WrapContents = false,
        };
        optionsPanel.Controls.Add(_startupCheckBox);
        optionsPanel.Controls.Add(_hideCheckBox);

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
        };
        buttons.Controls.AddRange(
        [
            _bindButton,
            _installButton,
            _startButton,
            _stopButton,
            _openLogsButton,
            _exitButton,
        ]);

        var logGroup = new GroupBox
        {
            Text = "Bridge Log",
            Dock = DockStyle.Fill,
        };
        logGroup.Controls.Add(_logTextBox);

        layout.Controls.Add(summary, 0, 0);
        layout.Controls.Add(optionsPanel, 0, 1);
        layout.Controls.Add(buttons, 0, 2);
        layout.Controls.Add(logGroup, 0, 3);

        Controls.Add(layout);
    }

    private ContextMenuStrip BuildTrayMenu()
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add("Open", null, (_, _) => ShowFromTray());
        menu.Items.Add("Bind Controller", null, (_, _) => BindController());
        menu.Items.Add("Install / Repair Prerequisites", null, (_, _) => LaunchInstaller());
        menu.Items.Add("Start Bridge", null, (_, _) => StartBridge());
        menu.Items.Add("Stop Bridge", null, async (_, _) => await StopBridgeAsync());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Exit", null, async (_, _) => await ExitApplicationAsync());
        return menu;
    }

    private void WireEvents()
    {
        _bindButton.Click += (_, _) => BindController();
        _installButton.Click += (_, _) => LaunchInstaller();
        _startButton.Click += (_, _) => StartBridge();
        _stopButton.Click += async (_, _) => await StopBridgeAsync();
        _openLogsButton.Click += (_, _) => OpenLogs();
        _exitButton.Click += async (_, _) => await ExitApplicationAsync();
        _startupCheckBox.CheckedChanged += (_, _) => SaveUiSettings();
        _hideCheckBox.CheckedChanged += (_, _) => SaveUiSettings();
        _bridgeCoordinator.StatusChanged += status => BeginInvoke(() => UpdateBridgeStatus(status));
        _log.MessageLogged += line =>
        {
            if (!IsDisposed)
            {
                BeginInvoke(() => _logTextBox.AppendText(line + Environment.NewLine));
            }
        };
        Resize += (_, _) =>
        {
            if (WindowState == FormWindowState.Minimized)
            {
                HideToTray();
            }
        };
    }

    private void LoadConfigurationIntoUi()
    {
        _updatingUi = true;
        try
        {
            var configuration = _configurationStore.Load();
            _startupCheckBox.Checked = configuration.AutoStartAtLogon;
            _hideCheckBox.Checked = configuration.HidePhysicalController;
            _boundControllerValue.Text = configuration.BoundController?.ProductName ?? "None";

            var processPath = Environment.ProcessPath;
            if (!string.IsNullOrWhiteSpace(processPath))
            {
                _startupRegistrationService.SetEnabled(processPath, configuration.AutoStartAtLogon);
            }
        }
        finally
        {
            _updatingUi = false;
        }
    }

    private void SaveUiSettings()
    {
        if (_updatingUi)
        {
            return;
        }

        var configuration = _configurationStore.Load();
        configuration.AutoStartAtLogon = _startupCheckBox.Checked;
        configuration.HidePhysicalController = _hideCheckBox.Checked;
        _configurationStore.Save(configuration);

        var processPath = Environment.ProcessPath;
        if (!string.IsNullOrWhiteSpace(processPath))
        {
            _startupRegistrationService.SetEnabled(processPath, configuration.AutoStartAtLogon);
        }
    }

    private void RefreshPrerequisiteStatus()
    {
        var summary = _prerequisiteService.Probe();
        _driverStatusValue.Text =
            $"ViGEmBus: {(summary.ViGEmBus.IsOperational ? "Ready" : "Missing")} | HidHide: {(summary.HidHide.IsOperational ? "Ready" : "Optional / Missing")}";
    }

    private void BindController()
    {
        IReadOnlyList<DeviceCandidate> candidates;

        try
        {
            candidates = _deviceBindingService.GetCandidates();
        }
        catch (Exception ex)
        {
            _log.Exception("Failed to enumerate HID devices for controller binding", ex);
            MessageBox.Show(
                this,
                "OCC Bridge could not enumerate Bluetooth/HID controllers on this PC. Check the log for details and try reconnecting the controller.",
                "Bind Failed",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return;
        }

        if (candidates.Count == 0)
        {
            MessageBox.Show(
                this,
                "No compatible HID controller candidates were found. Make sure the OCC guitar is powered on, paired, and connected over Bluetooth before binding.",
                "No Controllers Found",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information);
            return;
        }

        using var dialog = new BindControllerForm(candidates);
        if (dialog.ShowDialog(this) != DialogResult.OK || dialog.SelectedCandidate is null)
        {
            return;
        }

        var configuration = _configurationStore.Load();
        configuration.BoundController = _deviceBindingService.Bind(dialog.SelectedCandidate);
        _configurationStore.Save(configuration);
        _boundControllerValue.Text = configuration.BoundController.ProductName;
        _log.Info($"Bound controller: {configuration.BoundController.ProductName}");
    }

    private void LaunchInstaller()
    {
        var installerPath = Path.Combine(AppContext.BaseDirectory, "OccBridge.Install.exe");
        if (!File.Exists(installerPath))
        {
            MessageBox.Show(
                this,
                "OccBridge.Install.exe was not found next to the bridge app. Publish both apps together or run the installer project separately.",
                "Installer Not Found",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information);
            return;
        }

        Process.Start(new ProcessStartInfo(installerPath) { UseShellExecute = true });
    }

    private void StartBridge()
    {
        RefreshPrerequisiteStatus();
        SaveUiSettings();
        _bridgeCoordinator.Start();
    }

    private async Task StopBridgeAsync()
    {
        await _bridgeCoordinator.StopAsync();
    }

    private void UpdateBridgeStatus(BridgeRuntimeStatus status)
    {
        _bridgeStatusValue.Text = status.LastError is null
            ? status.StatusText
            : $"{status.StatusText} ({status.LastError})";
    }

    private void OpenLogs()
    {
        var logPath = _log.LogPath;
        if (!File.Exists(logPath))
        {
            File.WriteAllText(logPath, string.Empty);
        }

        Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{logPath}\"")
        {
            UseShellExecute = true,
        });
    }

    private void HideToTray()
    {
        Hide();
        ShowInTaskbar = false;
    }

    private void ShowFromTray()
    {
        Show();
        ShowInTaskbar = true;
        WindowState = FormWindowState.Normal;
        Activate();
    }

    private async Task ExitApplicationAsync()
    {
        _allowClose = true;
        await StopBridgeAsync();
        Close();
    }
}
