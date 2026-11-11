# Remove Meerkat installed by install.ps1.
#
#   irm https://raw.githubusercontent.com/owenpanusorn/meerkat-posture/main/uninstall.ps1 | iex
#
# Removes the program folder, the Start Menu shortcut and the sign-in autostart entry.
# Your settings and stats (%APPDATA%\meerkat) are kept unless MEERKAT_PURGE=1.
#
# Options (environment variables):
#   MEERKAT_INSTALL_DIR  install folder (default: %LOCALAPPDATA%\Programs\Meerkat)
#   MEERKAT_PURGE        1 = also delete settings, stats and logs (%APPDATA%\meerkat)

& {
    $ErrorActionPreference = 'Stop'
    $Dir = if ($env:MEERKAT_INSTALL_DIR) { $env:MEERKAT_INSTALL_DIR } else {
        Join-Path $env:LOCALAPPDATA 'Programs\Meerkat'
    }
    $Dir = [IO.Path]::GetFullPath($Dir)
    $Exe = Join-Path $Dir 'Meerkat.exe'
    $Shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'Meerkat.lnk'
    $RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'

    function Say($msg) { Write-Host "  $msg" }
    function InDir($path) { $path -and $path.Trim('"').StartsWith($Dir, [StringComparison]::OrdinalIgnoreCase) }

    Write-Host 'Uninstalling Meerkat...'

    $running = @(Get-Process Meerkat -ErrorAction SilentlyContinue | Where-Object { InDir $_.Path })
    if ($running) {
        Say 'closing Meerkat...'
        $running | Stop-Process -Force
        $running | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue
    }

    $run = (Get-ItemProperty $RunKey -Name Meerkat -ErrorAction SilentlyContinue).Meerkat
    if (InDir $run) {
        Remove-ItemProperty $RunKey -Name Meerkat
        Say 'removed: start at sign-in'
    }

    if (Test-Path $Shortcut) {
        $target = (New-Object -ComObject WScript.Shell).CreateShortcut($Shortcut).TargetPath
        if (InDir $target) {
            Remove-Item $Shortcut -Force
            Say 'removed: Start Menu shortcut'
        }
    }

    if (Test-Path $Exe) {
        Remove-Item $Dir -Recurse -Force
        Say "removed: $Dir"
    } elseif (Test-Path $Dir) {
        Say "skipped: $Dir has no Meerkat.exe, left as is"
    } else {
        Say "not installed in $Dir"
    }

    $data = Join-Path $env:APPDATA 'meerkat'
    if ($env:MEERKAT_PURGE -eq '1') {
        if (Test-Path $data) {
            Remove-Item $data -Recurse -Force
            Say "removed: settings and stats ($data)"
        }
    } elseif (Test-Path $data) {
        Say "kept your settings and stats in $data (set MEERKAT_PURGE=1 to delete them)"
    }

    Write-Host 'Done.'
}
