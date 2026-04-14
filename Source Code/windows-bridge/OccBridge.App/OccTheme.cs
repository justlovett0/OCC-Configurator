using System.Runtime.InteropServices;

namespace OccBridge.App;

internal static class OccTheme
{
    public static readonly Color BgMain     = ColorTranslator.FromHtml("#1F1F23");
    public static readonly Color BgCard     = ColorTranslator.FromHtml("#2A2A2E");
    public static readonly Color BgInput    = ColorTranslator.FromHtml("#38383C");
    public static readonly Color BgHover    = ColorTranslator.FromHtml("#44444A");
    public static readonly Color TextDim    = ColorTranslator.FromHtml("#8B8B92");
    public static readonly Color TextHeader = ColorTranslator.FromHtml("#E8E8EC");
    public static readonly Color AccentBlue   = ColorTranslator.FromHtml("#4A9EFF");
    public static readonly Color AccentGreen  = ColorTranslator.FromHtml("#3DBF7D");
    public static readonly Color AccentRed    = ColorTranslator.FromHtml("#E54545");
    public static readonly Color AccentOrange = ColorTranslator.FromHtml("#D4944A");

    public static readonly Font UiFont = new("Segoe UI", 9f);

    // Recursively applies dark bg to layout containers so no white flash shows through.
    public static void ApplyDark(Form form)
    {
        form.BackColor = BgMain;
        form.ForeColor = TextHeader;
        form.Font = UiFont;
        ApplyDarkToControls(form.Controls);
    }

    private static void ApplyDarkToControls(Control.ControlCollection controls)
    {
        foreach (Control c in controls)
        {
            switch (c)
            {
                case TableLayoutPanel or FlowLayoutPanel:
                    c.BackColor = BgMain;
                    ApplyDarkToControls(c.Controls);
                    break;
                case GroupBox gb:
                    gb.BackColor = BgCard;
                    gb.ForeColor = TextDim;
                    ApplyDarkToControls(gb.Controls);
                    break;
                case SplitContainer sc:
                    sc.BackColor = BgMain;
                    sc.Panel1.BackColor = BgMain;
                    sc.Panel2.BackColor = BgMain;
                    ApplyDarkToControls(sc.Panel1.Controls);
                    ApplyDarkToControls(sc.Panel2.Controls);
                    break;
            }
        }
    }

    public static void StyleButton(Button btn, Color? accent = null)
    {
        btn.FlatStyle = FlatStyle.Flat;
        btn.BackColor = accent ?? BgInput;
        btn.ForeColor = TextHeader;
        btn.FlatAppearance.BorderColor = BgHover;
        btn.FlatAppearance.MouseOverBackColor = BgHover;
        btn.Padding = new Padding(8, 4, 8, 4);
        btn.AutoSize = true;
        btn.Cursor = Cursors.Hand;
    }

    // 1px horizontal rule between sections
    public static Panel MakeSeparator() => new()
    {
        Height = 1,
        Dock = DockStyle.Fill,
        BackColor = BgHover,
        Margin = new Padding(0, 6, 0, 6),
    };

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

    // Dark title bar on Win 10 20H1+ and Win 11
    public static void ApplyDarkTitleBar(Form form)
    {
        int v = 1;
        DwmSetWindowAttribute(form.Handle, 20, ref v, sizeof(int));
    }
}
