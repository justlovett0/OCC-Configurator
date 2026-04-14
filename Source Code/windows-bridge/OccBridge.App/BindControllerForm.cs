using OccBridge.Core.Models;

namespace OccBridge.App;

public sealed class BindControllerForm : Form
{
    private readonly ListBox _deviceList = new()
    {
        Dock = DockStyle.Fill,
        BorderStyle = BorderStyle.None,
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
            ForeColor = OccTheme.TextDim,
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

        // Owner-draw so the selection highlight uses the OCC palette instead of system blue
        _deviceList.DrawMode = DrawMode.OwnerDrawFixed;
        _deviceList.DrawItem += DrawDeviceListItem;

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.RightToLeft,
            AutoSize = true,
        };

        var okButton = new Button { Text = "Bind", DialogResult = DialogResult.OK };
        var cancelButton = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel };

        OccTheme.StyleButton(okButton, OccTheme.AccentGreen);
        OccTheme.StyleButton(cancelButton);

        buttons.Controls.Add(okButton);
        buttons.Controls.Add(cancelButton);

        layout.Controls.Add(header,      0, 0);
        layout.Controls.Add(_deviceList, 0, 1);
        layout.Controls.Add(buttons,     0, 2);

        Controls.Add(layout);
        AcceptButton = okButton;
        CancelButton = cancelButton;

        OccTheme.ApplyDark(this);

        // Override listbox colors after ApplyDark so they aren't reset
        _deviceList.BackColor = OccTheme.BgInput;
        _deviceList.ForeColor = OccTheme.TextHeader;
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        OccTheme.ApplyDarkTitleBar(this);
    }

    public DeviceCandidate? SelectedCandidate => _deviceList.SelectedItem as DeviceCandidate;

    private void DrawDeviceListItem(object? sender, DrawItemEventArgs e)
    {
        if (e.Index < 0)
        {
            return;
        }

        bool selected = (e.State & DrawItemState.Selected) != 0;
        using var bg = new SolidBrush(selected ? OccTheme.BgHover : OccTheme.BgInput);
        e.Graphics.FillRectangle(bg, e.Bounds);

        var text = _deviceList.Items[e.Index]?.ToString() ?? string.Empty;
        using var fg = new SolidBrush(OccTheme.TextHeader);
        e.Graphics.DrawString(text, e.Font ?? OccTheme.UiFont, fg,
            new RectangleF(e.Bounds.X + 4, e.Bounds.Y + 2, e.Bounds.Width - 4, e.Bounds.Height));
    }
}
