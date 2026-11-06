# Auto Edit installer for Windows. Safe to run again: it updates what's there.
# In PowerShell:  irm https://raw.githubusercontent.com/paolo-segura/auto-edit/main/install.ps1 | iex
# Pasted into a window, so it stops with `throw`, never `exit`: exit would close the window and hide the message.

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # the download progress bar makes Invoke-WebRequest many times slower

$Repo = if ($env:AUTO_EDIT_REPO) { $env:AUTO_EDIT_REPO } else { "https://github.com/paolo-segura/auto-edit.git" }
$Branch = if ($env:AUTO_EDIT_BRANCH) { $env:AUTO_EDIT_BRANCH } else { "main" }  # set it to try a branch before it's merged
$Dir = Join-Path $HOME ".auto-edit"
# Pinned downloads, checked by hash, so a changed file never runs here unnoticed.
$Whisper = @{
  Url = "https://github.com/ggml-org/whisper.cpp/releases/download/v1.9.2/whisper-bin-x64.zip"
  Sha256 = "49dcc16de826f20bd53d44f947a1ae49dfa81f86cad67a64d80820cb192d674a"
}
$MaskModel = @{
  Url = "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/1/selfie_multiclass_256x256.tflite"
  Sha256 = "c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0"
}

function Say($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Stop-Install($text) { throw "Install stopped: $text" }

# Native programs don't stop PowerShell when they fail, so check each one.
function Invoke-Step($what, [scriptblock]$command) {
  & $command
  if ($LASTEXITCODE) { Stop-Install "$what failed (exit code $LASTEXITCODE). See the lines above." }
}

function Update-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Get-Verified($file, $where) {
  $out = Join-Path $env:TEMP ([IO.Path]::GetFileName($file.Url))
  Invoke-WebRequest -Uri $file.Url -OutFile $out -UseBasicParsing
  if ((Get-FileHash $out -Algorithm SHA256).Hash -ne $file.Sha256) {
    Remove-Item $out
    Stop-Install "$($file.Url) didn't match its expected contents. Try again later."
  }
  Move-Item $out $where -Force
}

function Install-Package($id, [string[]]$extra) {
  winget.exe install --id $id --exact --silent --accept-package-agreements --accept-source-agreements @extra
  # 0x8A15002B: already installed, just not on this window's PATH yet.
  if ($LASTEXITCODE -and $LASTEXITCODE -ne -1978335189) { Stop-Install "Installing $id failed (exit code $LASTEXITCODE). See the lines above." }
  Update-Path
}

function Find-Python {
  # A missing version prints to stderr, which "Stop" would turn into a crash.
  $ErrorActionPreference = "Continue"
  foreach ($version in "-3.13", "-3.12") {
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
      $exe = & py.exe $version -c "import sys; print(sys.executable)" 2>$null
      if (-not $LASTEXITCODE -and $exe) { return $exe.Trim() }
    }
  }
  $local = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
  if (Test-Path $local) { return $local }
  return $null
}

Write-Host "Auto Edit installer. It takes 10 to 20 minutes and needs about 5 GB free."
if ($env:OS -ne "Windows_NT") { Stop-Install "this installer is for Windows. On a Mac, use install.sh." }
if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64") { Stop-Install "Windows on ARM isn't supported yet. This needs a 64-bit Intel or AMD PC." }
if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
  Stop-Install "winget is missing. Install 'App Installer' from the Microsoft Store, then run this again."
}

Say "Installing Git, ffmpeg, Node and Python (Windows may ask you to allow each one)"
Update-Path
$packages = [ordered]@{ "git.exe" = "Git.Git"; "ffmpeg.exe" = "Gyan.FFmpeg"; "node.exe" = "OpenJS.NodeJS.LTS" }
foreach ($program in $packages.Keys) {
  if (-not (Get-Command $program -ErrorAction SilentlyContinue)) { Install-Package $packages[$program] }
}
$python = Find-Python
if (-not $python) {
  Install-Package "Python.Python.3.13" @("--scope", "user")
  $python = Find-Python
}
foreach ($program in "git.exe", "ffmpeg.exe", "ffprobe.exe", "node.exe", "npm.cmd") {
  if (-not (Get-Command $program -ErrorAction SilentlyContinue)) {
    Stop-Install "$program still isn't found. Close this window, open a new PowerShell, and run the install command again."
  }
}
if (-not $python) { Stop-Install "Python didn't install. Install Python 3.13 from python.org, then run this again." }

Say "Downloading Auto Edit to $Dir"
if (Test-Path (Join-Path $Dir ".git")) {
  Invoke-Step "Updating Auto Edit" { git.exe -C $Dir fetch --depth 1 origin $Branch }
  Invoke-Step "Updating Auto Edit" { git.exe -C $Dir checkout -B $Branch FETCH_HEAD }
} else {
  if (Test-Path $Dir) { Stop-Install "$Dir already exists and isn't an Auto Edit install. Move it, then run this again." }
  Invoke-Step "Downloading Auto Edit" { git.exe clone --depth 1 --branch $Branch $Repo $Dir }
}

Say "Setting up (this is the long part)"
Invoke-Step "Creating the Python environment" { & $python -m venv (Join-Path $Dir ".venv") }
$venvPython = Join-Path $Dir ".venv\Scripts\python.exe"
Invoke-Step "Installing Python packages" {
  & $venvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $Dir "requirements.txt")
}
Push-Location $Dir
try {
  Invoke-Step "Installing HyperFrames" { npm.cmd ci --silent --no-fund --no-audit }
} finally {
  Pop-Location
}
Invoke-Step "Downloading the browser HyperFrames draws with" {
  node.exe (Join-Path $Dir "node_modules\hyperframes\bin\hyperframes.mjs") browser ensure
}

$whisperDir = Join-Path $Dir "whisper"
if (-not (Test-Path (Join-Path $whisperDir "whisper-cli.exe"))) {
  Say "Downloading speech recognition (whisper.cpp)"
  $zip = Join-Path $env:TEMP "auto-edit-whisper.zip"
  Get-Verified $Whisper $zip
  $unpacked = Join-Path $env:TEMP "auto-edit-whisper"
  if (Test-Path $unpacked) { Remove-Item $unpacked -Recurse -Force }
  Expand-Archive $zip $unpacked
  New-Item -ItemType Directory -Force $whisperDir | Out-Null
  Copy-Item (Join-Path $unpacked "Release\*") $whisperDir -Recurse -Force
  Remove-Item $unpacked, $zip -Recurse -Force
}
$model = Join-Path $Dir "models\selfie_multiclass_256x256.tflite"
if (-not (Test-Path $model)) {
  Say "Downloading the model that finds you in the frame"
  Get-Verified $MaskModel $model
}

$bin = Join-Path $Dir "bin"
New-Item -ItemType Directory -Force $bin | Out-Null
@'
@echo off
setlocal
set "PATH=%~dp0..\whisper;%PATH%"
set "PYTHONUTF8=1"
"%~dp0..\.venv\Scripts\python.exe" "%~dp0..\autoedit.py" %*
'@ | Set-Content (Join-Path $bin "autoedit.cmd") -Encoding Ascii
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($userPath -split ";") -notcontains $bin) {
  [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $bin).TrimStart(";"), "User")
}
Update-Path

# Double-click it to be asked for a video, or drop a video onto it.
$desktop = [Environment]::GetFolderPath("Desktop")
if ($desktop -and (Test-Path $desktop)) {
  @'
@echo off
title Auto Edit
call "%USERPROFILE%\.auto-edit\bin\autoedit.cmd" ask %1
echo.
pause
'@ | Set-Content (Join-Path $desktop "Auto Edit.bat") -Encoding Ascii
}

$claudeNote = ""
if (Test-Path (Join-Path $HOME ".claude")) {
  $skill = Join-Path $HOME ".claude\skills\auto-edit"
  New-Item -ItemType Directory -Force $skill | Out-Null
  # Keep a skill someone has already customized.
  if (-not (Test-Path (Join-Path $skill "SKILL.md"))) { Copy-Item (Join-Path $Dir "skill\auto-edit\SKILL.md") $skill }
  $claudeNote = "Claude Code found: you can also say `"edit this video`" there."
}

Say "Checking everything works"
Invoke-Step "The setup check" { & (Join-Path $bin "autoedit.cmd") doctor }

Write-Host ""
Write-Host "All set. Double-click 'Auto Edit' on your Desktop, or drop a video onto it." -ForegroundColor Green
Write-Host "In a new terminal you can also run: autoedit myvideo.mp4"
if ($claudeNote) { Write-Host $claudeNote }
