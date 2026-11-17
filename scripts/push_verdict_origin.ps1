# Point ohush.co/verdict at the current lab tunnel (same farm password).
# Prereqs: firebase login; farm_episode_viewer on :3020; scripts/verdict.ps1 (or cloudflared) running.
#
#   .\scripts\push_verdict_origin.ps1
#   .\scripts\push_verdict_origin.ps1 -Url https://….trycloudflare.com

param(
  [string]$Url = "",
  [string]$Project = "hushdev"
)

$ErrorActionPreference = "Stop"
$urlFile = "C:\OHushData\indexes\farm_labels\audit\verdict_tunnel_url.txt"

if (-not $Url) {
  if (Test-Path $urlFile) {
    $Url = (Get-Content $urlFile -Raw).Trim()
  }
}
if (-not $Url) {
  throw "Pass -Url or start a tunnel first (scripts/verdict.ps1 writes $urlFile)."
}
$Url = $Url.TrimEnd("/")
Write-Host "OHUSH_VERDICT_ORIGIN=$Url"

$tmp = Join-Path $env:TEMP "ohush_verdict_origin.txt"
Set-Content -Path $tmp -Value $Url -NoNewline

# Prefer npx firebase-tools so PATH firebase is optional.
npx -y firebase-tools@latest apphosting:secrets:set OHUSH_VERDICT_ORIGIN `
  --project $Project `
  --data-file $tmp

Write-Host ""
Write-Host "Secret updated. If App Hosting does not pick it up within a minute, roll the backend in Firebase console."
Write-Host "Open https://ohush.co/verdict  (same password as /farm)."
Write-Host "Desk: https://ohush.co/verdict/dashboard"
