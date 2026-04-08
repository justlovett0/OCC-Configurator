using System.Text.Json;
using OccBridge.Core.Models;

namespace OccBridge.Core.Configuration;

public sealed class AppConfigurationStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };

    private readonly string _configPath;

    public AppConfigurationStore(string? baseDirectory = null)
    {
        var root = baseDirectory ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "OCC",
            "OccBridge");

        Directory.CreateDirectory(root);
        _configPath = Path.Combine(root, "appsettings.json");
    }

    public string ConfigPath => _configPath;

    public AppConfiguration Load()
    {
        if (!File.Exists(_configPath))
        {
            return AppConfiguration.CreateDefault();
        }

        try
        {
            using var stream = File.OpenRead(_configPath);
            return JsonSerializer.Deserialize<AppConfiguration>(stream, JsonOptions)
                   ?? AppConfiguration.CreateDefault();
        }
        catch
        {
            return AppConfiguration.CreateDefault();
        }
    }

    public void Save(AppConfiguration configuration)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(_configPath)!);
        using var stream = File.Create(_configPath);
        JsonSerializer.Serialize(stream, configuration, JsonOptions);
    }
}
