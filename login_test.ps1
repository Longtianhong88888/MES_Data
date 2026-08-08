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
#   7. Fill in the SN from config.json, submit the query, save the result page
#   8. Query Test data / ACF pages with the module SN
#   9. Open MC IMG UpLoadInfo (ReportPortal) and report its required fields

param(
    [string]$Username = '',
    [string]$Password = '',
    [string]$Sn = ''
)

$ErrorActionPreference = 'Stop'

$BASE_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$CONFIG_PATH = Join-Path $BASE_DIR 'config.json'

$loginUrl = ''
$username = $Username
$password = $Password
$sn = $Sn

if (Test-Path $CONFIG_PATH) {
    $config = Get-Content -Path $CONFIG_PATH -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $loginUrl) { $loginUrl = $config.login_url }
    if (-not $username)  { $username = $config.username }
    if (-not $password)  { $password = $config.password }
    if (-not $sn -and $config.sn) { $sn = [string]$config.sn }
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
    'report/snsearch.aspx',
    'Tracking/sntotalinfo.aspx',
    'VTQReport/VTQTestSNCurrentState.aspx',
    'VTQReport/TestSnCurrentStatus.aspx',
    'VTQReport/TestSNCurrentStateNew.aspx',
    'VTQReport/VTQTestSNCurrentStateNew.aspx',
    'VTQReport/VTTestSnCurrentStateSorting.aspx',
    'VTQReport/TestSNCurrentStateCre.aspx',
    'VTQReport/SnTestTrack.aspx',
    'VTQReport/FOLSnTestTrack.aspx',
    'VTQReport/NHASNSearch.aspx',
    'VTQReport/ACFscanning.aspx'
)
$pageIndex = 0
foreach ($pageRel in $snPages) {
    $pageIndex++
    $pageName = [regex]::Match($pageRel, '([^/]+)\.aspx$', 'IgnoreCase').Groups[1].Value
    if (-not $pageName) { $pageName = 'page' + $pageIndex }
    $snUrl = $origin + '/' + $pageRel
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

# ---- Step 7: submit the SN query and save the result page ----
Write-Output 'Step 7: submitting SN query...'
if (-not $sn) {
    Write-Output '  No SN provided. Add "sn" to config.json or pass -Sn "..."'
} else {
    Write-Output ('  SN: ' + $sn)

    $queryPages = @(
        'report/snsearch.aspx',
        'Tracking/sntotalinfo.aspx'
    )
    $qIndex = 0
    foreach ($rel in $queryPages) {
        $qIndex++
        $pageName = [regex]::Match($rel, '([^/]+)\.aspx$', 'IgnoreCase').Groups[1].Value
        $qUrl = $origin + '/' + $rel
        Write-Output ('Query ' + $qIndex + ' (' + $pageName + '): ' + $qUrl)
        try {
            $qResp = Invoke-WebRequest -Uri $qUrl -WebSession $session -UseBasicParsing
            $qHtml = $qResp.Content
            $fields = Get-FormFields $qHtml

            $snField = ''
            foreach ($k in $fields.Keys) {
                if ($k -match '(?i)sn|serial|barcode') { $snField = $k; break }
            }
            if (-not $snField) {
                Write-Output ('  no SN-like field found. fields: ' + (($fields.Keys | Select-Object -First 12) -join ', '))
                continue
            }
            Write-Output ('  SN field: ' + $snField)

            $body = @{}
            foreach ($k in $fields.Keys) { $body[$k] = $fields[$k] }
            $body[$snField] = $sn

            $trigger = ''
            $btnM = [regex]::Match($qHtml, '<input\b[^>]*\btype\s*=\s*["'']submit["''][^>]*>', 'IgnoreCase')
            if ($btnM.Success) {
                $bn = [regex]::Match($btnM.Value, '\bname\s*=\s*["'']([^"'']+)["'']', 'IgnoreCase')
                if ($bn.Success) { $trigger = $bn.Groups[1].Value }
            }
            if (-not $trigger) {
                $pb = [regex]::Match($qHtml, '__doPostBack\(\s*["'']([^"'']*(?:search|query|btn)[^"'']*)["'']\s*,\s*["'']*["'']*\s*\)', 'IgnoreCase')
                if ($pb.Success) { $trigger = $pb.Groups[1].Value }
            }
            $body['__EVENTTARGET'] = $trigger
            $body['__EVENTARGUMENT'] = ''
            if ($trigger) {
                Write-Output ('  trigger: ' + $trigger)
            } else {
                Write-Output '  no submit button / postback target found; posting with empty trigger'
            }

            $qRes = Invoke-WebRequest -Uri $qUrl -Method Post -Body $body -WebSession $session -UseBasicParsing -TimeoutSec 120
            $qResHtml = $qRes.Content
            $resFile = Join-Path $BASE_DIR ('sn_result_' + $qIndex + '_' + $pageName + '.html')
            $qResHtml | Out-File -FilePath $resFile -Encoding UTF8
            $trCount = [regex]::Matches($qResHtml, '<tr\b', 'IgnoreCase').Count
            $snInPage = $qResHtml -match [regex]::Escape($sn)
            Write-Output ('  result length=' + $qResHtml.Length + ' rows=' + $trCount + ' snInPage=' + $snInPage + ' saved: ' + $resFile)

            if ($pageName -eq 'snsearch') {
                # Parse the SN search result: summary row, station trace, consumables
                $rows = [regex]::Matches($qResHtml, '<tr\b[^>]*>(.*?)</tr>', 'IgnoreCase, Singleline')
                $stations = @()
                $consumables = @()
                $components = @()
                $componentIds = @()
                $summaryRow = @()
                foreach ($r in $rows) {
                    $tds = @([regex]::Matches($r.Groups[1].Value, '<td\b[^>]*>(.*?)</td>', 'IgnoreCase, Singleline') | ForEach-Object { $_.Groups[1].Value.Trim() })
                    if ($tds.Count -eq 2 -and $tds[0] -ne '站位' -and $tds[1] -match '^\d{4}-\d{2}-\d{2}') {
                        $stations += [pscustomobject]@{ Station = $tds[0]; Time = $tds[1] }
                    } elseif ($tds.Count -eq 12 -and $tds[0] -eq $sn) {
                        $summaryRow = $tds
                    } elseif ($tds.Count -eq 4 -and $tds[0] -notmatch '(?i)耗材|使用站位|名称|批號' -and $tds[1] -ne '') {
                        $consumables += [pscustomobject]@{ Material = $tds[0]; Lot = $tds[1]; Name = $tds[2]; Station = $tds[3] }
                        if ($tds[2] -match '(?i)sensor|lens|vcm|stiffener|tape') {
                            $components += [pscustomobject]@{ Material = $tds[0]; Id = $tds[1]; Name = $tds[2]; Station = $tds[3] }
                            $componentIds += $tds[1]
                        }
                    }
                }
                $componentIds = $componentIds | Select-Object -Unique
                $sumHeaders = @('SN','批號','EOL測試結果','FOL測試結果','SFC結果','線體','包號','包裝時間','箱號','銷單號','出貨地址','出貨時間')
                $reportLines = New-Object System.Collections.Generic.List[string]
                $reportLines.Add('==== SN 汇总 ====')
                if ($summaryRow.Count -ge $sumHeaders.Count) {
                    for ($i = 0; $i -lt $sumHeaders.Count; $i++) {
                        $reportLines.Add(($sumHeaders[$i] + ': ' + $summaryRow[$i]))
                    }
                }
                $reportLines.Add('')
                $reportLines.Add(('==== 站位轨迹 (' + $stations.Count + ') ===='))
                $idx = 0
                foreach ($st in $stations) {
                    $idx++
                    $reportLines.Add(('  ' + $idx + '. ' + $st.Station + '  |  ' + $st.Time))
                }
                $reportLines.Add('')
                $reportLines.Add(('==== 组件绑定 (' + $components.Count + ') ===='))
                foreach ($cp in $components) {
                    $reportLines.Add(('  ' + $cp.Material + ' | ' + $cp.Id + ' | ' + $cp.Name + ' | ' + $cp.Station))
                }
                $reportLines.Add('')
                $reportLines.Add(('==== 耗材记录 (' + $consumables.Count + ') ===='))
                foreach ($cm in $consumables) {
                    $reportLines.Add(('  ' + $cm.Material + ' | ' + $cm.Lot + ' | ' + $cm.Name + ' | ' + $cm.Station))
                }
                $reportFile = Join-Path $BASE_DIR 'sn_trace_report.txt'
                $reportLines | Out-File -FilePath $reportFile -Encoding UTF8
                Write-Output ('  PARSED: stations=' + $stations.Count + ' consumables=' + $consumables.Count)
                Write-Output ('  report saved: ' + $reportFile)
            }
        } catch {
            Write-Output ('  failed: ' + $_.Exception.Message)
        }
    }
}

# ---- Step 8: query test data / ACF pages with the module SN ----
Write-Output 'Step 8: querying test data pages with the module SN...'
$snQueryPages = @(
    'VTQReport/VTQTestDataDownLoad.aspx'
)
if (-not $sn) {
    Write-Output '  no SN provided.'
} else {
    $qIndex = 0
    foreach ($rel in $snQueryPages) {
        $qIndex++
        $pageName = [regex]::Match($rel, '([^/]+)\.aspx$', 'IgnoreCase').Groups[1].Value
        $qUrl = $origin + '/' + $rel
        Write-Output ('Query ' + $qIndex + ' (' + $pageName + ') with SN: ' + $sn)
        try {
            $qResp = Invoke-WebRequest -Uri $qUrl -WebSession $session -UseBasicParsing
            $qHtml = $qResp.Content

            # switch to SensorID mode if the page has a mode radio
            $fields = Get-FormFields $qHtml
            $body = @{}
            foreach ($k in $fields.Keys) { $body[$k] = $fields[$k] }
            $switched = $false
            if ($fields.ContainsKey('selectradio')) {
                $body['selectradio'] = '3'
                $body['__EVENTTARGET'] = 'selectradio$2'
                $body['__EVENTARGUMENT'] = ''
                $mResp = Invoke-WebRequest -Uri $qUrl -Method Post -Body $body -WebSession $session -UseBasicParsing
                $qHtml = $mResp.Content
                $switched = $true
            }

            $fields2 = Get-FormFields $qHtml
            $snField = ''
            foreach ($k in $fields2.Keys) {
                if ($k -match '(?i)barcode|sn|sensor|serial') { $snField = $k; break }
            }
            if (-not $snField) {
                foreach ($k in $fields2.Keys) { if ($k -match '(?i)txt|text') { $snField = $k; break } }
            }
            if (-not $snField) {
                Write-Output ('  no text field found. fields: ' + (($fields2.Keys | Select-Object -First 12) -join ', '))
                continue
            }
            $body3 = @{}
            foreach ($k in $fields2.Keys) { $body3[$k] = $fields2[$k] }
            $body3[$snField] = $sn
            $trig = ''
            $pb = [regex]::Match($qHtml, '__doPostBack\(\s*["'']([^"'']*(?:search|query)[^"'']*)["'']', 'IgnoreCase')
            if (-not $pb.Success) { $pb = [regex]::Match($qHtml, '__doPostBack\(\s*["'']([^"'']*(?:button|btn)[^"'']*)["'']', 'IgnoreCase') }
            if ($pb.Success) { $trig = $pb.Groups[1].Value }
            if (-not $trig) {
                $btnM = [regex]::Match($qHtml, '<input\b[^>]*\btype\s*=\s*["'']submit["''][^>]*>', 'IgnoreCase')
                if ($btnM.Success) {
                    $bn = [regex]::Match($btnM.Value, '\bname\s*=\s*["'']([^"'']+)["'']', 'IgnoreCase')
                    if ($bn.Success) { $trig = $bn.Groups[1].Value }
                }
            }
            $body3['__EVENTTARGET'] = $trig
            $body3['__EVENTARGUMENT'] = ''
            Write-Output ('  field=' + $snField + ' trigger=' + $trig + ' modeSwitched=' + $switched)
            $rResp = Invoke-WebRequest -Uri $qUrl -Method Post -Body $body3 -WebSession $session -UseBasicParsing -TimeoutSec 120
            $rHtml = $rResp.Content
            $rFile = Join-Path $BASE_DIR ('td_query_' + $qIndex + '_' + $pageName + '.html')
            $rHtml | Out-File -FilePath $rFile -Encoding UTF8
            $trCount = [regex]::Matches($rHtml, '<tr\b', 'IgnoreCase').Count
            $idInPage = $rHtml -match [regex]::Escape($sn)
            Write-Output ('  result length=' + $rHtml.Length + ' rows=' + $trCount + ' snInPage=' + $idInPage + ' saved: ' + $rFile)
        } catch {
            Write-Output ('  failed: ' + $_.Exception.Message)
        }
    }
}

# ---- Step 9: ReportPortal pages (ACF Test Data / MC IMG UpLoadInfo) ----
Write-Output 'Step 9: opening ReportPortal pages...'
$portalLabels = @(
    'ACF Test Data',
    'MC IMG UpLoadInfo'
)
$portalOrigin = ''
$portalIndex = 0
foreach ($label in $portalLabels) {
    $portalIndex++
    $portalMatch = $null
    foreach ($fc in $framesToScan) {
        $m = [regex]::Match($fc, "openPage\(\s*\d+\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*\)[^>]*>\s*" + [regex]::Escape($label), 'IgnoreCase')
        if ($m.Success) { $portalMatch = $m; break }
    }
    if (-not $portalMatch) {
        Write-Output ('  ' + $label + ' not found in the menu.')
        continue
    }
    $portalUrl = $portalMatch.Groups[1].Value
    $portalOrigin = (New-Object System.Uri($portalUrl)).GetLeftPart([System.UriPartial]::Authority)
    $device = $portalMatch.Groups[2].Value
    $dbname = $portalMatch.Groups[3].Value
    $plantid = $portalMatch.Groups[4].Value
    $userid = $portalMatch.Groups[5].Value
    Write-Output ('Portal ' + $portalIndex + ' (' + $label + '): ' + $portalUrl)
    Write-Output ('  params: p=' + $device + ' p=' + $dbname + ' p=' + $plantid + ' userID=' + $userid)
    $postBody = 'p=' + $device + '&p=' + $dbname + '&p=' + $plantid + '&userID=' + $userid
    try {
        $pResp = Invoke-WebRequest -Uri $portalUrl -Method Post -Body $postBody -ContentType 'application/x-www-form-urlencoded' -WebSession $session -UseBasicParsing -TimeoutSec 60
        $pHtml = $pResp.Content
        $shortName = ($label -replace '[^A-Za-z0-9]+', '_')
        $pFile = Join-Path $BASE_DIR ('portal_' + $shortName + '.html')
        $pHtml | Out-File -FilePath $pFile -Encoding UTF8
        $textInputs = [regex]::Matches($pHtml, '<input\b[^>]*\btype\s*=\s*["'']text["''][^>]*>', 'IgnoreCase')
        $names = @()
        foreach ($ti in $textInputs) {
            $nm = [regex]::Match($ti.Value, '\bname\s*=\s*["'']([^"'']+)["'']', 'IgnoreCase')
            if ($nm.Success) { $names += $nm.Groups[1].Value }
        }
        Write-Output ('  status=' + [int]$pResp.StatusCode + ' length=' + $pHtml.Length + ' textFields=' + $names.Count)
        if ($pResp.Headers['Set-Cookie']) { Write-Output ('  Set-Cookie: ' + [string]$pResp.Headers['Set-Cookie']) }
        if ($pResp.Headers['Token']) { Write-Output ('  Token header: ' + [string]$pResp.Headers['Token']) }
        if ($names.Count -gt 0) { Write-Output ('  text fields: ' + ($names -join ', ')) }
        Write-Output ('  saved: ' + $pFile)
    } catch {
        Write-Output ('  portal request failed: ' + $_.Exception.Message)
    }
}

# Download the portal's shared JS so the query logic can be replicated
if ($portalOrigin) {
    $jsFiles = @(
        '/Scripts/MyDefineScripts/MyDefineFunc.js',
        '/DefineLibrary/Scripts/Mybasejs.js'
    )
    $jsIndex = 0
    foreach ($jsPath in $jsFiles) {
        $jsIndex++
        $jsUrl = $portalOrigin + $jsPath
        try {
            $jsResp = Invoke-WebRequest -Uri $jsUrl -WebSession $session -UseBasicParsing
            $jsFile = Join-Path $BASE_DIR ('portal_js_' + $jsIndex + '.js')
            $jsResp.Content | Out-File -FilePath $jsFile -Encoding UTF8
            Write-Output ('  JS saved: ' + $jsFile + ' (' + $jsResp.Content.Length + ' chars)')
        } catch {
            Write-Output ('  JS fetch failed (' + $jsPath + '): ' + $_.Exception.Message)
        }
    }
}

# ---- Step 10: ACF Test Data search (looking for sensorID) ----
Write-Output 'Step 10: ACF Test Data search...'
$acfMatch = $null
foreach ($fc in $framesToScan) {
    $m = [regex]::Match($fc, "openPage\(\s*\d+\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*\)[^>]*>\s*ACF Test Data", 'IgnoreCase')
    if ($m.Success) { $acfMatch = $m; break }
}
if (-not $acfMatch) {
    Write-Output '  ACF Test Data not found in the menu.'
} elseif (-not $sn) {
    Write-Output '  no SN provided.'
} else {
    $acfUrl = $acfMatch.Groups[1].Value
    $acfOrigin = (New-Object System.Uri($acfUrl)).GetLeftPart([System.UriPartial]::Authority)
    $acfBody = 'p=' + $acfMatch.Groups[2].Value + '&p=' + $acfMatch.Groups[3].Value + '&p=' + $acfMatch.Groups[4].Value + '&userID=' + $acfMatch.Groups[5].Value
    try {
        $acfPage = Invoke-WebRequest -Uri $acfUrl -Method Post -Body $acfBody -ContentType 'application/x-www-form-urlencoded' -WebSession $session -UseBasicParsing
        $acfHtml = $acfPage.Content
        if ($acfPage.Headers['Set-Cookie']) { Write-Output ('  portal Set-Cookie: ' + [string]$acfPage.Headers['Set-Cookie']) }
        $fields = Get-FormFields $acfHtml

        # enumerate SearchType options via GetList (same call the page's JS makes)
        $pick = ''
        try {
            $sendJson = '[{"Key":"MCType","Parametertype":1,"Value":"acfbondnewdatabak"},{"Key":"SearchType","Parametertype":1,"Value":null},{"Key":"starttime","Parametertype":2,"Value":null},{"Key":"endtime","Parametertype":2,"Value":null},{"Key":"Condition","Parametertype":3,"Value":null}]'
            $rpmJson = '{"ClassName":"MESReportTeamplate.Report.ACF_TestData_WM","MethodName":"SearchType","SendParameters":' + $sendJson + ',"Othervalue":["' + $acfMatch.Groups[2].Value + '","' + $acfMatch.Groups[3].Value + '","' + $acfMatch.Groups[4].Value + '","' + $acfMatch.Groups[5].Value + '"]}'
            $glBody = @{ Jsonstr = $rpmJson }
            $glResp = Invoke-WebRequest -Uri ($acfOrigin + '/ReportPortal/GetList') -Method Post -Body $glBody -WebSession $session -UseBasicParsing -TimeoutSec 60
            $glJson = $glResp.Content | ConvertFrom-Json
            Write-Output ('  GetList Resultflag=' + $glJson.Resultflag + ' Message=' + $glJson.Message)
            Write-Output ('  GetList raw: ' + $glResp.Content)
            if ($glJson.Resultflag -eq '1') {
                $opts = $glJson.Resultvalue
                $optsJson = $opts | ConvertTo-Json -Depth 6 -Compress
                Write-Output ('  SearchType options: ' + $optsJson)
                foreach ($o in $opts) {
                    foreach ($v in $o.Value) {
                        if ([string]$v.Id -eq 'SN' -or [string]$v.Value -eq 'SN') { $pick = [string]$v.Id }
                    }
                }
                if (-not $pick) {
                    foreach ($o in $opts) {
                        foreach ($v in $o.Value) {
                            if (([string]$v.Id) -match '^SN' -or ([string]$v.Value) -match '^SN') { $pick = [string]$v.Id; break }
                        }
                        if ($pick) { break }
                    }
                }
                if ($pick) { Write-Output ('  using SearchType=' + $pick) }
            }
        } catch {
            Write-Output ('  GetList failed: ' + $_.Exception.Message)
        }

        $tokenVal = ''
        $tokM = [regex]::Match($acfHtml, '<input\b[^>]*\bname="token"[^>]*>', 'IgnoreCase')
        if ($tokM.Success) {
            $tv = [regex]::Match($tokM.Value, 'value="([^"]*)"', 'IgnoreCase')
            if ($tv.Success) { $tokenVal = $tv.Groups[1].Value }
        }

        $searchFields = @{}
        foreach ($k in $fields.Keys) {
            if ($k -eq 'token') { continue }
            $searchFields[$k] = $fields[$k]
        }
        # decode HTML entities (e.g. OtherValue contains &quot; in the page source)
        $decodedFields = @{}
        foreach ($k in $searchFields.Keys) {
            $decodedFields[$k] = [System.Net.WebUtility]::HtmlDecode([string]$searchFields[$k])
        }
        $searchFields = $decodedFields
        if (-not $searchFields.ContainsKey('MCType') -or -not $searchFields['MCType']) { $searchFields['MCType'] = 'acfbondnewdatabak' }
        if ($pick) { $searchFields['SearchType'] = $pick } else { $searchFields['SearchType'] = 'SN' }
        $searchFields['Condition'] = $sn
        $searchFields['starttime'] = '06/01/2026 00:00'
        $searchFields['endtime'] = '08/08/2026 23:59'
        Write-Output ('  OtherValue=' + $searchFields['OtherValue'])

        $boundary = '----CodexBoundary' + [guid]::NewGuid().ToString('N')
        $sb = New-Object System.Text.StringBuilder
        foreach ($k in $searchFields.Keys) {
            [void]$sb.Append('--' + $boundary + "`r`n")
            [void]$sb.Append('Content-Disposition: form-data; name="' + $k + '"' + "`r`n`r`n")
            [void]$sb.Append([string]$searchFields[$k] + "`r`n")
        }
        [void]$sb.Append('--' + $boundary + "--`r`n")

        $headers = @{}
        if ($tokenVal) { $headers['Authorization'] = 'Bearer ' + $tokenVal }
        Write-Output ('  search: MCType=' + $searchFields['MCType'] + ' SearchType=' + $searchFields['SearchType'] + ' Condition=' + $sn + ' token=' + $tokenVal)
        $sResp = Invoke-WebRequest -Uri ($acfOrigin + '/ReportPortal/Search') -Method Post -Body $sb.ToString() -ContentType ('multipart/form-data; boundary=' + $boundary) -Headers $headers -WebSession $session -UseBasicParsing -TimeoutSec 120
        $sHtml = $sResp.Content
        $sFile = Join-Path $BASE_DIR 'portal_search_acf.html'
        $sHtml | Out-File -FilePath $sFile -Encoding UTF8
        Write-Output ('  status=' + [int]$sResp.StatusCode + ' length=' + $sHtml.Length + ' saved: ' + $sFile)
        $visible = ($sHtml -replace '<[^>]+>', ' ') -replace '\s+', ' '
        if ($visible.Length -gt 300) { $visible = $visible.Substring(0, 300) }
        Write-Output ('  preview: ' + $visible)

        # download the generated Excel export and the station images
        $dlDir = Join-Path $BASE_DIR 'downloads'
        New-Item -ItemType Directory -Force -Path $dlDir | Out-Null
        $xlsm = [regex]::Match($sHtml, 'href="([^"]*\.xlsx[^"]*)"', 'IgnoreCase')
        if ($xlsm.Success) {
            $xlsUrl = [System.Net.WebUtility]::HtmlDecode($xlsm.Groups[1].Value) -replace '\\', '/'
            Write-Output ('  Excel: ' + $xlsUrl)
            try {
                $xlsFile = Join-Path $dlDir 'acf_testdata.xlsx'
                Invoke-WebRequest -Uri $xlsUrl -OutFile $xlsFile -WebSession $session -UseBasicParsing -TimeoutSec 120
                Write-Output ('  Excel saved: ' + $xlsFile + ' (' + (Get-Item $xlsFile).Length + ' bytes)')
            } catch {
                Write-Output ('  Excel download failed: ' + $_.Exception.Message)
            }
        }
        $imgUrls = @([regex]::Matches($sHtml, 'href="(http://cma1[^"]*\.jpg[^"]*)"', 'IgnoreCase') | ForEach-Object { [System.Net.WebUtility]::HtmlDecode($_.Groups[1].Value) })
        Write-Output ('  ACF images found: ' + $imgUrls.Count)
        if ($imgUrls.Count -gt 0) {
            $imgListFile = Join-Path $dlDir 'acf_images.txt'
            $imgUrls | Out-File -FilePath $imgListFile -Encoding UTF8
            Write-Output ('  image list saved: ' + $imgListFile)
            $firstImg = Join-Path $dlDir 'acf_test.jpg'
            try {
                Invoke-WebRequest -Uri $imgUrls[0] -OutFile $firstImg -WebSession $session -UseBasicParsing -TimeoutSec 60
                Write-Output ('  test image saved: ' + $firstImg + ' (' + (Get-Item $firstImg).Length + ' bytes)')
            } catch {
                Write-Output ('  image download failed: ' + $_.Exception.Message)
            }
        }
    } catch {
        $errMsg = $_.Exception.Message
        try {
            $errResp = $_.Exception.Response
            if ($errResp) {
                $sReader = New-Object System.IO.StreamReader($errResp.GetResponseStream())
                $errBody = $sReader.ReadToEnd()
                $sReader.Close()
                $errBody = ($errBody -replace '<[^>]+>', ' ') -replace '\s+', ' '
                if ($errBody.Length -gt 600) { $errBody = $errBody.Substring(0, 600) }
                Write-Output ('  server response: ' + $errBody)
            }
        } catch {}
        Write-Output ('  ACF search failed: ' + $errMsg)
    }
}
Write-Output 'Done.'
exit 0
