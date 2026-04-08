# OCC Windows Bridge

This folder contains the C# Windows bridge for OCC Bluetooth guitars plus the packaging pipeline that builds a single distributable `OCCBridgeSetup.exe`.

## Projects

- `OccBridge.Core`
  Shared bridge logic, configuration, prerequisite checks, HID input parsing, ViGEmBus output, and HidHide integration.
- `OccBridge.App`
  WinForms tray-oriented bridge app for binding an OCC controller and starting or stopping the virtual Xbox 360 bridge.
- `OccBridge.Install`
  WinForms prerequisite repair utility. It embeds the bundled ViGEmBus and HidHide installers and can relaunch them visibly with elevation.
- `OccBridge.Package`
  WiX v4 MSI project that installs the published bridge files under `Program Files\OCC\OccBridge`.
- `OccBridge.Bundle`
  WiX v4 Burn bundle that chains ViGEmBus, HidHide, and the OCC Bridge MSI into one offline `OCCBridgeSetup.exe`.

## Current Behavior

- Enumerates HID devices and lets the user bind one controller manually.
- Persists the selected controller under `%LOCALAPPDATA%\OCC\OccBridge\appsettings.json`.
- Detects ViGEmBus and HidHide at runtime.
- Starts a reconnect loop that waits for the bound controller and mirrors its HID reports into a virtual Xbox 360 controller.
- Uses HidHide when available to hide the physical controller instance from games.
- Supports per-user startup registration through the current user `Run` key.
- Provides one-command packaging for a per-machine installer bundle.

## Build

For normal source builds, enter this with your directory:

```powershell
dotnet build "....OCC\Source Code\windows-bridge\OccBridge.slnx" -c Release
```

To build the distributable setup bundle, enter this with your directory:

```powershell
powershell -ExecutionPolicy Bypass -File "....\OCC\Source Code\windows-bridge\build\Publish-OCCBridgeSetup.ps1"
```

## Prerequisite Inputs

Place these vetted prerequisite installers in `OccBridge.Install\Prerequisites\` before running the packaging script:

- `ViGEmBus_1.22.0.exe`
- `HidHide_1.5.230.exe`

`OccBridge.Install.exe` embeds these installers at publish time, so the installed repair utility does not depend on an on-disk `Prerequisites` folder.

## Artifact Outputs

The packaging script produces:

- `artifacts\publish\OccBridge.App\OccBridge.App.exe`
- `artifacts\publish\OccBridge.Install\OccBridge.Install.exe`
- `artifacts\installer\OccBridge.Package.msi`
- `artifacts\bundle\OCCBridgeSetup.exe`

`OCCBridgeSetup.exe` is the offline file intended for end users.

## Install and Uninstall Notes

- The bundle installs OCC Bridge per-machine under `Program Files\OCC\OccBridge`.
- ViGEmBus is treated as required, and HidHide is treated as recommended.
- `OCCBridgeSetup.exe` checks for existing ViGEmBus and HidHide driver-service registrations before launching those bundled installers, and skips the sub-installer when the driver is already present.
- Uninstalling OCC Bridge removes the OCC Bridge files but leaves ViGEmBus and HidHide installed by default because they are shared system drivers.
- Code signing is not part of this repo yet, so Windows SmartScreen may warn on unsigned binaries.

## Notes

- This is a v1 bridge scaffold focused on Clone Hero and one OCC Bluetooth controller.
- The HID parser currently assumes the OCC BLE report layout already used by the firmware: report ID `0x01` plus XInput-like buttons, triggers, and stick axes.
- ViGEmBus is treated as a fixed prerequisite because the project is archived.
