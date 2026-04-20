$ErrorActionPreference = "Stop"

$projectRoot = "C:\Users\zuoyi\Desktop\Dev\bilisub"
$serverRoot = Join-Path $projectRoot "server"
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$stdoutLog = Join-Path $projectRoot "bilisub-server.out.log"
$stderrLog = Join-Path $projectRoot "bilisub-server.err.log"
$hostAddress = "127.0.0.1"
$port = 8765

if (-not (Test-Path $pythonExe)) {
  throw "Python executable not found: $pythonExe"
}

$listening = Get-NetTCPConnection -LocalAddress $hostAddress -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listening) {
  exit 0
}

Start-Process `
  -FilePath $pythonExe `
  -ArgumentList "-m", "uvicorn", "app:app", "--host", $hostAddress, "--port", "$port" `
  -WorkingDirectory $serverRoot `
  -WindowStyle Hidden `
  -RedirectStandardOutput $stdoutLog `
  -RedirectStandardError $stderrLog
