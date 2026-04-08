using System.Diagnostics;
using OccBridge.Core.Install;
using OccBridge.Core.Models;

namespace OccBridge.Install;

public sealed class InstallerForm : Form
{
    private readonly PrerequisiteService _prerequisiteService = new();
    private readonly BundledPrerequisiteInstaller _bundledInstaller = new();
    private readonly CheckedListBox _installerList = new()
    {
        Dock = DockStyle.Fill,
        CheckOnClick = true,
    };

    private readonly TextBox _details = new()
    {
        Dock = DockStyle.Fill,
        ReadOnly = true,
        Multiline = true,
        ScrollBars = ScrollBars.Vertical,
    };

    private readonly Button _refreshButton = new() { Text = "Refresh Status", AutoSize = true };
    private readonly Button _installButton = new() { Text = "Install Selected", AutoSize = true };
    private readonly Button _launchBridgeButton = new() { Text = "Launch OCC Bridge", AutoSize = true };
    private readonly Button _closeButton = new() { Text = "Close", AutoSize = true };

    public InstallerForm()
    {
        Text = "OCC Bridge Prerequisites";
        Width = 860;
        Height = 560;
        StartPosition = FormStartPosition.CenterScreen;

        BuildUi();
        WireEvents();
    }

    protected override void OnLoad(EventArgs e)
    {
        base.OnLoad(e);
        RefreshStatus();
    }

    private void BuildUi()
    {
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Padding = new Padding(12),
        };
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var intro = new Label
        {
            AutoSize = true,
            MaximumSize = new Size(800, 0),
            Text =
                "This setup helper does not hide driver installs. It checks ViGEmBus and HidHide, explains what each one does, and elevates only when you choose to run a bundled installer.",
        };

        var content = new SplitContainer
        {
            Dock = DockStyle.Fill,
            Orientation = Orientation.Horizontal,
            SplitterDistance = 220,
        };

        content.Panel1.Controls.Add(_installerList);
        content.Panel2.Controls.Add(_details);

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
        };
        buttons.Controls.AddRange(
        [
            _refreshButton,
            _installButton,
            _launchBridgeButton,
            _closeButton,
        ]);

        layout.Controls.Add(intro, 0, 0);
        layout.Controls.Add(content, 0, 1);
        layout.Controls.Add(buttons, 0, 2);

        Controls.Add(layout);
    }

    private void WireEvents()
    {
        _refreshButton.Click += (_, _) => RefreshStatus();
        _installButton.Click += async (_, _) => await InstallSelectedAsync();
        _launchBridgeButton.Click += (_, _) => LaunchBridge();
        _closeButton.Click += (_, _) => Close();
        _installerList.SelectedIndexChanged += (_, _) => RefreshDetailsForSelection();
    }

    private void RefreshStatus()
    {
        var summary = _prerequisiteService.Probe();
        _installerList.Items.Clear();

        foreach (var definition in BundledPrerequisiteCatalog.All)
        {
            var status = definition.Id == "vigembus" ? summary.ViGEmBus : summary.HidHide;
            var present = _bundledInstaller.IsBundledInstallerPresent(definition);
            var line =
                $"{definition.DisplayName} | Driver {(status.IsOperational ? "Ready" : "Missing/Not Ready")} | Embedded installer {(present ? "Present" : "Missing")}";
            _installerList.Items.Add(line, definition.Required && !status.IsOperational);
        }

        _details.Text =
            $"ViGEmBus: {summary.ViGEmBus.Message}{Environment.NewLine}" +
            $"HidHide: {summary.HidHide.Message}{Environment.NewLine}{Environment.NewLine}" +
            "Bundled prerequisite installers are embedded inside OccBridge.Install.exe.";
    }

    private void RefreshDetailsForSelection()
    {
        if (_installerList.SelectedIndex < 0)
        {
            return;
        }

        var definition = BundledPrerequisiteCatalog.All[_installerList.SelectedIndex];
        _details.Text =
            $"{definition.DisplayName}{Environment.NewLine}{Environment.NewLine}" +
            $"{definition.Description}{Environment.NewLine}{Environment.NewLine}" +
            $"Embedded resource: {definition.EmbeddedResourceName}{Environment.NewLine}" +
            $"Present: {_bundledInstaller.IsBundledInstallerPresent(definition)}{Environment.NewLine}" +
            $"Arguments: {definition.Arguments}";
    }

    private async Task InstallSelectedAsync()
    {
        var selectedDefinitions = _installerList.CheckedIndices
            .Cast<int>()
            .Select(index => BundledPrerequisiteCatalog.All[index])
            .ToList();

        if (selectedDefinitions.Count == 0)
        {
            MessageBox.Show(this, "Select at least one prerequisite to install.", "Nothing Selected",
                MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        var confirm = MessageBox.Show(
            this,
            "The selected installers will be launched visibly and Windows may show one or more UAC prompts. Continue?",
            "Confirm Driver Installation",
            MessageBoxButtons.OKCancel,
            MessageBoxIcon.Warning);

        if (confirm != DialogResult.OK)
        {
            return;
        }

        var messages = new List<string>();
        bool rebootRequired = false;

        foreach (var definition in selectedDefinitions)
        {
            var result = await _bundledInstaller.RunAsync(definition);
            messages.Add($"{definition.DisplayName}: {result.Message}");
            rebootRequired |= result.RequiresReboot;
        }

        RefreshStatus();
        MessageBox.Show(
            this,
            string.Join(Environment.NewLine, messages) +
            (rebootRequired ? $"{Environment.NewLine}{Environment.NewLine}Windows reported that a reboot is recommended." : string.Empty),
            "Installation Results",
            MessageBoxButtons.OK,
            rebootRequired ? MessageBoxIcon.Warning : MessageBoxIcon.Information);
    }

    private void LaunchBridge()
    {
        var bridgePath = Path.Combine(AppContext.BaseDirectory, "OccBridge.App.exe");
        if (!File.Exists(bridgePath))
        {
            MessageBox.Show(
                this,
                "OccBridge.App.exe was not found next to the installer. Publish both apps together.",
                "Bridge App Not Found",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information);
            return;
        }

        Process.Start(new ProcessStartInfo(bridgePath) { UseShellExecute = true });
    }
}
