namespace OccBridge.App;

public sealed class HelpForm : Form
{
    public HelpForm()
    {
        Text = "About OCC Bridge";
        Width = 480;
        Height = 340;
        MinimizeBox = false;
        MaximizeBox = false;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        StartPosition = FormStartPosition.CenterParent;

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
            Padding = new Padding(16),
        };
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var rtb = new RichTextBox
        {
            ReadOnly = true,
            BorderStyle = BorderStyle.None,
            BackColor = OccTheme.BgMain,
            ForeColor = OccTheme.TextDim,
            ScrollBars = RichTextBoxScrollBars.None,
            Dock = DockStyle.Fill,
            WordWrap = true,
        };

        var normal = OccTheme.UiFont;
        var bold   = new Font(OccTheme.UiFont, FontStyle.Bold);

        void Append(string text, Font font)
        {
            rtb.SelectionFont  = font;
            rtb.SelectionColor = OccTheme.TextDim;
            rtb.AppendText(text);
        }

        Append("Controllers connected to Windows over Bluetooth act as a generic game controller.", normal);
        Append("\n\n", normal);
        Append("OCC Bridge will intercept your Bluetooth controller's inputs and re-send them to games like Clone Hero as Xbox Controller button presses.", normal);
        Append("\n\n", normal);
        Append("This should allow you to play Clone Hero over a Bluetooth OCC controller without manually binding buttons.", normal);
        Append("\n\n", normal);
        rtb.SelectionAlignment = HorizontalAlignment.Center;
        Append("BT Controller", bold);
        Append(" ---> ", normal);
        Append("OCC Bridge", bold);
        Append(" ---> ", normal);
        Append("Clone Hero", bold);

        var okButton = new Button { Text = "OK", DialogResult = DialogResult.OK };
        OccTheme.StyleButton(okButton, OccTheme.AccentBlue);

        var buttonRow = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.RightToLeft,
            AutoSize = true,
        };
        buttonRow.Controls.Add(okButton);

        layout.Controls.Add(rtb,       0, 0);
        layout.Controls.Add(buttonRow, 0, 1);
        Controls.Add(layout);

        // Redirect focus to OK button whenever RTB is clicked — prevents caret from appearing
        rtb.Enter += (_, _) => okButton.Focus();

        AcceptButton = okButton;
        OccTheme.ApplyDark(this);

        // ApplyDark doesn't recurse into RichTextBox — set manually after
        rtb.BackColor = OccTheme.BgMain;
        rtb.ForeColor = OccTheme.TextDim;
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        OccTheme.ApplyDarkTitleBar(this);
    }
}
