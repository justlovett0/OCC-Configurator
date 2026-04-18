namespace OccBridge.Core.Models;

public sealed class OccState
{
    public ushort Buttons { get; init; }

    public byte LeftTrigger { get; init; }

    public byte RightTrigger { get; init; }

    public short LeftStickX { get; init; }

    public short LeftStickY { get; init; }

    public short RightStickX { get; init; }

    public short RightStickY { get; init; }

    public DateTimeOffset TimestampUtc { get; init; } = DateTimeOffset.UtcNow;

    public bool IsPressed(ushort mask) => (Buttons & mask) != 0;

    public short WhammyAxis => LeftStickX;

    public short TiltAxis => RightStickY;
}
