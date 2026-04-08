namespace OccBridge.Core.Models;

public sealed class PrerequisiteSummary
{
    public required PrerequisiteStatus ViGEmBus { get; init; }

    public required PrerequisiteStatus HidHide { get; init; }

    public bool CanBridge => ViGEmBus.IsOperational;

    public bool CanHide => HidHide.IsOperational;
}
