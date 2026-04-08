namespace OccBridge.App;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var startHidden = args.Any(arg => string.Equals(arg, "--background", StringComparison.OrdinalIgnoreCase));
        Application.Run(new MainForm(startHidden));
    }
}
