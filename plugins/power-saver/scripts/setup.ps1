# power-saver setup: the one admin step. `power-saver setup` starts it elevated (one UAC prompt) and reads the
# result file it writes. Windows PowerShell 5.1; ASCII only.
#
# Install:   the admin-only folder %ProgramData%\power-saver (guard.ps1, config.json; Users may write only `mode`),
#            the saver plan (a copy of the plan that is active, CPU boost off, max processor state 99%, screens off
#            after 2 minutes, Energy Saver on), and the SYSTEM task `power-saver` that Users may run but not change.
# Uninstall: removes exactly those, and puts each GPU back to its default power limit.
#
# -DryRun lists the steps and changes nothing (it does not need admin).
param(
    [ValidateSet('Install', 'Uninstall', 'SecureFolder')][string]$Action = 'Install',
    [string]$Source = $PSScriptRoot,
    [string]$DetectFile = '',
    [string]$ResultFile = '',
    [double]$Share = -1,
    [int]$EnergySaver = -1,
    [switch]$EveryMinute,
    [string]$ReplaceDir = '',
    [string]$RemovePlan = '',
    [string]$BackPlan = '',
    [string]$Root = (Join-Path $env:ProgramData 'power-saver'),
    [string]$TaskName = 'power-saver',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$inv = [Globalization.CultureInfo]::InvariantCulture
$guidRe = '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
$anyGuid = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
$balanced = '381b4222-f694-41f0-9685-ff5bb260df2e'
$SUB_PROCESSOR = '54533251-82be-4824-96c1-47b60b740d00'
$PERFBOOSTMODE = 'be337238-0d82-4146-a960-4f3749d470c7'
$PROCTHROTTLEMAX = @('bc5038f7-23e0-4960-96da-33abaf5935ec', 'bc5038f7-23e0-4960-96da-33abaf5935ed', 'bc5038f7-23e0-4960-96da-33abaf5935ee')
$SUB_VIDEO = '7516b95f-f776-4464-8c53-06167f40cc99'
$VIDEOIDLE = '3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e'
$SUB_ENERGYSAVER = 'de830923-a562-41af-a086-e3a2c6bad2da'
$ESBATTTHRESHOLD = 'e69653ca-cf7f-4f05-aa73-cb833fa90ad4'

$pc = Join-Path $env:SystemRoot 'System32\powercfg.exe'
$psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
# nvidia-smi only from folders that only an administrator can write: a SYSTEM task must never run a user's copy.
$smi = ''
foreach ($c in @((Join-Path $env:SystemRoot 'System32\nvidia-smi.exe'),
                 (Join-Path $env:ProgramFiles 'NVIDIA Corporation\NVSMI\nvidia-smi.exe'))) {
    if (Test-Path -LiteralPath $c -PathType Leaf) { $smi = $c; break }
}

$steps = New-Object System.Collections.ArrayList
$result = [ordered]@{ ok = $false; action = $Action; dry_run = [bool]$DryRun; steps = $steps }

function Invoke-Step([string]$what, [scriptblock]$do) {
    [void]$steps.Add($what)
    if (-not $DryRun) { & $do }
}

function Save-Result {
    if ($ResultFile) { ConvertTo-Json $result -Depth 6 | Set-Content -LiteralPath $ResultFile -Encoding UTF8 }
    else { ConvertTo-Json $result -Depth 6 }
}

# Windows PowerShell 5.1 turns a native tool's stderr into a terminating error under 'Stop' once it is redirected,
# so tools run through this, with stderr dropped and the exit code left in $LASTEXITCODE.
function Invoke-Tool {
    $ErrorActionPreference = 'Continue'
    $exe = $args[0]
    $rest = @()
    if ($args.Count -gt 1) { $rest = $args[1..($args.Count - 1)] }
    & $exe @rest 2>$null
}

function Get-ActivePlan {
    $m = [regex]::Match(((& $pc /getactivescheme) -join ' '), $anyGuid)
    if ($m.Success) { return $m.Value.ToLowerInvariant() } else { return '' }
}

function Get-PlanList { return [regex]::Matches(((& $pc /list) -join "`n"), $anyGuid) | ForEach-Object { $_.Value.ToLowerInvariant() } }

function Test-Setting([string]$plan, [string]$sub, [string]$setting) {
    $out = (Invoke-Tool $pc /qh $plan $sub) -join "`n"
    return ($LASTEXITCODE -eq 0 -and $out -match [regex]::Escape($setting))
}

function Assert-NotLink([string]$path) {
    if (Test-Path -LiteralPath $path) {
        $i = Get-Item -LiteralPath $path -Force
        if ($i.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "$path is a link or junction: refusing to use it" }
    }
}

# The folder's whole DACL is replaced, not edited: protected (nothing inherited), SYSTEM and Administrators full
# control, Users read and execute. Any other entry, such as one left by whoever created the folder first, is gone.
# Everything inside is reset to inherit only that, and links inside are removed.
$FolderSddl = 'D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)'
function Set-AdminOnlyFolder([string]$path) {
    Assert-NotLink $path
    Invoke-Tool icacls $path /setowner '*S-1-5-32-544' /T /C /Q | Out-Null
    # A fresh object with only the DACL section, so only the DACL is written (Set-Acl would also rewrite the owner).
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetSecurityDescriptorSddlForm($FolderSddl, [Security.AccessControl.AccessControlSections]::Access)
    (Get-Item -LiteralPath $path -Force).SetAccessControl($acl)
    Get-ChildItem -LiteralPath $path -Force | ForEach-Object {
        if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { Remove-Item -LiteralPath $_.FullName -Force }
    }
    if (@(Get-ChildItem -LiteralPath $path -Force).Count -gt 0) { Invoke-Tool icacls (Join-Path $path '*') /reset /T /C /Q | Out-Null }
}

function Test-AdminOwned([string]$path) {
    $sid = (Get-Acl -LiteralPath $path).GetOwner([Security.Principal.SecurityIdentifier]).Value
    return ($sid -eq 'S-1-5-32-544' -or $sid -eq 'S-1-5-18')
}

try {
    if ($Action -eq 'SecureFolder') {
        # Only the folder rights, on -Root (used by the tests on a folder of their own; needs no admin there).
        Set-AdminOnlyFolder $Root
        $result.ok = $true
        $result['sddl'] = (Get-Acl -LiteralPath $Root).Sddl
        Save-Result
        exit 0
    }
    if (-not $DryRun) {
        $me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
        if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'setup must run elevated' }
    }
    $old = $null
    $cfgPath = Join-Path $Root 'config.json'
    # An earlier config is trusted only inside a folder that administrators own (one setup made).
    if ((Test-Path -LiteralPath $cfgPath -PathType Leaf) -and (Test-AdminOwned $Root) -and (Test-AdminOwned $cfgPath)) {
        Assert-NotLink $Root
        Assert-NotLink $cfgPath
        try { $old = Get-Content -LiteralPath $cfgPath -Raw | ConvertFrom-Json } catch { $old = $null }
    }

    if ($Action -eq 'Uninstall') {
        Invoke-Step "unregister the task $TaskName" {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue }
        if ($smi) {
            $rows = Invoke-Tool $smi '--query-gpu=uuid,power.limit,power.default_limit,power.min_limit,power.max_limit' '--format=csv,noheader,nounits'
            foreach ($line in @($rows)) {
                $p = ([string]$line).Split(',')
                if ($p.Count -ne 5) { continue }
                $uuid = $p[0].Trim(); $d = 0.0
                if ($uuid -match '^GPU-[0-9a-fA-F-]+$' -and [double]::TryParse($p[2].Trim(), [Globalization.NumberStyles]::Float, $inv, [ref]$d)) {
                    $w = [int][math]::Floor($d)
                    Invoke-Step "GPU $uuid back to its default limit ($w W)" { & $smi -i $uuid -pl $w | Out-Null }
                }
            }
        }
        $saver = if ($old) { ([string]$old.saver_plan).ToLowerInvariant() } else { '' }
        if ($saver -match $guidRe) {
            $plans = @(Get-PlanList)
            $back = $BackPlan.ToLowerInvariant()
            if ($back -notmatch $guidRe -or $plans -notcontains $back -or $back -eq $saver) {
                $back = ([string]$old.fallback_plan).ToLowerInvariant()
                if ($back -notmatch $guidRe -or $plans -notcontains $back) { $back = $balanced }
            }
            if ((Get-ActivePlan) -eq $saver) { Invoke-Step "switch to the plan $back" { & $pc /setactive $back | Out-Null } }
            if ($plans -contains $saver) { Invoke-Step "delete the saver plan $saver" { & $pc /delete $saver | Out-Null } }
        }
        if (Test-Path -LiteralPath $Root) {
            Assert-NotLink $Root
            Invoke-Step "remove $Root" { Remove-Item -LiteralPath $Root -Recurse -Force }
        }
        $result.ok = $true
        Save-Result
        exit 0
    }

    # ---- Install: values (an earlier config gives the defaults; every number is clamped) ----
    function Get-Old($name, $fallback) { if ($old -and $null -ne $old.$name) { return $old.$name } return $fallback }
    $sh = if ($Share -gt 0) { $Share } else { [double](Get-Old 'gpu_share' 0.7) }
    $sh = [math]::Min(1.0, [math]::Max(0.3, $sh))
    $es = if ($EnergySaver -ge 0) { [bool]$EnergySaver } else { [bool](Get-Old 'energy_saver' $true) }
    $interval = if ($EveryMinute) { 1 } else { 5 }

    # ---- the saver plan: a copy of the plan that is active now ----
    $plans = @(Get-PlanList)
    $active = Get-ActivePlan
    $saver = ([string](Get-Old 'saver_plan' '')).ToLowerInvariant()
    if ($saver -notmatch $guidRe -or $plans -notcontains $saver) { $saver = '' }
    $removePlan = $RemovePlan.ToLowerInvariant()
    if ($removePlan -and ($removePlan -notmatch $guidRe -or $removePlan -eq $balanced)) { throw "-RemovePlan must be a plan GUID other than Balanced" }
    $base = $active
    if (-not $base -or $base -eq $saver -or $base -eq $removePlan) { $base = [string](Get-Old 'fallback_plan' $balanced) }
    if ($base -notmatch $guidRe -or $plans -notcontains $base) { $base = $balanced }
    if (-not $saver) {
        $saver = [guid]::NewGuid().ToString()
        Invoke-Step "copy the plan $base as the saver plan $saver" { & $pc /duplicatescheme $base $saver | Out-Null }
    }
    Invoke-Step 'name the saver plan' {
        & $pc /changename $saver 'power-saver (unattended work)' 'CPU boost off, screens off after 2 minutes. Made by power-saver.' | Out-Null }
    $set = @()
    if ($DryRun -or (Test-Setting $saver $SUB_PROCESSOR $PERFBOOSTMODE)) { $set += , @($SUB_PROCESSOR, $PERFBOOSTMODE, 0) }
    foreach ($s in $PROCTHROTTLEMAX) {
        if ($DryRun -or (Test-Setting $saver $SUB_PROCESSOR $s)) { $set += , @($SUB_PROCESSOR, $s, 99) }
    }
    $set += , @($SUB_VIDEO, $VIDEOIDLE, 120)
    $esPresent = $DryRun -or (Test-Setting $saver $SUB_ENERGYSAVER $ESBATTTHRESHOLD)
    if ($esPresent) {
        if ($es) { $set += , @($SUB_ENERGYSAVER, $ESBATTTHRESHOLD, 100) }
        else {
            $q = (& $pc /qh $base $SUB_ENERGYSAVER $ESBATTTHRESHOLD) -join "`n"
            $hex = [regex]::Matches($q, '0x([0-9a-fA-F]+)') | ForEach-Object { [Convert]::ToInt32($_.Groups[1].Value, 16) }
            $ac = 0; if (@($hex).Count -ge 2) { $ac = @($hex)[-2] }
            $set += , @($SUB_ENERGYSAVER, $ESBATTTHRESHOLD, $ac)
        }
    }
    foreach ($row in $set) {
        $sub = $row[0]; $setting = $row[1]; $val = $row[2]
        Invoke-Step "saver plan: $setting = $val (mains and battery)" {
            & $pc /setacvalueindex $saver $sub $setting $val | Out-Null
            & $pc /setdcvalueindex $saver $sub $setting $val | Out-Null }
    }
    if ($active -eq $saver) { Invoke-Step 'apply the saver plan again (it is active)' { & $pc /setactive $saver | Out-Null } }

    # ---- an older hand-made guard, if the user chose to replace it ----
    if ($ReplaceDir) {
        $full = [IO.Path]::GetFullPath($ReplaceDir).TrimEnd('\')
        $pd = [IO.Path]::GetFullPath($env:ProgramData).TrimEnd('\')
        if (-not $full.StartsWith($pd + '\', [StringComparison]::OrdinalIgnoreCase) -or
            $full -ieq [IO.Path]::GetFullPath($Root).TrimEnd('\')) { throw "-ReplaceDir must be a folder under $pd" }
        $old_tasks = @(Get-ScheduledTask | Where-Object { ($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -match [regex]::Escape($full) })
        foreach ($t in $old_tasks) {
            $tn = $t.TaskName; $tp = $t.TaskPath
            Invoke-Step "unregister the older task $tp$tn (it runs a script in $full; the folder stays)" {
                Unregister-ScheduledTask -TaskName $tn -TaskPath $tp -Confirm:$false }
        }
    }
    if ($removePlan -and $plans -contains $removePlan -and $removePlan -ne $saver) {
        if ($active -eq $removePlan) { Invoke-Step "switch from the older plan to $base" { & $pc /setactive $base | Out-Null } }
        Invoke-Step "delete the older plan $removePlan" { & $pc /delete $removePlan | Out-Null }
    }

    # ---- the admin-only folder: owner Administrators, SYSTEM and Administrators full, Users read; mode Users modify ----
    Assert-NotLink $Root
    Invoke-Step "make $Root admin-only (Users: read; the mode file: modify)" {
        New-Item -ItemType Directory -Path $Root -Force | Out-Null
        Set-AdminOnlyFolder $Root
    }
    $modePath = Join-Path $Root 'mode'
    Invoke-Step 'write guard.ps1 and the mode file' {
        $g = Join-Path $Root 'guard.ps1'
        if (Test-Path -LiteralPath $g) { Remove-Item -LiteralPath $g -Force }
        Copy-Item -LiteralPath (Join-Path $Source 'guard.ps1') -Destination $g
        $word = 'off'
        if (Test-Path -LiteralPath $modePath -PathType Leaf) {
            $w = ([IO.File]::ReadAllText($modePath)).Trim().ToLowerInvariant()
            if ($w -eq 'on') { $word = 'on' }
            Remove-Item -LiteralPath $modePath -Force
        }
        [IO.File]::WriteAllText($modePath, "$word`n")
        Invoke-Tool icacls $modePath /grant '*S-1-5-32-545:M' /Q | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'could not give Users modify rights on the mode file' }
    }

    # ---- the task: SYSTEM, at startup and every $interval minutes, one instance at a time ----
    $guardPath = Join-Path $Root 'guard.ps1'
    function Register-Guard([int]$minutes) {
        $act = New-ScheduledTaskAction -Execute $psExe -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$guardPath`""
        $trig = @((New-ScheduledTaskTrigger -AtStartup),
                  (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $minutes)))
        $prin = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
            -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
        Register-ScheduledTask -TaskName $TaskName -Action $act -Trigger $trig -Principal $prin -Settings $set -Force | Out-Null
    }
    Invoke-Step "register the task $TaskName (SYSTEM, at startup and every $interval minutes)" { Register-Guard $interval }

    # Users may read and run the task, never change it: one ACE, (A;;GRGX;;;BU), added to the task's DACL.
    # Whether a standard account can then really start it is checked afterwards, unelevated, by `power-saver setup`.
    $runRights = $false
    Invoke-Step 'let Users run the task (read + execute on its security descriptor)' {
        try {
            $svc = New-Object -ComObject Schedule.Service
            $svc.Connect()
            $task = $svc.GetFolder('\').GetTask($TaskName)
            $sd = $task.GetSecurityDescriptor(4)
            if ($sd -notmatch '\(A;;GRGX;;;BU\)') { $task.SetSecurityDescriptor($sd + '(A;;GRGX;;;BU)', 0) }
            $script:runRights = $true
            $script:result['task_sddl'] = $svc.GetFolder('\').GetTask($TaskName).GetSecurityDescriptor(4)
        } catch { $script:runRights = $false; $script:result['task_sddl_error'] = $_.Exception.Message }
        if (-not $script:runRights -and $interval -ne 1) {
            # Fallback: Windows would not take the rights, so the guard repeats every minute instead.
            $script:interval = 1
            Register-Guard 1
        }
    }

    # ---- config.json (admin-only) ----
    $detected = $null
    if ($DetectFile -and (Test-Path -LiteralPath $DetectFile -PathType Leaf) -and (Get-Item -LiteralPath $DetectFile).Length -lt 262144) {
        try { $detected = Get-Content -LiteralPath $DetectFile -Raw | ConvertFrom-Json } catch { $detected = $null }
    }
    $cfg = [ordered]@{
        version = 1; powercfg = $pc; nvidia_smi = $smi; saver_plan = $saver; fallback_plan = $base
        gpu_share = $sh
        gpu_hot_share_on = [math]::Min(1.0, [math]::Max(0.3, [double](Get-Old 'gpu_hot_share_on' 0.6)))
        gpu_hot_share_off = [math]::Min(1.0, [math]::Max(0.3, [double](Get-Old 'gpu_hot_share_off' 0.78)))
        hot_margin_on = [double](Get-Old 'hot_margin_on' 6); hot_margin_off = [double](Get-Old 'hot_margin_off' 2)
        hot_temp_on = [double](Get-Old 'hot_temp_on' 83); hot_temp_off = [double](Get-Old 'hot_temp_off' 87)
        hysteresis = [double](Get-Old 'hysteresis' 5)
        energy_saver = $es; screen_off_minutes = 2
        interval_minutes = $interval; run_rights = $runRights
        detected = $detected
    }
    Invoke-Step 'write config.json' {
        if (Test-Path -LiteralPath $cfgPath) { Remove-Item -LiteralPath $cfgPath -Force }
        ConvertTo-Json $cfg -Depth 8 | Set-Content -LiteralPath $cfgPath -Encoding UTF8
    }
    Invoke-Step 'start the task once' { Start-ScheduledTask -TaskName $TaskName }
    $result.ok = $true
    $result['saver_plan'] = $saver
    $result['copied_from'] = $base
    $result['nvidia_smi'] = $smi
    $result['run_rights'] = $runRights
    $result['interval_minutes'] = $interval
    Save-Result
    exit 0
} catch {
    $result['error'] = $_.Exception.Message
    Save-Result
    exit 1
}
