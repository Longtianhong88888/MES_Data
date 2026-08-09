# download_images.ps1 - download station images from URL list files.
# Run this on a machine that can reach the image file servers
# (e.g. the company desktop). No login needed - the URLs are pre-signed.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File download_images.ps1
#   (reads *images*.txt from .\downloads and saves images to .\downloads\images)

param(
    [string]$ListDir = '',
    [string]$OutDir = ''
)

$ErrorActionPreference = 'Stop'
$BASE_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $ListDir) { $ListDir = Join-Path $BASE_DIR 'downloads' }
if (-not $OutDir) { $OutDir = Join-Path $BASE_DIR 'downloads\images' }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$lists = @(Get-ChildItem -Path $ListDir -Filter '*images*.txt' -File -ErrorAction SilentlyContinue)
if ($lists.Count -eq 0) {
    # also look in the script folder (e.g. after unzipping a packed list)
    $lists = @(Get-ChildItem -Path $BASE_DIR -Filter '*images*.txt' -File -ErrorAction SilentlyContinue)
}
if ($lists.Count -eq 0) {
    Write-Output ('No image list files found in: ' + $ListDir + ' or ' + $BASE_DIR)
    exit 1
}

$total = 0
$okCount = 0
foreach ($list in $lists) {
    $urls = @(Get-Content -Path $list.FullName | Where-Object { $_.Trim() -ne '' })
    Write-Output ('List: ' + $list.Name + ' (' + $urls.Count + ' URLs)')
    $n = 0
    foreach ($u in $urls) {
        $n++
        $total++
        $name = [System.IO.Path]::GetFileName(($u -split '[?#]')[0])
        if (-not $name) { $name = ('img_' + $n + '.jpg') }
        $out = Join-Path $OutDir $name
        if (Test-Path $out) {
            Write-Output ('  exists: ' + $name)
            $okCount++
            continue
        }
        try {
            Invoke-WebRequest -Uri $u -OutFile $out -UseBasicParsing -TimeoutSec 120
            Write-Output ('  OK: ' + $name)
            $okCount++
        } catch {
            Write-Output ('  FAIL: ' + $name + ' - ' + $_.Exception.Message)
        }
    }
}
Write-Output ('Done. ' + $okCount + '/' + $total + ' images in ' + $OutDir)
