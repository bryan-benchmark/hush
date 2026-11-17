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
Write-Host "When the https URL prints:  .\scripts\push_verdict_origin.ps1 -Url <that-url>"
Write-Host "Then open https://ohush.co/verdict  (same password as /farm) · desk /verdict/dashboard"

$urlFile = "C:\OHushData\indexes\farm_labels\audit\verdict_tunnel_url.txt"
New-Item -ItemType Directory -Force -Path (Split-Path $urlFile) | Out-Null

# Capture stderr+stdout so we can remember the quick-tunnel URL for push_verdict_origin.ps1
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $exe
$psi.Arguments = "tunnel --url http://127.0.0.1:3020"
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $false
$p = [System.Diagnostics.Process]::Start($psi)
$writer = {
  param($stream, $urlPath)
  while ($null -ne ($line = $stream.ReadLine())) {
    Write-Host $line
    if ($line -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
      Set-Content -Path $urlPath -Value $Matches[0] -NoNewline
      Write-Host "Saved tunnel URL -> $urlPath"
      Write-Host "Next:  .\scripts\push_verdict_origin.ps1"
    }
  }
}
$outJob = Start-Job -ScriptBlock $writer -ArgumentList $p.StandardOutput, $urlFile
$errJob = Start-Job -ScriptBlock $writer -ArgumentList $p.StandardError, $urlFile
try {
  $p.WaitForExit()
} finally {
  Receive-Job $outJob -EA SilentlyContinue | Out-Null
  Receive-Job $errJob -EA SilentlyContinue | Out-Null
  Stop-Job $outJob, $errJob -EA SilentlyContinue
  Remove-Job $outJob, $errJob -Force -EA SilentlyContinue
}
