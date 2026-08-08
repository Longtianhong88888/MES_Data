# login_test.ps1 - auto-login + SN trace page discovery for the internal MES site
# Zero-install: uses Windows built-in PowerShell 5.1 only.
#
# Flow:
#   1. GET login.aspx, parse ASP.NET hidden fields (__VIEWSTATE etc.)
#   2. POST credentials + hidden fields to login.aspx
#   3. Open the app entry URL from config.json
#   4. Fetch top/left/home frames, verify the session is valid
#   5. List the frames' menu links and download-like pages
#   6. Fetch the SN trace query pages and report their query form structure

param(
    [string]$Username = '',
    [string]$Password = ''
)

$ErrorActionPreference = 'Stop'

$BASE_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$CONFIG_PATH = Join-Path $BASE_DIR 'config.json'

$loginUrl = ''
$username = $Username
$password = $Password

if (Test-Path $CONFIG_PATH) {
    $config = Get-Content -Path $CONFIG_PATH -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $loginUrl) { $loginUrl = $config.login_url }
    if (-not $username)  { $username = $config.username }
    if (-not $password)  { $password = $config.password }
}

if (-not $loginUrl) { $loginUrl = Read-Host 'App entry URL (index.aspx?project=...&custom=...&num=...)' }
if (-not $username) { $username = Read-Host 'Username' }
if (-not $password) { $password = Read-Host 'Password' }

function Get-FormValue([string]$html, [string]$field) {
    $tag = [regex]::Match($html, '<input\b[^>]*\bname="' + [regex]::Escape($field) + '"[^>]*>', 'IgnoreCase').Value
    if (-not $tag) { return '' }
    $m = [regex]::Match($tag, 'value="([^"]*)"', 'IgnoreCase')
    if ($m.Success) { return $m.Groups[1].Value }
    return ''
}

$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$session.UserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

$base = New-Object System.Uri($loginUrl)
$origin = $base.GetLeftPart([System.UriPartial]::Authority)
$loginPageUrl = $origin + '/login.aspx'

Write-Output ('Target app: ' + $loginUrl)
Write-Output ('User:       ' + $username)
Write-Output ('Login page: ' + $loginPageUrl)

# ---- Step 1: GET the login page ----
Write-Output 'Step 1: fetching login page...'
$lpResp = Invoke-WebRequest -Uri $loginPageUrl -WebSession $session -UseBasicParsing
$lpResp.Content | Out-File -FilePath (Join-Path $BASE_DIR 'login_page.html') -Encoding UTF8

$vs  = Get-FormValue $lpResp.Content '__VIEWSTATE'
$vsg = Get-FormValue $lpResp.Content '__VIEWSTATEGENERATOR'
$ev  = Get-FormValue $lpResp.Content '__EVENTVALIDATION'
if (-not $vs -or -not $ev) {
    Write-Output 'ERROR: login page does not contain the expected ASP.NET hidden fields.'
    exit 1
}

$btnTag = [regex]::Match($lpResp.Content, '<input\b[^>]*\bname="' + [regex]::Escape('Login1$LoginImageButton') + '"[^>]*>', 'IgnoreCase').Value
$btnValue = ''
$bm = [regex]::Match($btnTag, 'value="([^"]*)"', 'IgnoreCase')
if ($bm.Success) { $btnValue = $bm.Groups[1].Value }

# ---- Step 2: POST the login form ----
Write-Output 'Step 2: posting login form...'
$body = @{
    '__LASTFOCUS' = ''
    '__EVENTTARGET' = ''
    '__EVENTARGUMENT' = ''
    '__VIEWSTATE' = $vs
    '__VIEWSTATEGENERATOR' = $vsg
    '__EVENTVALIDATION' = $ev
    'Login1$useridtb' = $username
    'Login1$userpwdtb' = $password
    'Login1$LoginImageButton' = $btnValue
}

$loginResp = Invoke-WebRequest -Uri $loginPageUrl -Method Post -Body $body -WebSession $session -UseBasicParsing -MaximumRedirection 10
$loginHtml = $loginResp.Content
Write-Output ('Login POST status: ' + [int]$loginResp.StatusCode)
Write-Output ('Login POST final:  ' + $loginResp.BaseResponse.ResponseUri.AbsoluteUri)
$loginHtml | Out-File -FilePath (Join-Path $BASE_DIR 'login_post_result.html') -Encoding UTF8

$stillLoginPage = $loginResp.BaseResponse.ResponseUri.AbsoluteUri -match 'login\.aspx' -or $loginHtml -match [regex]::Escape('Login1$userpwdtb')
if ($stillLoginPage) {
    Write-Output 'Result: LOGIN FAILED - server returned the login page again (check credentials).'
    exit 1
}

# ---- Step 3: open the app entry ----
Write-Output 'Step 3: opening app entry...'
$appResp = Invoke-WebRequest -Uri $loginUrl -WebSession $session -UseBasicParsing
$appHtml = $appResp.Content
$appHtml | Out-File -FilePath (Join-Path $BASE_DIR 'login_result.html') -Encoding UTF8

if ($appHtml -notmatch '<frameset') {
    Write-Output 'ERROR: app entry did not return the frameset page.'
    exit 1
}

# ---- Step 4: verify the session via frames ----
Write-Output 'Step 4: verifying session via frames...'
$frameMatches = [regex]::Matches($appHtml, '<frame\b[^>]*\bsrc\s*=\s*["''](?<src>[^"'']+)["'']', 'IgnoreCase')
Write-Output ('Frames found: ' + $frameMatches.Count)
$frameIndex = 0
$sessionValid = $false
$framesToScan = @()
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
        } else {
            Write-Output ('Frame ' + $frameIndex + ': fetched OK (length ' + $frameResp.Content.Length + ').')
            $sessionValid = $true
            $framesToScan += $frameResp.Content
        }
    } catch {
        Write-Output ('Frame ' + $frameIndex + ' fetch failed: ' + $_.Exception.Message)
    }
}

if (-not $sessionValid) {
    Write-Output 'Result: session still NOT authenticated after the login POST.'
    exit 1
}
Write-Output 'Result: session authenticated OK.'

# ---- Step 5: list menu links and download-like pages ----
Write-Output 'Step 5: listing menu links...'
$allHrefs = @()
foreach ($fc in $framesToScan) {
    $hrefs = [regex]::Matches($fc, 'href\s*=\s*["'']([^"'']+)["'']', 'IgnoreCase') | ForEach-Object { $_.Groups[1].Value }
    foreach ($h in $hrefs) { $allHrefs += $h }
    $openPageCalls = [regex]::Matches($fc, 'openPage\([^)]*\)', 'IgnoreCase')
    Write-Output ('  openPage() menu calls found: ' + $openPageCalls.Count)
}
$uniqueHrefs = $allHrefs | Where-Object { $_ -ne '#' } | Sort-Object -Unique
Write-Output ('Unique non-empty hrefs: ' + $uniqueHrefs.Count)

# ---- Step 6: inspect the SN trace query pages ----
Write-Output 'Step 6: inspecting SN trace query pages...'
$snPages = @(
    'VTQTestSNCurrentState.aspx',
    'TestSnCurrentStatus.aspx',
    'TestSNCurrentStateNew.aspx',
    'VTQTestSNCurrentStateNew.aspx',
    'VTTestSnCurrentStateSorting.aspx',
    'TestSNCurrentStateCre.aspx',
    'SnTestTrack.aspx',
    'FOLSnTestTrack.aspx',
    'NHASNSearch.aspx'
)
$pageIndex = 0
foreach ($pageName in $snPages) {
    $pageIndex++
    $snUrl = $origin + '/VTQReport/' + $pageName
    Write-Output ('SN page ' + $pageIndex + ': ' + $snUrl)
    try {
        $sResp = Invoke-WebRequest -Uri $snUrl -WebSession $session -UseBasicParsing
        $sHtml = $sResp.Content
        $sFile = Join-Path $BASE_DIR ('sn_' + $pageIndex + '.html')
        $sHtml | Out-File -FilePath $sFile -Encoding UTF8
        $textInputs = [regex]::Matches($sHtml, '<input\b[^>]*\btype\s*=\s*["'']text["''][^>]*>', 'IgnoreCase')
        $submitButtons = [regex]::Matches($sHtml, '<input\b[^>]*\btype\s*=\s*["'']submit["''][^>]*>', 'IgnoreCase')
        $nameList = @()
        foreach ($ti in $textInputs) {
            $nm = [regex]::Match($ti.Value, '\bname\s*=\s*["'']([^"'']+)["'']', 'IgnoreCase')
            if ($nm.Success) { $nameList += $nm.Groups[1].Value }
        }
        Write-Output ('  status=' + [int]$sResp.StatusCode + ' length=' + $sHtml.Length + ' textInputs=' + $textInputs.Count + ' buttons=' + $submitButtons.Count)
        if ($nameList.Count -gt 0) {
            Write-Output ('  text fields: ' + ($nameList -join ', '))
        }
    } catch {
        Write-Output ('  failed: ' + $_.Exception.Message)
    }
}
Write-Output 'Done.'
exit 0
