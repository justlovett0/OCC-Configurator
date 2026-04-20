using Nefarius.ViGEm.Client.Targets;
using Nefarius.ViGEm.Client.Targets.Xbox360;
using OccBridge.Core.Models;

namespace OccBridge.Core.Bridge;

public static class CloneHeroMapper
{
    public static void Apply(IXbox360Controller controller, OccState state)
    {
        controller.ResetReport();

        controller.SetButtonState(Xbox360Button.A, state.IsPressed(OccButtonMasks.Green));
        controller.SetButtonState(Xbox360Button.B, state.IsPressed(OccButtonMasks.Red));
        controller.SetButtonState(Xbox360Button.Y, state.IsPressed(OccButtonMasks.Yellow));
        controller.SetButtonState(Xbox360Button.X, state.IsPressed(OccButtonMasks.Blue));
        controller.SetButtonState(Xbox360Button.LeftShoulder, state.IsPressed(OccButtonMasks.Orange));

        controller.SetButtonState(Xbox360Button.Up, state.IsPressed(OccButtonMasks.DPadUp));
        controller.SetButtonState(Xbox360Button.Down, state.IsPressed(OccButtonMasks.DPadDown));
        controller.SetButtonState(Xbox360Button.Left, state.IsPressed(OccButtonMasks.DPadLeft));
        controller.SetButtonState(Xbox360Button.Right, state.IsPressed(OccButtonMasks.DPadRight));

        controller.SetButtonState(Xbox360Button.Start, state.IsPressed(OccButtonMasks.Start));
        controller.SetButtonState(Xbox360Button.Back, state.IsPressed(OccButtonMasks.Select));
        controller.SetButtonState(Xbox360Button.Guide, state.IsPressed(OccButtonMasks.Guide));

        controller.SetSliderValue(Xbox360Slider.LeftTrigger, 0);
        controller.SetSliderValue(Xbox360Slider.RightTrigger, 0);

        controller.SetAxisValue(Xbox360Axis.LeftThumbX, 0);
        controller.SetAxisValue(Xbox360Axis.LeftThumbY, 0);
        controller.SetAxisValue(Xbox360Axis.RightThumbX, state.WhammyAxis);
        controller.SetAxisValue(Xbox360Axis.RightThumbY, NormalizeTiltAxis(state.TiltAxis));

        controller.SubmitReport();
    }

    private static short NormalizeTiltAxis(short tiltAxis)
    {
        if (tiltAxis <= 0)
        {
            return 0;
        }

        return tiltAxis;
    }
}
