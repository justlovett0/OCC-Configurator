using HidSharp;
using OccBridge.Core.Diagnostics;
using OccBridge.Core.Models;
using Windows.Gaming.Input;

namespace OccBridge.Core.Input;

public sealed class PhysicalInputService
{
    private readonly FileLog _log;
    private string? _lastLoggedRawAxisSignature;

    public PhysicalInputService(FileLog log)
    {
        _log = log;
    }

    public async Task<bool> ReadUntilDisconnectAsync(
        DeviceCandidate candidate,
        Func<OccState, Task> onState,
        CancellationToken cancellationToken)
    {
        return candidate.Backend switch
        {
            ControllerBackend.Hid => await ReadHidUntilDisconnectAsync(candidate, onState, cancellationToken).ConfigureAwait(false),
            ControllerBackend.WinRtGamepad => await ReadGamepadUntilDisconnectAsync(candidate, onState, cancellationToken).ConfigureAwait(false),
            ControllerBackend.WinRtRawGameController => await ReadRawGameControllerUntilDisconnectAsync(candidate, onState, cancellationToken).ConfigureAwait(false),
            _ => false,
        };
    }

    private async Task<bool> ReadHidUntilDisconnectAsync(
        DeviceCandidate candidate,
        Func<OccState, Task> onState,
        CancellationToken cancellationToken)
    {
        var hidDevice = DeviceList.Local.GetHidDevices()
            .FirstOrDefault(device => string.Equals(device.DevicePath, candidate.DevicePath, StringComparison.OrdinalIgnoreCase));

        if (hidDevice is null)
        {
            return false;
        }

        if (!hidDevice.TryOpen(out HidStream? stream))
        {
            _log.Warn($"Failed to open HID stream for {candidate.ProductName}.");
            return false;
        }

        using var streamScope = stream;
        using var registration = cancellationToken.Register(() =>
        {
            try
            {
                stream.Close();
            }
            catch
            {
                // ignored
            }
        });

        var buffer = new byte[Math.Max(hidDevice.GetMaxInputReportLength(), 16)];
        _log.Info($"Opened physical HID controller: {candidate.ProductName}");

        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                int count;

                try
                {
                    count = await Task.Run(() => stream.Read(buffer, 0, buffer.Length), cancellationToken)
                        .ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (IOException)
                {
                    return false;
                }
                catch (ObjectDisposedException)
                {
                    return false;
                }

                if (count <= 0)
                {
                    continue;
                }

                if (OccReportParser.TryParse(buffer.AsSpan(0, count), out var state))
                {
                    await onState(state).ConfigureAwait(false);
                }
            }
        }
        finally
        {
            _log.Info($"Closed physical HID controller: {candidate.ProductName}");
        }

        return true;
    }

    private async Task<bool> ReadGamepadUntilDisconnectAsync(
        DeviceCandidate candidate,
        Func<OccState, Task> onState,
        CancellationToken cancellationToken)
    {
        var gamepad = TryFindGamepad(candidate);
        if (gamepad is null)
        {
            _log.Warn($"Failed to find Gamepad API controller for {candidate.ProductName}.");
            return false;
        }

        _log.Info($"Opened Gamepad API controller: {candidate.ProductName}");

        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var current = TryFindGamepad(candidate);
                if (current is null)
                {
                    return false;
                }

                var reading = current.GetCurrentReading();
                await onState(MapGamepadReading(reading)).ConfigureAwait(false);
                await Task.Delay(8, cancellationToken).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException)
        {
        }
        finally
        {
            _log.Info($"Closed Gamepad API controller: {candidate.ProductName}");
        }

        return true;
    }

    private async Task<bool> ReadRawGameControllerUntilDisconnectAsync(
        DeviceCandidate candidate,
        Func<OccState, Task> onState,
        CancellationToken cancellationToken)
    {
        var controller = TryFindRawGameController(candidate);
        if (controller is null)
        {
            _log.Warn($"Failed to find Raw Game Controller API controller for {candidate.ProductName}.");
            return false;
        }

        var buttons = new bool[controller.ButtonCount];
        var switches = new GameControllerSwitchPosition[controller.SwitchCount];
        var axes = new double[controller.AxisCount];

        _log.Info($"Opened Raw Game Controller API controller: {candidate.ProductName}");
        LogRawControllerCapabilities(controller);

        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var current = TryFindRawGameController(candidate);
                if (current is null)
                {
                    return false;
                }

                if (buttons.Length != current.ButtonCount)
                {
                    buttons = new bool[current.ButtonCount];
                }

                if (switches.Length != current.SwitchCount)
                {
                    switches = new GameControllerSwitchPosition[current.SwitchCount];
                }

                if (axes.Length != current.AxisCount)
                {
                    axes = new double[current.AxisCount];
                }

                current.GetCurrentReading(buttons, switches, axes);
                var state = MapRawGameControllerReading(current, buttons, switches, axes);
                LogRawAxisSampleIfNeeded(current, axes, state);
                await onState(state).ConfigureAwait(false);
                await Task.Delay(8, cancellationToken).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException)
        {
        }
        finally
        {
            _log.Info($"Closed Raw Game Controller API controller: {candidate.ProductName}");
        }

        return true;
    }

    private void LogRawAxisSampleIfNeeded(
        RawGameController controller,
        IReadOnlyList<double> axes,
        OccState state)
    {
        if (!IsBtGuitarRawController(controller) || axes.Count < 6)
        {
            return;
        }

        var signature =
            $"{Math.Round(axes[3], 2):0.00}|{Math.Round(axes[5], 2):0.00}|{state.LeftStickX}|{state.RightStickY}";

        if (string.Equals(signature, _lastLoggedRawAxisSignature, StringComparison.Ordinal))
        {
            return;
        }

        _lastLoggedRawAxisSignature = signature;
        _log.Info(
            $"Raw BT axis sample: axes=[{axes[0]:0.00}, {axes[1]:0.00}, {axes[2]:0.00}, {axes[3]:0.00}, {axes[4]:0.00}, {axes[5]:0.00}] -> OccState LX={state.LeftStickX}, LY={state.LeftStickY}, RX={state.RightStickX}, RY={state.RightStickY}");
    }

    private void LogRawControllerCapabilities(RawGameController controller)
    {
        _log.Info(
            $"Raw controller capabilities: DisplayName='{controller.DisplayName}', VID={controller.HardwareVendorId:X4}, PID={controller.HardwareProductId:X4}, Buttons={controller.ButtonCount}, Switches={controller.SwitchCount}, Axes={controller.AxisCount}, Wireless={controller.IsWireless}");

        for (var index = 0; index < controller.ButtonCount; index++)
        {
            _log.Info($"Raw controller button label {index}: {controller.GetButtonLabel(index)}");
        }

        for (var index = 0; index < controller.SwitchCount; index++)
        {
            _log.Info($"Raw controller switch kind {index}: {controller.GetSwitchKind(index)}");
        }
    }

    private static Gamepad? TryFindGamepad(DeviceCandidate candidate)
    {
        return Gamepad.Gamepads.FirstOrDefault(gamepad =>
        {
            var raw = RawGameController.FromGameController(gamepad);
            return raw is not null && ControllerMatches(candidate, raw);
        });
    }

    private static RawGameController? TryFindRawGameController(DeviceCandidate candidate)
    {
        return RawGameController.RawGameControllers.FirstOrDefault(controller => ControllerMatches(candidate, controller));
    }

    private static bool ControllerMatches(DeviceCandidate candidate, RawGameController controller)
    {
        if (!string.IsNullOrWhiteSpace(candidate.RuntimeInstanceId) &&
            string.Equals(candidate.RuntimeInstanceId, controller.NonRoamableId, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        if (!string.IsNullOrWhiteSpace(candidate.InstanceId) &&
            string.Equals(candidate.InstanceId, controller.NonRoamableId, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        return candidate.VendorId == controller.HardwareVendorId &&
               candidate.ProductId == controller.HardwareProductId &&
               string.Equals(candidate.ProductName, controller.DisplayName, StringComparison.OrdinalIgnoreCase);
    }

    private static OccState MapGamepadReading(GamepadReading reading)
    {
        ushort buttons = 0;

        if (reading.Buttons.HasFlag(GamepadButtons.DPadUp)) buttons |= OccButtonMasks.DPadUp;
        if (reading.Buttons.HasFlag(GamepadButtons.DPadDown)) buttons |= OccButtonMasks.DPadDown;
        if (reading.Buttons.HasFlag(GamepadButtons.DPadLeft)) buttons |= OccButtonMasks.DPadLeft;
        if (reading.Buttons.HasFlag(GamepadButtons.DPadRight)) buttons |= OccButtonMasks.DPadRight;
        if (reading.Buttons.HasFlag(GamepadButtons.Menu)) buttons |= OccButtonMasks.Start;
        if (reading.Buttons.HasFlag(GamepadButtons.View)) buttons |= OccButtonMasks.Select;
        if (reading.Buttons.HasFlag(GamepadButtons.A)) buttons |= OccButtonMasks.Green;
        if (reading.Buttons.HasFlag(GamepadButtons.B)) buttons |= OccButtonMasks.Red;
        if (reading.Buttons.HasFlag(GamepadButtons.X)) buttons |= OccButtonMasks.Blue;
        if (reading.Buttons.HasFlag(GamepadButtons.Y)) buttons |= OccButtonMasks.Yellow;
        if (reading.Buttons.HasFlag(GamepadButtons.LeftShoulder)) buttons |= OccButtonMasks.Orange;

        return new OccState
        {
            Buttons = buttons,
            LeftTrigger = NormalizeUnsignedAxis(reading.LeftTrigger),
            RightTrigger = NormalizeUnsignedAxis(reading.RightTrigger),
            LeftStickX = NormalizeSignedAxis(reading.LeftThumbstickX),
            LeftStickY = NormalizeSignedAxis(reading.LeftThumbstickY),
            RightStickX = NormalizeSignedAxis(reading.RightThumbstickX),
            RightStickY = NormalizeSignedAxis(reading.RightThumbstickY),
            TimestampUtc = DateTimeOffset.UtcNow,
        };
    }

    private static OccState MapRawGameControllerReading(
        RawGameController controller,
        IReadOnlyList<bool> buttons,
        IReadOnlyList<GameControllerSwitchPosition> switches,
        IReadOnlyList<double> axes)
    {
        ushort mappedButtons = 0;
        var hasNamedButtons = false;

        for (var index = 0; index < buttons.Count; index++)
        {
            if (!buttons[index])
            {
                continue;
            }

            var label = controller.GetButtonLabel(index).ToString();
            if (!string.Equals(label, "None", StringComparison.OrdinalIgnoreCase))
            {
                hasNamedButtons = true;
            }

            switch (label)
            {
                case "XboxUp":
                case "Up":
                    mappedButtons |= OccButtonMasks.DPadUp;
                    break;
                case "XboxDown":
                case "Down":
                    mappedButtons |= OccButtonMasks.DPadDown;
                    break;
                case "XboxLeft":
                case "Left":
                    mappedButtons |= OccButtonMasks.DPadLeft;
                    break;
                case "XboxRight":
                case "Right":
                    mappedButtons |= OccButtonMasks.DPadRight;
                    break;
                case "XboxStart":
                case "XboxMenu":
                case "Menu":
                    mappedButtons |= OccButtonMasks.Start;
                    break;
                case "XboxBack":
                case "XboxView":
                case "View":
                    mappedButtons |= OccButtonMasks.Select;
                    break;
                case "XboxA":
                case "LetterA":
                    mappedButtons |= OccButtonMasks.Green;
                    break;
                case "XboxB":
                case "LetterB":
                    mappedButtons |= OccButtonMasks.Red;
                    break;
                case "XboxX":
                case "LetterX":
                    mappedButtons |= OccButtonMasks.Blue;
                    break;
                case "XboxY":
                case "LetterY":
                    mappedButtons |= OccButtonMasks.Yellow;
                    break;
                case "XboxLeftBumper":
                case "LeftBumper":
                    mappedButtons |= OccButtonMasks.Orange;
                    break;
            }
        }

        var usedBtGuitarButtonFallback = !hasNamedButtons &&
            switches.Count == 0 &&
            buttons.Count >= 16 &&
            controller.HardwareVendorId == 0x045E &&
            controller.HardwareProductId == 0x028E;

        if (usedBtGuitarButtonFallback)
        {
            mappedButtons |= buttons[0] ? OccButtonMasks.DPadUp : (ushort)0;
            mappedButtons |= buttons[1] ? OccButtonMasks.DPadDown : (ushort)0;
            mappedButtons |= buttons[2] ? OccButtonMasks.DPadLeft : (ushort)0;
            mappedButtons |= buttons[3] ? OccButtonMasks.DPadRight : (ushort)0;
            mappedButtons |= buttons[4] ? OccButtonMasks.Start : (ushort)0;
            mappedButtons |= buttons[5] ? OccButtonMasks.Select : (ushort)0;
            mappedButtons |= buttons[8] ? OccButtonMasks.Orange : (ushort)0;
            mappedButtons |= buttons[10] ? OccButtonMasks.Guide : (ushort)0;
            mappedButtons |= buttons[12] ? OccButtonMasks.Green : (ushort)0;
            mappedButtons |= buttons[13] ? OccButtonMasks.Red : (ushort)0;
            mappedButtons |= buttons[14] ? OccButtonMasks.Blue : (ushort)0;
            mappedButtons |= buttons[15] ? OccButtonMasks.Yellow : (ushort)0;
        }
        else if (buttons.Count >= 9)
        {
            mappedButtons |= buttons[0] ? OccButtonMasks.Start : (ushort)0;
            mappedButtons |= buttons.Count > 1 && buttons[1] ? OccButtonMasks.Select : (ushort)0;
            mappedButtons |= buttons.Count > 4 && buttons[4] ? OccButtonMasks.Green : (ushort)0;
            mappedButtons |= buttons.Count > 5 && buttons[5] ? OccButtonMasks.Red : (ushort)0;
            mappedButtons |= buttons.Count > 6 && buttons[6] ? OccButtonMasks.Blue : (ushort)0;
            mappedButtons |= buttons.Count > 7 && buttons[7] ? OccButtonMasks.Yellow : (ushort)0;
            mappedButtons |= buttons.Count > 8 && buttons[8] ? OccButtonMasks.Orange : (ushort)0;
        }

        if (!usedBtGuitarButtonFallback && switches.Count == 0 && buttons.Count >= 14)
        {
            mappedButtons |= buttons[10] ? OccButtonMasks.DPadUp : (ushort)0;
            mappedButtons |= buttons[11] ? OccButtonMasks.DPadDown : (ushort)0;
            mappedButtons |= buttons[12] ? OccButtonMasks.DPadLeft : (ushort)0;
            mappedButtons |= buttons[13] ? OccButtonMasks.DPadRight : (ushort)0;
        }

        foreach (var switchPosition in switches)
        {
            switch (switchPosition)
            {
                case GameControllerSwitchPosition.Up:
                case GameControllerSwitchPosition.UpLeft:
                case GameControllerSwitchPosition.UpRight:
                    mappedButtons |= OccButtonMasks.DPadUp;
                    break;
                case GameControllerSwitchPosition.Down:
                case GameControllerSwitchPosition.DownLeft:
                case GameControllerSwitchPosition.DownRight:
                    mappedButtons |= OccButtonMasks.DPadDown;
                    break;
            }

            switch (switchPosition)
            {
                case GameControllerSwitchPosition.Left:
                case GameControllerSwitchPosition.UpLeft:
                case GameControllerSwitchPosition.DownLeft:
                    mappedButtons |= OccButtonMasks.DPadLeft;
                    break;
                case GameControllerSwitchPosition.Right:
                case GameControllerSwitchPosition.UpRight:
                case GameControllerSwitchPosition.DownRight:
                    mappedButtons |= OccButtonMasks.DPadRight;
                    break;
            }
        }

        if (IsBtGuitarRawController(controller))
        {
            return new OccState
            {
                Buttons = mappedButtons,
                LeftTrigger = 0,
                RightTrigger = 0,
                LeftStickX = NormalizeBtWhammyAxis(axes.Count > 3 ? axes[3] : 0d),
                LeftStickY = 0,
                RightStickX = 0,
                RightStickY = NormalizeBtTiltAxis(axes.Count > 5 ? axes[5] : 0d),
                TimestampUtc = DateTimeOffset.UtcNow,
            };
        }

        return new OccState
        {
            Buttons = mappedButtons,
            LeftTrigger = axes.Count > 0 ? NormalizeUnsignedAxis(axes[0]) : (byte)0,
            RightTrigger = axes.Count > 1 ? NormalizeUnsignedAxis(axes[1]) : (byte)0,
            LeftStickX = axes.Count > 2 ? NormalizeSignedAxis(axes[2]) : (short)0,
            LeftStickY = axes.Count > 3 ? NormalizeSignedAxis(axes[3]) : (short)0,
            RightStickX = axes.Count > 4 ? NormalizeSignedAxis(axes[4]) : (short)0,
            RightStickY = axes.Count > 5 ? NormalizeSignedAxis(axes[5]) : (short)0,
            TimestampUtc = DateTimeOffset.UtcNow,
        };
    }

    private static byte NormalizeUnsignedAxis(double value)
    {
        var clamped = Math.Clamp(value, 0d, 1d);
        return (byte)Math.Round(clamped * 255d);
    }

    private static short NormalizeSignedAxis(double value)
    {
        var clamped = Math.Clamp(value, -1d, 1d);
        return (short)Math.Round(clamped * short.MaxValue);
    }

    private static short NormalizeBtWhammyAxis(double value)
    {
        var clamped = Math.Clamp(value, 0d, 1d);
        return (short)Math.Round((clamped * 65535d) - 32768d);
    }

    private static short NormalizeBtTiltAxis(double value)
    {
        var clamped = Math.Clamp(value, 0d, 1d);
        return (short)Math.Round(clamped * short.MaxValue);
    }

    private static bool IsBtGuitarRawController(RawGameController controller)
    {
        return controller.HardwareVendorId == 0x045E &&
               controller.HardwareProductId == 0x028E &&
               controller.AxisCount >= 6 &&
               controller.ButtonCount >= 16 &&
               controller.SwitchCount == 0;
    }
}
