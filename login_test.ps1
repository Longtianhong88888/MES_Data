# login_test.ps1 - quick auto-login test for the internal site
# Zero-install: uses Windows built-in PowerShell 5.1 only. No Python needed.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File login_test.ps1
#   (or just double-click login_windows.bat)

param(
    [string]$Username = '',
    [string]$Password = ''
)

$ErrorActionPreference = 'Stop'

$BASE_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$CONFIG_PATH = Join-Path $BASE_DIR 'config.json'
$RESULT_HTML = Join-Path $BASE_DIR 'login_result.html'

$loginUrl = ''
$username = $Username
$password = $Password
$usernameField = 'username'
$passwordField = 'password'
$extraFields = @{}

# Load config.json if present (credentials stay local, never committed)
if (Test-Path $CONFIG_PATH) {
    $config = Get-Content -Path $CONFIG_PATH -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $loginUrl) { $loginUrl = $config.login_url }
    if (-not $username)  { $username = $config.username }
    if (-not $password)  { $password = $config.password }
    if ($config.login_form) {
        if ($config.login_form.username_field) { $usernameField = $config.login_form.username_field }
        if ($config.login_form.password_field) { $passwordField = $config.login_form.password_field }
        if ($config.login_form.extra_fields) {
            $config.login_form.extra_fields.PSObject.Properties | ForEach-Object {
                $extraFields[$_.Name] = $_.Value
            }
        }
    }
}

# Prompt for anything still missing
if (-not $loginUrl) { $loginUrl = Read-Host 'Login URL (e.g. http://server:8081/login)' }
if (-not $username) { $username = Read-Host 'Username' }
if (-not $password) { $password = Read-Host 'Password' }

$body = @{
    $usernameField = $username
    $passwordField = $password
}
foreach ($k in $extraFields.Keys) {
    $body[$k] = $extraFields[$k]
}

Write-Output ('Target: ' + $loginUrl)
Write-Output ('User:   ' + $username)

$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$session.UserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

Write-Output 'Sending login request...'

try {
    $resp = Invoke-WebRequest -Uri $loginUrl -Method Post -Body $body -WebSession $session -UseBasicParsing -MaximumRedirection 5
} catch {
    Write-Output ('HTTP error: ' + $_.Exception.Message)
    Write-Output 'Login test FAILED (network or server error).'
    exit 1
}

$finalUrl = $resp.BaseResponse.ResponseUri.AbsoluteUri
Write-Output ('HTTP status: ' + [int]$resp.StatusCode)
Write-Output ('Final URL:   ' + $finalUrl)
Write-Output ('Cookies:     ' + $session.Cookies.Count)

try {
    $resp.Content | Out-File -FilePath $RESULT_HTML -Encoding UTF8
    Write-Output ('Saved response page: ' + $RESULT_HTML)
} catch {
    Write-Output 'Could not save response page.'
}

$isLoginPage = $finalUrl.TrimEnd('/').ToLower() -eq $loginUrl.TrimEnd('/').ToLower()

if ($isLoginPage) {
    Write-Output 'Result: still on the login page -> login FAILED or extra auth needed.'
    exit 1
} else {
    Write-Output 'Result: redirected away from the login page -> login looks SUCCESSFUL.'
    exit 0
}
