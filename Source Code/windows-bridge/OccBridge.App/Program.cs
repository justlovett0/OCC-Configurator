namespace OccBridge.App;

using OccBridge.Core.Diagnostics;

internal static class Program
{
    private const string SingleInstanceMutexName = @"Local\OpenController.OccBridge.App";

    [STAThread]
    private static void Main(string[] args)
    {
        using var singleInstanceMutex = new Mutex(
            initiallyOwned: true,
            name: SingleInstanceMutexName,
            createdNew: out var isFirstInstance);

        if (!isFirstInstance)
        {
            new FileLog().Info("OCC Bridge startup skipped because another instance is already running.");
            return;
        }

        ApplicationConfiguration.Initialize();
        var startHidden = args.Any(arg => string.Equals(arg, "--background", StringComparison.OrdinalIgnoreCase));
        Application.Run(new MainForm(startHidden));
    }
}
