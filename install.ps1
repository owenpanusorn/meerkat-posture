# Meerkat installer for Windows: per-user, no admin rights, no Python needed.
#
#   irm https://raw.githubusercontent.com/owenpanusorn/meerkat-posture/main/install.ps1 | iex
#
# Downloads the latest GitHub Release (Meerkat-windows-x64.zip), checks its SHA-256,
# installs to %LOCALAPPDATA%\Programs\Meerkat, adds a Start Menu shortcut and starts it.
# Running it again updates Meerkat. Your settings and stats (%APPDATA%\meerkat) are kept.
#
# Options (environment variables, because "irm | iex" cannot pass parameters):
#   MEERKAT_VERSION      release tag to install, e.g. v0.1.0 (default: latest)
#   MEERKAT_ZIP          install from a local zip instead of downloading
#   MEERKAT_INSTALL_DIR  install folder (default: %LOCALAPPDATA%\Programs\Meerkat)
#   MEERKAT_NO_START     1 = don't start Meerkat at the end
#   GITHUB_TOKEN         only needed while the repository is private

& {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest is very slow with it on
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $Repo = 'owenpanusorn/meerkat-posture'
    $AssetName = 'Meerkat-windows-x64.zip'
    $Dir = if ($env:MEERKAT_INSTALL_DIR) { $env:MEERKAT_INSTALL_DIR } else {
        Join-Path $env:LOCALAPPDATA 'Programs\Meerkat'
    }
    $Dir = [IO.Path]::GetFullPath($Dir)
    $Exe = Join-Path $Dir 'Meerkat.exe'
    $Shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'Meerkat.lnk'

    function Say($msg) { Write-Host "  $msg" }

    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('meerkat-install-' + [guid]::NewGuid())
    New-Item -ItemType Directory $tmp | Out-Null
    try {
        Write-Host 'Installing Meerkat...'

        # ---- get the zip
        if ($env:MEERKAT_ZIP) {
            $zip = (Resolve-Path $env:MEERKAT_ZIP).Path
            $label = $null
            Say "from $zip"
        } else {
            $headers = @{ 'User-Agent' = 'meerkat-installer'; 'Accept' = 'application/vnd.github+json' }
            if ($env:GITHUB_TOKEN) { $headers['Authorization'] = "Bearer $env:GITHUB_TOKEN" }
            $which = if ($env:MEERKAT_VERSION) { "tags/$env:MEERKAT_VERSION" } else { 'latest' }
            try {
                $release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/$which" -Headers $headers
            } catch {
                throw "Cannot find release '$which' of $Repo ($($_.Exception.Message))"
            }
            $label = $release.tag_name
            $asset = $release.assets | Where-Object name -EQ $AssetName
            $sumAsset = $release.assets | Where-Object name -EQ "$AssetName.sha256"
            if (-not $asset) { throw "Release $label has no $AssetName" }

            $dl = $headers.Clone()
            $dl['Accept'] = 'application/octet-stream'
            $zip = Join-Path $tmp $AssetName
            Say ("downloading {0} ({1:N0} MB)..." -f $label, ($asset.size / 1MB))
            Invoke-WebRequest $asset.url -Headers $dl -OutFile $zip -UseBasicParsing

            if ($sumAsset) {
                $sumFile = Join-Path $tmp 'sum.txt'
                Invoke-WebRequest $sumAsset.url -Headers $dl -OutFile $sumFile -UseBasicParsing
                $expected = ((Get-Content $sumFile -Raw).Trim() -split '\s+')[0].ToLower()
                $actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
                if ($expected -ne $actual) { throw "SHA-256 mismatch: expected $expected, got $actual" }
                Say 'checksum ok'
            } else {
                Say 'warning: release has no .sha256 file, checksum not verified'
            }
        }

        # ---- unpack and sanity-check before touching the old install
        $unpacked = Join-Path $tmp 'x'
        Expand-Archive $zip $unpacked
        $src = Join-Path $unpacked 'Meerkat'
        if (-not (Test-Path (Join-Path $src 'Meerkat.exe'))) {
            $src = $unpacked
            if (-not (Test-Path (Join-Path $src 'Meerkat.exe'))) { throw 'Meerkat.exe not found in the zip' }
        }

        # ---- stop a running copy from this folder (others are left alone)
        $running = @(Get-Process Meerkat -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -and $_.Path.StartsWith($Dir, [StringComparison]::OrdinalIgnoreCase)
        })
        if ($running) {
            Say 'closing the running Meerkat...'
            $running | Stop-Process -Force
            $running | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue
        }

        # ---- replace the program folder (user data lives in %APPDATA%\meerkat, not here)
        if (Test-Path $Dir) {
            $isMeerkat = Test-Path $Exe
            $isEmpty = -not (Get-ChildItem $Dir -Force | Select-Object -First 1)
            if (-not ($isMeerkat -or $isEmpty)) {
                throw "$Dir exists and is not a Meerkat folder; choose another MEERKAT_INSTALL_DIR"
            }
            Remove-Item $Dir -Recurse -Force
        }
        New-Item -ItemType Directory $Dir -Force | Out-Null
        Copy-Item (Join-Path $src '*') $Dir -Recurse -Force
        Say "installed to $Dir"

        # ---- Start Menu shortcut
        $ws = New-Object -ComObject WScript.Shell
        $lnk = $ws.CreateShortcut($Shortcut)
        $lnk.TargetPath = $Exe
        $lnk.WorkingDirectory = $Dir
        $lnk.Description = 'Meerkat posture reminder'
        $lnk.Save()
        Say 'Start Menu shortcut: Meerkat'

        # ---- start
        $other = @(Get-Process Meerkat -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -and -not $_.Path.StartsWith($Dir, [StringComparison]::OrdinalIgnoreCase)
        })
        if ($other) {
            Say "note: another Meerkat is running from $($other[0].Path)"
            Say '      quit it (tray icon > right-click) before starting this one'
        } elseif ($env:MEERKAT_NO_START -ne '1') {
            Start-Process $Exe
            Say 'started: look for the meerkat icon in the system tray'
        }

        Write-Host ('Meerkat {0}installed.' -f $(if ($label) { "$label " } else { '' }))
        Write-Host '  To start it at sign-in, tick the autostart option in its tray menu.'
    } finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
