# Expose the local episode verdict viewer (:3020) so ohush.co/verdict can proxy it.
# Keep this computer on. Paste the printed https URL into OHUSH_VERDICT_ORIGIN
# (Firebase secret, or apps/monitor/.env.local for a local monitor).

$ErrorActionPreference = "Stop"
$exeDir = Join-Path $env:LOCALAPPDATA "ohush"
$exe = Join-Path $exeDir "cloudflared.exe"
if (-not (Test-Path $exe)) {
  New-Item -ItemType Directory -Force -Path $exeDir | Out-Null
  Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $exe
}

Write-Host "Tunneling http://127.0.0.1:3020  (farm_episode_viewer must already be running)"
Write-Host "Set OHUSH_VERDICT_ORIGIN to the https URL printed below, then open https://ohush.co/verdict"
& $exe tunnel --url http://127.0.0.1:3020
