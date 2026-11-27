# power-saver guard. The power-saver scheduled task runs this as SYSTEM: at startup, every few minutes, and when
# `power-saver on` / `off` start the task. Setup copies it to the admin-only folder; the task runs that copy.
#
# What it trusts, and what it doesn't:
#   config.json  admin-only: the tool paths, the saver plan, the shares and margins (clamped again here).
#   mode         the one file Users can write. Only the words on/off are accepted; anything else is off, and logged.
#                No number, path or command is ever read from it.
#   tools        nvidia-smi and powercfg by the absolute paths in config.json, never through PATH.
#
# What it does each run: keeps the power plan in step with the mode, sets each NVIDIA GPU's power limit (a share of
# its default while on, the default while off, lower again when the card runs hot, with hysteresis), and appends one
# JSON line to guard.log. Windows PowerShell 5.1; ASCII only.
param([string]$Root = (Join-Path $env:ProgramData 'power-saver'))

$ErrorActionPreference = 'Continue'
$inv = [Globalization.CultureInfo]::InvariantCulture
$guidRe = '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
$balanced = '381b4222-f694-41f0-9685-ff5bb260df2e'
$log = Join-Path $Root 'guard.log'
$entry = [ordered]@{ t = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ', $inv) }
$notes = New-Object System.Collections.ArrayList
$events = New-Object System.Collections.ArrayList

function Write-GuardLog {
    $entry['notes'] = @($notes)
    $entry['events'] = @($events)
    Add-Content -LiteralPath $log -Value (ConvertTo-Json $entry -Compress -Depth 6) -Encoding UTF8
    $item = Get-Item -LiteralPath $log -ErrorAction SilentlyContinue
    if ($item -and $item.Length -gt 2MB) {
        $keep = Get-Content -LiteralPath $log -Tail 5000
        Set-Content -LiteralPath "$log.tmp" -Value $keep -Encoding UTF8
        Move-Item -LiteralPath "$log.tmp" -Destination $log -Force
    }
}

function ConvertTo-Number([string]$s) {
    if ($null -eq $s) { return $null }
    $s = $s.Trim()
    $d = 0.0
    if ([double]::TryParse($s, [Globalization.NumberStyles]::Float, $inv, [ref]$d)) { return $d }
    return $null
}

function Get-Clamped($value, [double]$lo, [double]$hi, [double]$fallback) {
    $d = ConvertTo-Number ([string]$value)
    if ($null -eq $d) { return $fallback }
    return [math]::Min($hi, [math]::Max($lo, $d))
}

# ---- config (admin-only) ----
$cfgPath = Join-Path $Root 'config.json'
try { $cfg = Get-Content -LiteralPath $cfgPath -Raw -ErrorAction Stop | ConvertFrom-Json }
catch { $entry['mode'] = 'off'; [void]$notes.Add('config.json missing or unreadable: nothing changed'); Write-GuardLog; exit 1 }

$share = Get-Clamped $cfg.gpu_share 0.3 1.0 0.7
$hotShareOn = Get-Clamped $cfg.gpu_hot_share_on 0.3 1.0 0.6
$hotShareOff = Get-Clamped $cfg.gpu_hot_share_off 0.3 1.0 0.78
$marginOn = Get-Clamped $cfg.hot_margin_on 0 40 6
$marginOff = Get-Clamped $cfg.hot_margin_off 0 40 2
$tempOn = Get-Clamped $cfg.hot_temp_on 50 105 83
$tempOff = Get-Clamped $cfg.hot_temp_off 50 105 87
$hyst = Get-Clamped $cfg.hysteresis 1 20 5

# ---- mode (the only file Users can write: one word, nothing else) ----
$mode = 'off'
$modePath = Join-Path $Root 'mode'
if (Test-Path -LiteralPath $modePath -PathType Leaf) {
    $item = Get-Item -LiteralPath $modePath
    $word = $null
    if ($item.Length -le 16) { $word = ([IO.File]::ReadAllText($modePath)).Trim().ToLowerInvariant() }
    if ($word -eq 'on' -or $word -eq 'off') { $mode = $word }
    else { [void]$notes.Add('the mode file holds something other than on/off: treated as off') }
} else { [void]$notes.Add('the mode file is missing: treated as off') }
$entry['mode'] = $mode

# ---- the power plan, kept in step with the mode ----
$pc = [string]$cfg.powercfg
$saver = ([string]$cfg.saver_plan).ToLowerInvariant()
$fallback = ([string]$cfg.fallback_plan).ToLowerInvariant()
if ($fallback -notmatch $guidRe) { $fallback = $balanced }
if ($pc -and (Test-Path -LiteralPath $pc -PathType Leaf) -and $saver -match $guidRe) {
    $out = (& $pc /getactivescheme) -join ' '
    $m = [regex]::Match($out, '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
    $active = if ($m.Success) { $m.Value.ToLowerInvariant() } else { '' }
    if ($mode -eq 'on' -and $active -ne $saver) {
        & $pc /setactive $saver | Out-Null
        [void]$events.Add("plan: saver plan put back (was $active)")
    } elseif ($mode -eq 'off' -and $active -eq $saver) {
        & $pc /setactive $fallback | Out-Null
        [void]$events.Add("plan: mode is off, so the saver plan was replaced by $fallback")
    }
    $entry['plan'] = $active
} else { [void]$notes.Add('powercfg path or saver plan missing from config.json') }

# ---- GPUs ----
$gpus = New-Object System.Collections.ArrayList
$smi = [string]$cfg.nvidia_smi
if ($smi -and (Test-Path -LiteralPath $smi -PathType Leaf)) {
    $statePath = Join-Path $Root 'state.json'
    $hotWas = @{}
    try { $st = Get-Content -LiteralPath $statePath -Raw -ErrorAction Stop | ConvertFrom-Json
          foreach ($p in $st.PSObject.Properties) { $hotWas[$p.Name] = [bool]$p.Value } } catch { }
    $hotNow = @{}
    $fields = 'index,uuid,name,power.limit,power.default_limit,power.min_limit,power.max_limit,power.draw,temperature.gpu'
    $rows = & $smi "--query-gpu=$fields" '--format=csv,noheader,nounits' 2>$null
    if ($LASTEXITCODE -ne 0) { [void]$notes.Add("nvidia-smi failed ($LASTEXITCODE)"); $rows = @() }
    $tl = @{}
    $trows = & $smi '--query-gpu=uuid,temperature.gpu.tlimit' '--format=csv,noheader,nounits' 2>$null
    if ($LASTEXITCODE -eq 0) {
        foreach ($line in @($trows)) { $q = ([string]$line).Split(','); if ($q.Count -eq 2) { $tl[$q[0].Trim()] = ConvertTo-Number $q[1] } }
    }
    foreach ($line in @($rows)) {
        $p = ([string]$line).Split(',')
        if ($p.Count -ne 9 -or $p[0].Trim() -notmatch '^\d+$') { continue }
        $uuid = $p[1].Trim()
        $g = [ordered]@{ i = [int]$p[0].Trim(); uuid = $uuid; name = $p[2].Trim()
            limit = ConvertTo-Number $p[3]; default = ConvertTo-Number $p[4]; min = ConvertTo-Number $p[5]
            max = ConvertTo-Number $p[6]; draw = ConvertTo-Number $p[7]; temp = ConvertTo-Number $p[8]
            tlimit = $tl[$uuid] }
        if ($null -eq $g.default -or $null -eq $g.min -or $null -eq $g.max -or $g.max -le $g.min -or
            $uuid -notmatch '^GPU-[0-9a-fA-F-]+$') {
            $g['result'] = 'skipped'; $g['why'] = 'power limit not adjustable on this card'
            [void]$gpus.Add($g); continue
        }
        # Heat: T.Limit (degrees left before the card slows itself) when the card reports it, else the temperature.
        $was = [bool]$hotWas[$uuid]
        $hot = $false
        if ($null -ne $g.tlimit) {
            $margin = if ($mode -eq 'on') { $marginOn } else { $marginOff }
            $hot = if ($was) { $g.tlimit -lt ($margin + $hyst) } else { $g.tlimit -le $margin }
        } elseif ($null -ne $g.temp) {
            $limitT = if ($mode -eq 'on') { $tempOn } else { $tempOff }
            $hot = if ($was) { $g.temp -gt ($limitT - $hyst) } else { $g.temp -ge $limitT }
        }
        $hotNow[$uuid] = $hot
        $g['hot'] = $hot
        if ($mode -eq 'on') { $s = if ($hot) { $hotShareOn } else { $share } }
        else { $s = if ($hot) { $hotShareOff } else { 1.0 } }
        $want = [math]::Floor([math]::Min($g.max, [math]::Max($g.min, $g.default * $s)))
        if ($want -lt $g.min) { $want = [math]::Ceiling($g.min) }
        $want = [int]$want
        $g['want'] = $want
        $g['result'] = 'ok'
        if ($null -eq $g.limit -or [math]::Abs($g.limit - $want) -ge 1) {
            & $smi -i $uuid -pl $want 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { $g['result'] = 'set'; [void]$events.Add("GPU $($g.i): limit $($g.limit) W -> $want W") }
            else { $g['result'] = 'failed'; $g['why'] = "nvidia-smi -pl $want refused (exit $LASTEXITCODE)" }
        }
        if ($hot -and -not $was) { [void]$events.Add("hot: GPU $($g.i) held at $want W (temp $($g.temp), T.Limit $($g.tlimit))") }
        if ($was -and -not $hot) { [void]$events.Add("cool: GPU $($g.i) released (temp $($g.temp), T.Limit $($g.tlimit))") }
        [void]$gpus.Add($g)
    }
    try { ConvertTo-Json $hotNow -Compress | Set-Content -LiteralPath $statePath -Encoding ASCII } catch { }
}
$entry['gpus'] = @($gpus)

try { $entry['cpu'] = [int][math]::Round((Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average) }
catch { $entry['cpu'] = $null }
Write-GuardLog
exit 0
