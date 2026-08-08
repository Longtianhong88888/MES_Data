# login_test.ps1 - auto-login + resource scan for the internal MES site
# Zero-install: uses Windows built-in PowerShell 5.1 only.
#
# Flow:
#   1. GET login.aspx, parse ASP.NET hidden fields (__VIEWSTATE etc.)
#   2. POST credentials + hidden fields to login.aspx
#   3. Open the app entry URL from config.json
#   4. Fetch top/left/home frames, verify the session is valid
#   5. Count links / download-like resources found in the frames
#   6. Inspect each download page (form fields, buttons)
#   7. Trigger the Excel export (toexcelbutton postback) and save the files

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

# ---- Step 5: scan frames for resources ----
Write-Output 'Step 5: scanning frames for resources...'
$allHrefs = @()
foreach ($fc in $framesToScan) {
    $hrefs = [regex]::Matches($fc, 'href\s*=\s*["'']([^"'']+)["'']', 'IgnoreCase') | ForEach-Object { $_.Groups[1].Value }
    foreach ($h in $hrefs) { $allHrefs += $h }
    $openPageCalls = [regex]::Matches($fc, 'openPage\([^)]*\)', 'IgnoreCase')
    Write-Output ('  openPage() menu calls found: ' + $openPageCalls.Count)
}
$uniqueHrefs = $allHrefs | Where-Object { $_ -ne '#' } | Sort-Object -Unique
Write-Output ('Unique non-empty hrefs: ' + $uniqueHrefs.Count)
$dlHrefs = $uniqueHrefs | Where-Object { $_ -match '\.(pdf|xls|xlsx|zip|rar|csv|doc|docx|txt|dat)(\?|$)' -or $_ -match 'download|attach|getfile|file=' }
Write-Output ('Download-like page links: ' + $dlHrefs.Count)
if ($dlHrefs.Count -gt 0) {
    $dlHrefs | ForEach-Object { Write-Output ('  - ' + $_) }
}

# ---- Step 6: crawl each download page and inspect its content ----
$pageIndex = 0
foreach ($dl in $dlHrefs) {
    $pageIndex++
    if ($pageIndex -gt 15) { break }
    try {
        $absUrl = (New-Object System.Uri($base, $dl)).AbsoluteUri
        Write-Output ('Opening download page ' + $pageIndex + ': ' + $absUrl)
        $dResp = Invoke-WebRequest -Uri $absUrl -WebSession $session -UseBasicParsing
        $dHtml = $dResp.Content
        $dFile = Join-Path $BASE_DIR ('vtq_' + $pageIndex + '.html')
        $dHtml | Out-File -FilePath $dFile -Encoding UTF8
        $fileHrefs = [regex]::Matches($dHtml, 'href\s*=\s*["'']([^"'']+\.(?:pdf|xls|xlsx|zip|rar|csv|doc|docx|txt|dat)(?:\?[^"'']*)?)["'']', 'IgnoreCase') | ForEach-Object { $_.Groups[1].Value }
        $submitButtons = [regex]::Matches($dHtml, '<input\b[^>]*\btype\s*=\s*["''](?:submit|button)["''][^>]*>', 'IgnoreCase')
        $formFields = [regex]::Matches($dHtml, '<input\b[^>]*>', 'IgnoreCase')
        Write-Output ('  status=' + [int]$dResp.StatusCode + ' length=' + $dHtml.Length + ' fileLinks=' + $fileHrefs.Count + ' buttons=' + $submitButtons.Count + ' inputs=' + $formFields.Count)
        foreach ($fh in ($fileHrefs | Select-Object -First 10)) {
            Write-Output ('    FILE: ' + $fh)
        }
    } catch {
        Write-Output ('  failed: ' + $_.Exception.Message)
    }
}

# ---- Step 7: trigger Excel export on each download page and save files ----
Write-Output 'Step 7: attempting Excel export from each download page...'
$downloadDir = Join-Path $BASE_DIR 'downloads'
New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null

function Get-FormFields([string]$html) {
    $fields = @{}
    foreach ($m in [regex]::Matches($html, '<input\b[^>]*>', 'IgnoreCase')) {
        $tag = $m.Value
        $nm = [regex]::Match($tag, '\bname\s*=\s*["'']([^"'']+)["'']', 'IgnoreCase')
        if (-not $nm.Success) { continue }
        $name = $nm.Groups[1].Value
        if ($name -eq '__EVENTTARGET' -or $name -eq '__EVENTARGUMENT') { continue }
        $tp = [regex]::Match($tag, '\btype\s*=\s*["'']([^"'']+)["'']', 'IgnoreCase')
        $type = ''
        if ($tp.Success) { $type = $tp.Groups[1].Value.ToLower() }
        if ($type -eq 'submit' -or $type -eq 'button' -or $type -eq 'image') { continue }
        $vl = [regex]::Match($tag, '\bvalue\s*=\s*["'']([^"'']*)["'']', 'IgnoreCase')
        $value = ''
        if ($vl.Success) { $value = $vl.Groups[1].Value }
        if (($type -eq 'radio' -or $type -eq 'checkbox') -and $tag -notmatch '\bchecked\b') { continue }
        $fields[$name] = $value
    }
    foreach ($m in [regex]::Matches($html, '<select\b[^>]*>(.*?)</select>', 'IgnoreCase, Singleline')) {
        $tag = $m.Value
        $nm = [regex]::Match($tag, '\bname\s*=\s*["'']([^"'']+)["'']', 'IgnoreCase')
        if (-not $nm.Success) { continue }
        $name = $nm.Groups[1].Value
        $opt = [regex]::Match($tag, '<option\b[^>]*\bselected(?:=[^ >]*)?[^>]*\bvalue="([^"]*)"', 'IgnoreCase')
        if (-not $opt.Success) { $opt = [regex]::Match($tag, '<option\b[^>]*\bvalue="([^"]*)"', 'IgnoreCase') }
        if (-not $opt.Success) { continue }
        $fields[$name] = $opt.Groups[1].Value
    }
    return $fields
}

$pageIndex = 0
foreach ($dl in $dlHrefs) {
    $pageIndex++
    if ($pageIndex -gt 15) { break }
    try {
        $absUrl = (New-Object System.Uri($base, $dl)).AbsoluteUri
        $pageName = [regex]::Match($absUrl, '/([^/]+)\.aspx\s*$', 'IgnoreCase').Groups[1].Value
        if (-not $pageName) { $pageName = 'page' + $pageIndex }
        Write-Output ('Export ' + $pageIndex + ': ' + $pageName)

        $gResp = Invoke-WebRequest -Uri $absUrl -WebSession $session -UseBasicParsing
        $gHtml = $gResp.Content

        $fileSaved = $false
        $attempt = 0
        while ($attempt -lt 2 -and -not $fileSaved) {
            $attempt++
            $fields = Get-FormFields $gHtml
            $body = @{
                '__EVENTTARGET' = 'toexcelbutton'
                '__EVENTARGUMENT' = ''
            }
            foreach ($k in $fields.Keys) { $body[$k] = $fields[$k] }
            if ($attempt -eq 2) {
                $body['__EVENTTARGET'] = 'searchbutton'
                Write-Output '  direct export returned HTML; trying search-then-export...'
            }
            $tmpFile = Join-Path $downloadDir ('dl_' + $pageIndex + '.bin')
            $xResp = Invoke-WebRequest -Uri $absUrl -Method Post -Body $body -WebSession $session -UseBasicParsing -TimeoutSec 300 -OutFile $tmpFile
            $ct = ''
            if ($xResp.Headers['Content-Type']) { $ct = [string]$xResp.Headers['Content-Type'] }
            if ($ct -match 'excel|octet-stream') {
                $finalFile = Join-Path $downloadDir ('dl_' + $pageIndex + '_' + $pageName + '.xls')
                Move-Item -Force -Path $tmpFile -Destination $finalFile
                $size = (Get-Item $finalFile).Length
                Write-Output ('  SAVED: ' + $finalFile + ' (' + $size + ' bytes, ' + $ct + ')')
                $fileSaved = $true
            } else {
                $htmlFile = Join-Path $downloadDir ('dl_' + $pageIndex + '_' + $pageName + '_page.html')
                Move-Item -Force -Path $tmpFile -Destination $htmlFile
                Write-Output ('  not a file yet (content-type=' + $ct + ', saved page: ' + $htmlFile + ')')
                if ($attempt -lt 2) {
                    $gHtml = Get-Content -Path $htmlFile -Raw -Encoding UTF8
                }
            }
        }
    } catch {
        Write-Output ('  failed: ' + $_.Exception.Message)
    }
}
Write-Output 'Done.'
exit 0
