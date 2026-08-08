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
$html = $resp.Content
Write-Output ('HTTP status: ' + [int]$resp.StatusCode)
Write-Output ('Final URL:   ' + $finalUrl)
Write-Output ('Cookies:     ' + $session.Cookies.Count)

try {
    $html | Out-File -FilePath $RESULT_HTML -Encoding UTF8
    Write-Output ('Saved response page: ' + $RESULT_HTML)
} catch {
    Write-Output 'Could not save response page.'
}

# Content-based judgement: this site stays on index.aspx after login and returns
# the main frameset shell (top/left/home frames). A login form contains a password field.
$hasLoginForm = $html -match 'type\s*=\s*["'']password["'']'
$hasFrameset  = $html -match '<frameset'

if ($hasFrameset) {
    Write-Output 'Result: main app frameset returned (POST accepted).'

    # Verify the session by fetching each frame page (top/left/home) with the
    # same session. An expired/invalid session returns the frames with an
    # injected "login expired" script (redirect to login.aspx) instead of content.
    $base = New-Object System.Uri($loginUrl)
    $frameMatches = [regex]::Matches($html, '<frame\b[^>]*\bsrc\s*=\s*["''](?<src>[^"'']+)["'']', 'IgnoreCase')
    Write-Output ('Frames found: ' + $frameMatches.Count)
    $frameIndex = 0
    $usernameFound = $false
    $sessionInvalid = $false
    foreach ($fm in $frameMatches) {
        $frameIndex++
        if ($frameIndex -gt 3) { break }
        $src = $fm.Groups['src'].Value
        $frameUri = New-Object System.Uri($base, $src)
        $frameUrl = $frameUri.AbsoluteUri
        Write-Output ('Fetching frame ' + $frameIndex + ': ' + $frameUrl)
        try {
            $frameResp = Invoke-WebRequest -Uri $frameUrl -WebSession $session -UseBasicParsing
            $frameFile = Join-Path $BASE_DIR ('frame_' + $frameIndex + '.html')
            $frameResp.Content | Out-File -FilePath $frameFile -Encoding UTF8
            if ($frameResp.Content -match 'login\.aspx|window\.top\.location') {
                Write-Output ('Frame ' + $frameIndex + ': SESSION INVALID (login-expired message found).')
                $sessionInvalid = $true
            } elseif ($frameResp.Content -match [regex]::Escape($username)) {
                Write-Output ('Confirmed: username "' + $username + '" found in frame ' + $frameIndex + '.')
                $usernameFound = $true
            } else {
                Write-Output ('Frame ' + $frameIndex + ' fetched OK (length ' + $frameResp.Content.Length + '), username not shown here.')
            }
        } catch {
            Write-Output ('Frame ' + $frameIndex + ' fetch failed: ' + $_.Exception.Message)
        }
    }
    if ($usernameFound) {
        Write-Output 'Result: logged-in session confirmed by page content.'
        exit 0
    }
    if ($sessionInvalid) {
        Write-Output 'Result: session is NOT authenticated - this site needs the real login page flow.'
        # Probe the real login page so we can build a proper login POST.
        $origin = $base.GetLeftPart([System.UriPartial]::Authority)
        $loginPageUrl = $origin + '/login.aspx'
        Write-Output ('Probing login page: ' + $loginPageUrl)
        try {
            $lpResp = Invoke-WebRequest -Uri $loginPageUrl -WebSession $session -UseBasicParsing
            $lpResp.Content | Out-File -FilePath (Join-Path $BASE_DIR 'login_page.html') -Encoding UTF8
            $inputs = [regex]::Matches($lpResp.Content, '<input\b[^>]*>', 'IgnoreCase')
            Write-Output ('Login page input fields (' + $inputs.Count + '):')
            foreach ($inp in $inputs) {
                $nm = [regex]::Match($inp.Value, 'name\s*=\s*["'']([^"'']+)["'']', 'IgnoreCase')
                $tp = [regex]::Match($inp.Value, 'type\s*=\s*["'']([^"'']+)["'']', 'IgnoreCase')
                $name = ''
                $type = ''
                if ($nm.Success) { $name = $nm.Groups[1].Value }
                if ($tp.Success) { $type = $tp.Groups[1].Value }
                Write-Output ('  - name=' + $name + ' type=' + $type)
            }
            if ($lpResp.Content -match 'captcha|verifycode|verify_code') {
                Write-Output 'WARNING: login page contains a captcha-like field.'
            }
        } catch {
            Write-Output ('Login page probe failed: ' + $_.Exception.Message)
        }
    } else {
        Write-Output 'Result: frames fetched but could not confirm the session from content.'
    }
    exit 0
} elseif ($hasLoginForm) {
    Write-Output 'Result: response still contains a password field -> login FAILED.'
    exit 1
} else {
    Write-Output 'Result: cannot tell from page content, check login_result.html.'
    exit 2
}
