namespace OccBridge.Core.Diagnostics;

public sealed class FileLog
{
    private const string TimestampFormat = "yyyy-MM-dd HH:mm:ss zzz";
    private static readonly TimeSpan RetentionWindow = TimeSpan.FromDays(1);
    private static readonly TimeSpan PruneInterval = TimeSpan.FromMinutes(15);

    private readonly string _logPath;
    private readonly object _sync = new();
    private DateTimeOffset _nextPruneAt = DateTimeOffset.MinValue;

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
        var now = DateTimeOffset.Now;
        var line = $"{now.ToString(TimestampFormat)} [{level}] {message}";

        lock (_sync)
        {
            TryPruneExpiredEntries(now);
            File.AppendAllLines(_logPath, new[] { line });
        }

        MessageLogged?.Invoke(line);
    }

    private void TryPruneExpiredEntries(DateTimeOffset now)
    {
        if (now < _nextPruneAt || !File.Exists(_logPath))
        {
            return;
        }

        try
        {
            var cutoff = now - RetentionWindow;
            var retainedLines = File
                .ReadLines(_logPath)
                .Where(line => ShouldRetain(line, cutoff))
                .ToArray();

            File.WriteAllLines(_logPath, retainedLines);
        }
        catch
        {
            // Logging should remain best-effort. If pruning fails, keep appending.
        }
        finally
        {
            _nextPruneAt = now + PruneInterval;
        }
    }

    private static bool ShouldRetain(string line, DateTimeOffset cutoff)
    {
        var bracketIndex = line.IndexOf(" [", StringComparison.Ordinal);
        if (bracketIndex <= 0)
        {
            return true;
        }

        var timestamp = line[..bracketIndex];
        return !DateTimeOffset.TryParseExact(
                   timestamp,
                   TimestampFormat,
                   null,
                   System.Globalization.DateTimeStyles.None,
                   out var parsedTimestamp)
               || parsedTimestamp >= cutoff;
    }
}
