using Microsoft.Win32;

namespace OccBridge.Core.Install;

public sealed class StartupRegistrationService
{
    private const string RunKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string ValueName = "OCC OccBridge";

    public bool IsEnabled()
    {
        using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, writable: false);
        return !string.IsNullOrWhiteSpace(key?.GetValue(ValueName) as string);
    }

    public void SetEnabled(string executablePath, bool enabled)
    {
        using var key = Registry.CurrentUser.CreateSubKey(RunKeyPath, writable: true);

        if (enabled)
        {
            key.SetValue(ValueName, $"\"{executablePath}\" --background");
        }
        else
        {
            key.DeleteValue(ValueName, throwOnMissingValue: false);
        }
    }
}
