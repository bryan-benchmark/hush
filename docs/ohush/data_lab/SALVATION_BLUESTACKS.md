# Salvation on BlueStacks

This is the login that reached the Streamers home screen on this PC. The instance was `Nougat32`. The app was `ar.tvplayer.tv` 5.1.0 (versionCode 5103).

Success is `ar.tvplayer.tv/.ui.MainActivity` with the welcome screen gone. Check it with:

```powershell
cd C:\Users\faceo\Projects\ohush
.\.venv\Scripts\Activate.ps1
python -m tools.windows_lab salvation status --instance Nougat32
```

`screen` is `home` when the instance is logged in.

## One command

The password lives only in `C:\OHushData\farm\salvation_login.json` (`service`, `username`, `password`, `playlist_name`). The repo does not contain it.

```powershell
python -m tools.windows_lab salvation login --instance Nougat32
```

That command starts the instance if ADB is down, opens Streamers, and walks the screens below. If the app is already on the home screen, it stops.

## 1. Start the instance

BlueStacks ADB on this machine is already on: `bst.enable_adb_access="1"` in `C:\ProgramData\BlueStacks_nxt\bluestacks.conf`. Remote ADB stays off.

```powershell
& "C:\Program Files\BlueStacks_nxt\HD-Player.exe" --instance Nougat32
```

The engine name is `Nougat32`. The window title is `BlueStacks App Player`. Android reports 7.1.2, model `SM-G988N`, screen 1600x900.

## 2. Connect ADB

`Nougat32` listens on port 5555.

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" connect 127.0.0.1:5555
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" devices -l
```

The line must say `127.0.0.1:5555    device`. `offline` means the instance is still booting. Connect again after a few seconds.

The lab command uses `C:\Program Files\BlueStacks_nxt\HD-Adb.exe` when that file is present, and the same serial `127.0.0.1:5555`.

## 3. Open Streamers

```powershell
adb -s 127.0.0.1:5555 shell monkey -p ar.tvplayer.tv -c android.intent.category.LAUNCHER 1
```

The first activity is `com.andyhax.haxsplash.LaunchActivity`. Wait until the focus moves on.

Three screens are possible:

| What you see | Activity | What to do |
|---|---|---|
| Welcome, with **Add playlist** and **Settings** | `MainActivity` | Continue at step 4 |
| Service list, with **Salvation** and **Cancel** | `PlaylistWizardActivity` | Continue at step 5 |
| Channel home, welcome gone | `MainActivity` | Already logged in. Stop |

Confirm the build if the service list is missing:

```powershell
adb -s 127.0.0.1:5555 shell dumpsys package ar.tvplayer.tv | Select-String "versionName=|versionCode="
```

The working build is `versionName=5.1.0` and `versionCode=5103`.

## 4. Add playlist

Tap **Add playlist**. The focus becomes:

`ar.tvplayer.tv/.settings.ui.playlists.wizard.PlaylistWizardActivity`

## 5. Choose Salvation

The left title is **Service**. The rows include **Salvation** and **Cancel**.

Tap the **Salvation** row. Do not type into a server box. Salvation is a built-in service. The next page is the Xtream Codes login, and the server line already reads Salvation.

## 6. Username

Tap the **Username** row. The keyboard opens (`mInputShown=true`).

Type the username from the login file, then commit with Enter:

```powershell
adb -s 127.0.0.1:5555 shell input text USERNAME
adb -s 127.0.0.1:5555 shell input keyevent 66
```

A value line appears under the Username label. The rows below it move up. The password coordinates from before this commit are now wrong.

## 7. Password

Read the screen again and tap the **Password** row at its new position. The keyboard opens.

Type the password from the login file, then Enter (`keyevent 66`). A value line appears under Password. On this account that line is 8 characters. The username line is still there.

Tapping the old Password position hits the option row underneath it, and the password is not saved.

## 8. Next

Tap **Next**. The wizard stays in `PlaylistWizardActivity` and shows **Playlist name**, **Done**, and **Back**.

## 9. Playlist name

Any name works. This run used `ohush`.

Tap **Playlist name**, type the name, then Enter. The name appears under the label.

## 10. Done

Tap **Done**.

The first tap can leave the page on Playlist name. Tap **Done** again. The focus becomes `ar.tvplayer.tv/.ui.MainActivity`, and the welcome screen with **Add playlist** is gone. That is the logged-in app.

## Check

```powershell
python -m tools.windows_lab salvation status --instance Nougat32
```

`ok` is true and `screen` is `home`.

## Another instance

Clone `Nougat32` in BlueStacks Multi-Instance Manager. Boot the clone once, then:

```powershell
python -m tools.windows_lab instances discover
python -m tools.windows_lab salvation login --instance THE_CLONE_NAME
```

Each clone has its own ADB port. The same login file is used. A recording time is stored with:

```powershell
python -m tools.windows_lab salvation record-add --instance Nougat32 --channel CHANNEL --at 2026-11-16T20:00:00-05:00 --minutes 180
python -m tools.windows_lab salvation record-list
```

The job records the channel name and the clock time. The taps that open that channel inside the home screen are not part of this login. Those controls are in [`STREAMERS_CONTROLS.md`](STREAMERS_CONTROLS.md).
