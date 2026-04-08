using System.Diagnostics;
using System.Reflection;
using OccBridge.Core.Models;

namespace OccBridge.Core.Install;

public sealed class BundledPrerequisiteInstaller
{
    public bool IsBundledInstallerPresent(BundledInstallerDefinition definition)
    {
        return GetHostAssembly().GetManifestResourceNames().Contains(definition.EmbeddedResourceName, StringComparer.Ordinal);
    }

    public async Task<BundledInstallerResult> RunAsync(
        BundledInstallerDefinition definition,
        CancellationToken cancellationToken = default)
    {
        if (!IsBundledInstallerPresent(definition))
        {
            return new BundledInstallerResult
            {
                Installer = definition,
                Success = false,
                ExitCode = -1,
                Message = $"Embedded installer resource not found: {definition.EmbeddedResourceName}",
            };
        }

        var extractDirectory = Path.Combine(
            Path.GetTempPath(),
            "OCC",
            "OccBridge",
            "Prerequisites",
            $"{definition.Id}-{Guid.NewGuid():N}");
        Directory.CreateDirectory(extractDirectory);

        var installerPath = Path.Combine(extractDirectory, Path.GetFileName(definition.RelativeInstallerPath));

        try
        {
            await ExtractEmbeddedInstallerAsync(definition, installerPath, cancellationToken).ConfigureAwait(false);
            return await RunInstallerAsync(installerPath, definition, cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            TryDeleteDirectory(extractDirectory);
        }
    }

    private static Assembly GetHostAssembly()
    {
        return Assembly.GetEntryAssembly() ?? Assembly.GetExecutingAssembly();
    }

    private static async Task ExtractEmbeddedInstallerAsync(
        BundledInstallerDefinition definition,
        string destinationPath,
        CancellationToken cancellationToken)
    {
        var assembly = GetHostAssembly();
        await using var resourceStream = assembly.GetManifestResourceStream(definition.EmbeddedResourceName)
            ?? throw new FileNotFoundException("Embedded installer resource was not found.", definition.EmbeddedResourceName);
        await using var destination = File.Create(destinationPath);
        await resourceStream.CopyToAsync(destination, cancellationToken).ConfigureAwait(false);
    }

    private static async Task<BundledInstallerResult> RunInstallerAsync(
        string installerPath,
        BundledInstallerDefinition definition,
        CancellationToken cancellationToken)
    {
        ProcessStartInfo startInfo;

        if (definition.IsMsi)
        {
            startInfo = new ProcessStartInfo("msiexec.exe")
            {
                Arguments = $"/i \"{installerPath}\" {definition.Arguments}".Trim(),
                UseShellExecute = true,
                Verb = "runas",
            };
        }
        else
        {
            startInfo = new ProcessStartInfo(installerPath)
            {
                Arguments = definition.Arguments,
                UseShellExecute = true,
                Verb = "runas",
            };
        }

        using var process = Process.Start(startInfo);

        if (process is null)
        {
            return new BundledInstallerResult
            {
                Installer = definition,
                Success = false,
                ExitCode = -1,
                Message = "Failed to start installer process.",
            };
        }

        await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
        var reboot = process.ExitCode is 3010 or 1641;
        var success = process.ExitCode is 0 or 3010 or 1641;

        return new BundledInstallerResult
        {
            Installer = definition,
            Success = success,
            RequiresReboot = reboot,
            ExitCode = process.ExitCode,
            Message = reboot
                ? $"{definition.DisplayName} installed. Windows reported a reboot is recommended."
                : success
                    ? $"{definition.DisplayName} installed successfully."
                    : $"{definition.DisplayName} installer exited with code {process.ExitCode}.",
        };
    }

    private static void TryDeleteDirectory(string path)
    {
        try
        {
            if (Directory.Exists(path))
            {
                Directory.Delete(path, true);
            }
        }
        catch
        {
            // Temporary installer extraction cleanup is best-effort only.
        }
    }
}
