using Microsoft.Win32;
using Nefarius.Drivers.HidHide;
using Nefarius.ViGEm.Client;
using Nefarius.ViGEm.Client.Exceptions;
using OccBridge.Core.Models;

namespace OccBridge.Core.Install;

public sealed class PrerequisiteService
{
    public PrerequisiteSummary Probe()
    {
        return new PrerequisiteSummary
        {
            ViGEmBus = ProbeViGEmBus(),
            HidHide = ProbeHidHide(),
        };
    }

    private static PrerequisiteStatus ProbeViGEmBus()
    {
        var uninstallEntry = TryFindUninstallEntry("ViGEm Bus Driver");

        try
        {
            using var client = new ViGEmClient();
            return new PrerequisiteStatus
            {
                Name = "ViGEmBus",
                IsInstalled = true,
                IsOperational = true,
                InstalledVersion = uninstallEntry.Version,
                InstallLocation = uninstallEntry.InstallLocation,
                Message = "ViGEm Bus Driver is installed and operational.",
            };
        }
        catch (VigemBusNotFoundException)
        {
            return new PrerequisiteStatus
            {
                Name = "ViGEmBus",
                IsInstalled = uninstallEntry.Version is not null,
                IsOperational = false,
                InstalledVersion = uninstallEntry.Version,
                InstallLocation = uninstallEntry.InstallLocation,
                Message = "ViGEm Bus Driver is missing or not operational.",
            };
        }
        catch (Exception ex)
        {
            return new PrerequisiteStatus
            {
                Name = "ViGEmBus",
                IsInstalled = uninstallEntry.Version is not null,
                IsOperational = false,
                InstalledVersion = uninstallEntry.Version,
                InstallLocation = uninstallEntry.InstallLocation,
                Message = $"ViGEm Bus Driver did not initialize: {ex.Message}",
            };
        }
    }

    private static PrerequisiteStatus ProbeHidHide()
    {
        var uninstallEntry = TryFindUninstallEntry("HidHide");
        var control = new HidHideControlService();

        return new PrerequisiteStatus
        {
            Name = "HidHide",
            IsInstalled = control.IsInstalled || uninstallEntry.Version is not null,
            IsOperational = control.IsOperational,
            InstalledVersion = control.LocalDriverVersion ?? uninstallEntry.Version,
            InstallLocation = uninstallEntry.InstallLocation,
            Message = control.IsOperational
                ? "HidHide is installed and operational."
                : "HidHide is not operational. The bridge can still run, but games may see duplicate inputs.",
        };
    }

    private static (Version? Version, string? InstallLocation) TryFindUninstallEntry(string displayName)
    {
        foreach (var hive in new[]
                 {
                     Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                     Registry.LocalMachine.OpenSubKey(@"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                 })
        {
            if (hive is null)
            {
                continue;
            }

            foreach (var keyName in hive.GetSubKeyNames())
            {
                using var subKey = hive.OpenSubKey(keyName);
                var name = subKey?.GetValue("DisplayName") as string;

                if (string.IsNullOrWhiteSpace(name) ||
                    name.IndexOf(displayName, StringComparison.OrdinalIgnoreCase) < 0)
                {
                    continue;
                }

                Version? version = null;
                if (Version.TryParse(subKey?.GetValue("DisplayVersion") as string, out var parsed))
                {
                    version = parsed;
                }

                return (version, subKey?.GetValue("InstallLocation") as string);
            }
        }

        return (null, null);
    }
}
