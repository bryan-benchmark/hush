# Point ohush.co/verdict at the current lab tunnel.
# Bakes the URL into git (App Hosting deploy). Preferred over the stale Firebase secret.
#
#   .\scripts\verdict.ps1
#   .\scripts\push_verdict_origin.ps1
#   .\scripts\push_verdict_origin.ps1 -Url https://….trycloudflare.com

param(
  [string]$Url = "",
  [switch]$SkipCommit,
  [switch]$SkipPush,
  [string]$Project = "hushdev"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$urlFile = "C:\OHushData\indexes\farm_labels\audit\verdict_tunnel_url.txt"
$published = Join-Path $repo "apps\monitor\src\lib\verdictOrigin.published.ts"

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

$ts = @"
/**
 * Lab tunnel URL baked into the App Hosting deploy.
 * Quick tunnels change often — update this file + push when scripts/verdict.ps1 prints a new URL
 * (preferred over the stale OHUSH_VERDICT_ORIGIN secret).
 */
export const PUBLISHED_VERDICT_ORIGIN =
  "$Url";
"@
Set-Content -Path $published -Value $ts -NoNewline
Write-Host "Updated $published"

$envLocal = Join-Path $repo "apps\monitor\.env.local"
if (Test-Path $envLocal) {
  $t = Get-Content $envLocal -Raw
  if ($t -match "OHUSH_VERDICT_ORIGIN=") {
    $t = $t -replace "OHUSH_VERDICT_ORIGIN=.*", "OHUSH_VERDICT_ORIGIN=$Url"
  } else {
    $t = $t.TrimEnd() + "`nOHUSH_VERDICT_ORIGIN=$Url`n"
  }
  Set-Content -Path $envLocal -Value $t -NoNewline
}

if (-not $SkipCommit) {
  Push-Location $repo
  try {
    git add -- "apps/monitor/src/lib/verdictOrigin.published.ts"
    $pending = git diff --cached --name-only
    if ($pending) {
      git commit -m "Point ohush.co/verdict at the current lab tunnel."
      if (-not $SkipPush) {
        git push origin HEAD
        $branch = (git rev-parse --abbrev-ref HEAD).Trim()
        if ($branch -ne "main") {
          Write-Host "Also updating origin/main for App Hosting…"
          git push origin "HEAD:main"
        }
      }
    } else {
      Write-Host "published file unchanged"
    }
  } finally {
    Pop-Location
  }
}

$tmp = Join-Path $env:TEMP "ohush_verdict_origin.txt"
Set-Content -Path $tmp -Value $Url -NoNewline
try {
  npx -y firebase-tools@latest apphosting:secrets:set OHUSH_VERDICT_ORIGIN `
    --project $Project `
    --data-file $tmp 2>&1 | Write-Host
} catch {
  Write-Host "Secret update skipped (firebase login). Published git URL is enough after deploy."
}

Write-Host ""
Write-Host "Open https://ohush.co/verdict  (same password as /farm)."
Write-Host "Desk: https://ohush.co/verdict/dashboard"
