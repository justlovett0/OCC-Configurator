using OccBridge.Core.Models;

namespace OccBridge.Core.Input;

public static class OccReportParser
{
    public static bool TryParse(ReadOnlySpan<byte> report, out OccState state)
    {
        state = new OccState();

        if (report.Length < 12)
        {
            return false;
        }

        var offset = report.Length >= 13 && report[0] == 0x01 ? 1 : 0;

        if (report.Length - offset < 12)
        {
            return false;
        }

        state = new OccState
        {
            Buttons = BitConverter.ToUInt16(report.Slice(offset, 2)),
            LeftTrigger = report[offset + 2],
            RightTrigger = report[offset + 3],
            LeftStickX = BitConverter.ToInt16(report.Slice(offset + 4, 2)),
            LeftStickY = BitConverter.ToInt16(report.Slice(offset + 6, 2)),
            RightStickX = BitConverter.ToInt16(report.Slice(offset + 8, 2)),
            RightStickY = BitConverter.ToInt16(report.Slice(offset + 10, 2)),
            TimestampUtc = DateTimeOffset.UtcNow,
        };

        return true;
    }
}
