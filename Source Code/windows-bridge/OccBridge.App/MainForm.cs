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

    private readonly Label _driverStatusValue  = new() { AutoSize = true };
    private readonly Label _boundControllerValue = new() { AutoSize = true };
    private readonly Label _bridgeStatusValue  = new() { AutoSize = true };
    private readonly CheckBox _startupCheckBox = new() { Text = "Start OCC Bridge with Windows", AutoSize = true };
    private readonly CheckBox _hideCheckBox    = new() { Text = "Hide physical controller with HidHide when available", AutoSize = true };
    private readonly Button _bindButton        = new() { Text = "Choose Controller" };
    private readonly Button _installButton     = new() { Text = "Install / Repair Drivers" };
    private readonly Button _startButton       = new() { Text = "Auto Select and Emulate Guitar" };
    private readonly Button _stopButton        = new() { Text = "Stop Emulation" };
    private readonly Button _openLogsButton    = new() { Text = "Open Logs" };
    private readonly Button _exitButton        = new() { Text = "Close OCC Bridge" };
    private readonly Button _helpButton        = new() { Text = "?", Width = 28, Height = 28, AutoSize = false };
    private readonly TextBox _logTextBox = new()
    {
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Vertical,
        Dock = DockStyle.Fill,
        BorderStyle = BorderStyle.None,
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
        OccTheme.ApplyDark(this);
        WireEvents();
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        OccTheme.ApplyDarkTitleBar(this);
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
        // 7 rows: content rows interleaved with 1px separators
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 7,
            Padding = new Padding(12),
        };
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));     // 0 summary
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));     // 1 separator
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));     // 2 options
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));     // 3 separator
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));     // 4 buttons
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));     // 5 separator
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); // 6 log

        // --- Status summary ---
        var summary = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            AutoSize = true,
        };
        summary.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        summary.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));

        summary.Controls.Add(new Label { Text = "Driver Status:",    AutoSize = true, ForeColor = OccTheme.TextDim }, 0, 0);
        summary.Controls.Add(_driverStatusValue, 1, 0);
        summary.Controls.Add(new Label { Text = "Bound Controller:", AutoSize = true, ForeColor = OccTheme.TextDim }, 0, 1);
        summary.Controls.Add(_boundControllerValue, 1, 1);
        summary.Controls.Add(new Label { Text = "Bridge Status:",    AutoSize = true, ForeColor = OccTheme.TextDim }, 0, 2);
        summary.Controls.Add(_bridgeStatusValue, 1, 2);

        _driverStatusValue.ForeColor   = OccTheme.TextDim;
        _boundControllerValue.ForeColor = OccTheme.TextDim;
        _bridgeStatusValue.ForeColor   = OccTheme.TextDim;

        // --- Options ---
        _startupCheckBox.ForeColor = OccTheme.TextDim;
        _hideCheckBox.ForeColor    = OccTheme.TextDim;

        var optionsPanel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.TopDown,
            AutoSize = true,
            WrapContents = false,
        };
        optionsPanel.Controls.Add(_startupCheckBox);
        optionsPanel.Controls.Add(_hideCheckBox);

        // --- Buttons ---
        OccTheme.StyleButton(_bindButton,    OccTheme.AccentBlue);
        OccTheme.StyleButton(_installButton);
        OccTheme.StyleButton(_startButton,   OccTheme.AccentGreen);
        OccTheme.StyleButton(_stopButton);
        OccTheme.StyleButton(_openLogsButton);
        OccTheme.StyleButton(_exitButton);

        var primaryButtons = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true };
        primaryButtons.Controls.AddRange([_bindButton, _startButton, _stopButton]);

        var secondaryButtons = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true };
        secondaryButtons.Controls.AddRange([_openLogsButton, _installButton, _exitButton]);

        var buttons = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
            AutoSize = true,
        };
        buttons.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        buttons.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        buttons.Controls.Add(primaryButtons,   0, 0);
        buttons.Controls.Add(secondaryButtons, 0, 1);

        // --- Log ---
        _logTextBox.BackColor = OccTheme.BgCard;
        _logTextBox.ForeColor = OccTheme.TextDim;
        _logTextBox.Font = new Font("Consolas", 9f);

        var logGroup = new GroupBox
        {
            Text = "Bridge Log",
            Dock = DockStyle.Fill,
        };
        logGroup.Controls.Add(_logTextBox);

        layout.Controls.Add(summary,                  0, 0);
        layout.Controls.Add(OccTheme.MakeSeparator(), 0, 1);
        layout.Controls.Add(optionsPanel,              0, 2);
        layout.Controls.Add(OccTheme.MakeSeparator(), 0, 3);
        layout.Controls.Add(buttons,                   0, 4);
        layout.Controls.Add(OccTheme.MakeSeparator(), 0, 5);
        layout.Controls.Add(logGroup,                  0, 6);

        Controls.Add(layout);

        OccTheme.StyleButton(_helpButton);
        _helpButton.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        _helpButton.Location = new Point(ClientSize.Width - _helpButton.Width - 14, 14);
        Controls.Add(_helpButton);
        _helpButton.BringToFront();
    }

    private ContextMenuStrip BuildTrayMenu()
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add("Open", null, (_, _) => ShowFromTray());
        menu.Items.Add("Choose Controller", null, (_, _) => BindController());
        menu.Items.Add("Install / Repair Drivers", null, (_, _) => LaunchInstaller());
        menu.Items.Add("Auto Select and Emulate Guitar", null, (_, _) => StartBridge());
        menu.Items.Add("Stop Emulation", null, async (_, _) => await StopBridgeAsync());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Close OCC Bridge", null, async (_, _) => await ExitApplicationAsync());
        return menu;
    }

    private void WireEvents()
    {
        _bindButton.Click     += (_, _) => BindController();
        _installButton.Click  += (_, _) => LaunchInstaller();
        _startButton.Click    += (_, _) => StartBridge();
        _stopButton.Click     += async (_, _) => await StopBridgeAsync();
        _openLogsButton.Click += (_, _) => OpenLogs();
        _exitButton.Click     += async (_, _) => await ExitApplicationAsync();
        _helpButton.Click     += (_, _) => ShowHelp();
        _startupCheckBox.CheckedChanged += (_, _) => SaveUiSettings();
        _hideCheckBox.CheckedChanged    += (_, _) => SaveUiSettings();
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
            _hideCheckBox.Checked    = configuration.HidePhysicalController;

            var name = configuration.BoundController?.ProductName;
            _boundControllerValue.Text      = name ?? "None";
            _boundControllerValue.ForeColor = name is null ? OccTheme.TextDim : OccTheme.TextHeader;

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
        configuration.AutoStartAtLogon       = _startupCheckBox.Checked;
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
        var summary  = _prerequisiteService.Probe();
        bool vigem   = summary.ViGEmBus.IsOperational;
        bool hidhide = summary.HidHide.IsOperational;

        _driverStatusValue.Text =
            $"ViGEmBus: {(vigem ? "Ready" : "Missing")} | HidHide: {(hidhide ? "Ready" : "Optional / Missing")}";

        // Red = ViGEmBus missing (required), orange = only HidHide absent, green = all good
        _driverStatusValue.ForeColor = !vigem    ? OccTheme.AccentRed
            : !hidhide                           ? OccTheme.AccentOrange
            : OccTheme.AccentGreen;
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

        _boundControllerValue.Text      = configuration.BoundController.ProductName;
        _boundControllerValue.ForeColor = OccTheme.TextHeader;
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

        _bridgeStatusValue.ForeColor = status.LastError is not null
            ? OccTheme.AccentRed
            : status.StatusText.Contains("running", StringComparison.OrdinalIgnoreCase)
                ? OccTheme.AccentBlue
                : OccTheme.TextDim;
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

    private void ShowHelp()
    {
        using var form = new HelpForm();
        form.ShowDialog(this);
    }

    private async Task ExitApplicationAsync()
    {
        _allowClose = true;
        await StopBridgeAsync();
        Close();
    }
}
