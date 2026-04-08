namespace OccBridge.Core.Diagnostics;

public sealed class FileLog
{
    private readonly string _logPath;
    private readonly object _sync = new();

    public FileLog(string? baseDirectory = null)
    {
        var root = baseDirectory ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "OCC",
            "OccBridge",
            "Logs");

        Directory.CreateDirectory(root);
        _logPath = Path.Combine(root, "occbridge.log");
    }

    public string LogPath => _logPath;

    public event Action<string>? MessageLogged;

    public void Info(string message) => Write("INFO", message);

    public void Warn(string message) => Write("WARN", message);

    public void Error(string message) => Write("ERROR", message);

    public void Exception(string context, Exception exception)
    {
        Write("ERROR", $"{context}: {exception.GetType().Name}: {exception.Message}");
    }

    private void Write(string level, string message)
    {
        var line = $"{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss zzz} [{level}] {message}";

        lock (_sync)
        {
            File.AppendAllLines(_logPath, new[] { line });
        }

        MessageLogged?.Invoke(line);
    }
}
