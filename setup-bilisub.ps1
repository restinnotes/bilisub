$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $projectRoot ".venv"
$pythonExe = Join-Path $venvDir "Scripts\python.exe"
$requirementsFile = Join-Path $projectRoot "server\requirements.txt"
$startupScript = Join-Path $projectRoot "start-bilisub-server.ps1"

function Find-SystemPython {
  $commands = @("py", "python")
  foreach ($command in $commands) {
    try {
      $cmd = Get-Command $command -ErrorAction Stop
      if ($cmd) {
        return $command
      }
    } catch {}
  }
  return $null
}

Write-Host ""
Write-Host "BiliSub setup is starting..." -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $pythonExe)) {
  $systemPython = Find-SystemPython
  if (-not $systemPython) {
    throw "Python was not found. Please install Python 3.10+ first, then run this script again."
  }

  Write-Host "Creating virtual environment..." -ForegroundColor Yellow
  if ($systemPython -eq "py") {
    & py -3 -m venv $venvDir
  } else {
    & python -m venv $venvDir
  }
}

Write-Host "Installing / updating dependencies..." -ForegroundColor Yellow
& $pythonExe -m pip install -r $requirementsFile

try {
  $null = Get-Command ffmpeg -ErrorAction Stop
  Write-Host "ffmpeg detected." -ForegroundColor Green
} catch {
  Write-Host "Warning: ffmpeg was not found in PATH. The server may start, but subtitle generation will fail until ffmpeg is installed." -ForegroundColor Red
}

Write-Host "Starting local server..." -ForegroundColor Yellow
& $startupScript

Start-Sleep -Seconds 3

try {
  $health = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/health -TimeoutSec 5
  Write-Host ""
  Write-Host "BiliSub server is ready." -ForegroundColor Green
  Write-Host ""
  Write-Host "Next step:" -ForegroundColor Cyan
  Write-Host "1. Open chrome://extensions"
  Write-Host "2. Turn on Developer mode"
  Write-Host "3. Click 'Load unpacked' and choose the extension folder:"
  Write-Host "   $projectRoot\extension"
  Write-Host ""
  Write-Host "After that, open any Bilibili video page and click the 'AI字幕' button in the player." -ForegroundColor Cyan
} catch {
  Write-Host ""
  Write-Host "Setup finished, but the health check failed." -ForegroundColor Red
  Write-Host "Try running this file once more, or inspect bilisub-server.err.log in the project root." -ForegroundColor Yellow
}

Write-Host ""
Read-Host "Press Enter to close"
