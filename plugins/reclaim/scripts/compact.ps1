# reclaim compact: the one admin step. `reclaim docker compact` starts it elevated (one UAC prompt) after it has
# checked that Docker Desktop is quit and nothing holds the disk, and reads back the result file this writes.
# Windows PowerShell 5.1; ASCII only.
#
# Shrinks a dynamic VHDX (Docker's docker_data.vhdx or ext4.vhdx) to the space it really uses:
#   Optimize-VHD -Mode Full when the Hyper-V tools are installed, else diskpart (attach read-only, compact
#   vdisk, detach). The disk is never written to by this script; only its unused blocks are given back.
#
# -DryRun lists the steps and changes nothing (it does not need admin).
param(
    [Parameter(Mandatory = $true)][string]$Vhdx,
    [string]$ResultFile = '',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$result = [ordered]@{ ok = $false; vhdx = $Vhdx; steps = @() }

function Save-Result {
    if ($ResultFile) {
        ($result | ConvertTo-Json -Compress -Depth 4) | Set-Content -LiteralPath $ResultFile -Encoding UTF8
    }
}

function Invoke-Diskpart([string[]]$Lines) {
    $script = [IO.Path]::GetTempFileName()
    try {
        Set-Content -LiteralPath $script -Value ($Lines -join "`r`n") -Encoding ASCII
        $out = & (Join-Path $env:SystemRoot 'System32\diskpart.exe') /s $script 2>&1 | Out-String
        return @{ code = $LASTEXITCODE; out = $out.Trim() }
    } finally {
        Remove-Item -LiteralPath $script -Force -ErrorAction SilentlyContinue
    }
}

try {
    if ($Vhdx.Contains('"')) { throw 'the disk path holds a quote' }
    if (-not (Test-Path -LiteralPath $Vhdx -PathType Leaf)) { throw "no such disk: $Vhdx" }
    if ([IO.Path]::GetExtension($Vhdx) -notin @('.vhdx', '.vhd')) { throw 'not a VHD or VHDX file' }
    $result.before = (Get-Item -LiteralPath $Vhdx).Length
    $hyperv = [bool](Get-Command Optimize-VHD -ErrorAction SilentlyContinue)
    $result.tool = $(if ($hyperv) { 'Optimize-VHD' } else { 'diskpart' })
    if ($DryRun) {
        $result.steps = $(if ($hyperv) { @("Optimize-VHD -Path `"$Vhdx`" -Mode Full") } else {
            @("select vdisk file=`"$Vhdx`"", 'attach vdisk readonly', 'compact vdisk', 'detach vdisk') })
        $result.ok = $true
        $result.dry_run = $true
        Save-Result
        exit 0
    }
    $me = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'compact must run elevated' }

    if ($hyperv) {
        Optimize-VHD -Path $Vhdx -Mode Full
        $result.steps += 'Optimize-VHD -Mode Full'
    } else {
        $attach = Invoke-Diskpart @("select vdisk file=`"$Vhdx`"", 'attach vdisk readonly')
        $result.steps += 'attach vdisk readonly'
        if ($attach.code -ne 0) { throw "diskpart could not attach the disk: $($attach.out)" }
        try {
            $compact = Invoke-Diskpart @("select vdisk file=`"$Vhdx`"", 'compact vdisk')
            $result.steps += 'compact vdisk'
            if ($compact.code -ne 0) { throw "diskpart compact failed: $($compact.out)" }
        } finally {
            $detach = Invoke-Diskpart @("select vdisk file=`"$Vhdx`"", 'detach vdisk')
            $result.steps += 'detach vdisk'
            $result.detached = ($detach.code -eq 0)
        }
    }
    $result.after = (Get-Item -LiteralPath $Vhdx).Length
    $result.ok = $true
} catch {
    $result.error = $_.Exception.Message
}
Save-Result
if ($result.ok) { exit 0 } else { exit 1 }
