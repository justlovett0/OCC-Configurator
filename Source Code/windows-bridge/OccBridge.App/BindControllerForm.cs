using OccBridge.Core.Models;

namespace OccBridge.App;

public sealed class BindControllerForm : Form
{
    private readonly ListBox _deviceList = new()
    {
        Dock = DockStyle.Fill,
    };

    public BindControllerForm(IReadOnlyList<DeviceCandidate> candidates)
    {
        Text = "Bind OCC Controller";
        Width = 720;
        Height = 420;
        MinimizeBox = false;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterParent;

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

        var header = new Label
        {
            AutoSize = true,
            Text = "Select the Bluetooth controller that represents your OCC guitar. The app will store its identity for automatic reconnects.",
            MaximumSize = new Size(680, 0),
        };

        foreach (var candidate in candidates)
        {
            _deviceList.Items.Add(candidate);
        }

        if (_deviceList.Items.Count > 0)
        {
            _deviceList.SelectedIndex = 0;
        }

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.RightToLeft,
            AutoSize = true,
        };

        var okButton = new Button
        {
            Text = "Bind",
            DialogResult = DialogResult.OK,
            AutoSize = true,
        };

        var cancelButton = new Button
        {
            Text = "Cancel",
            DialogResult = DialogResult.Cancel,
            AutoSize = true,
        };

        buttons.Controls.Add(okButton);
        buttons.Controls.Add(cancelButton);

        layout.Controls.Add(header, 0, 0);
        layout.Controls.Add(_deviceList, 0, 1);
        layout.Controls.Add(buttons, 0, 2);

        Controls.Add(layout);
        AcceptButton = okButton;
        CancelButton = cancelButton;
    }

    public DeviceCandidate? SelectedCandidate => _deviceList.SelectedItem as DeviceCandidate;
}
