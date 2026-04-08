Place vetted prerequisite installers in this folder before publishing `OccBridge.Install`.

Expected filenames:

- `ViGEmBus_1.22.0.exe`
- `HidHide_1.5.230.exe`

The bootstrapper will present these installs visibly to the user and launch them with elevation only after the user confirms.
They are started directly as normal `.exe` installers, so the vendor installer UI remains visible.
