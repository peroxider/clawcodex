# ============================================================================
#  install.ps1 — One-click installer for clawcodex on Windows / PowerShell
# ----------------------------------------------------------------------------
#  PowerShell counterpart of install.sh.  Mirrors its subcommand set, flags,
#  exit codes, and version-pinning semantics, adapted for Windows.
#
#  Tested on:
#    - Windows PowerShell 5.1 (built-in on Windows 10/11)
#    - PowerShell 7+ (pwsh)
#  Native Windows or WSL (Linux subsystem).  For WSL, prefer the bash
#  install.sh — this script targets the Windows side of things.
#
#  Usage (from a PowerShell prompt — you can paste the whole block):
#      iwr https://gitcode.com/chadwweng/clawcodex/raw/main/install.ps1 -UseBasicParsing | iex
#  Or after downloading:
#      powershell -ExecutionPolicy Bypass -File .\install.ps1
#      .\install.ps1 install
#      .\install.ps1 status
#      .\install.ps1 doctor
#      .\install.ps1 verify
#      .\install.ps1 update
#      .\install.ps1 uninstall
#      .\install.ps1 help
#
#  Subcommands:
#      (none) / install    Install clawcodex (default action).
#      status              Show current install state — no side effects.
#      doctor              Diagnose the environment — no side effects.
#      verify              Health-check an existing install — no side effects.
#      update              Pull latest and reinstall deps.
#      uninstall           Remove everything this installer created.
#      help                Show full help.
#
#  Flags (PowerShell convention: dash + PascalCase, with --kebab aliases):
#      -Ref <ref>            Override the git ref to install.
#      -InstallDir <path>    Override the project clone + venv location.
#      -ConfigDir <path>     Override the runtime config directory.
#      -NoVenv               Skip virtual-environment creation.
#      -NoSetup              Skip the post-install configuration-wizard hint.
#      -DryRun               Preview every change without applying.
#      -Yes / -Force         Assume 'yes' for any interactive prompts.
#      -LogFile <path>       Tee all output to <path>.
#      -Uninstall            Alias for the 'uninstall' subcommand.
#      -Help                 Show full help (English).
#      -HelpZh               Show help in Chinese.
#      -Version              Print installer version.
#
#  Agent-friendly features:
#      - Subcommands (status / doctor / verify) for inspection without side effects
#      - -DryRun             preview every change before applying
#      - -Yes / -Force       skip interactive prompts (assumes yes)
#      - -LogFile <path>     tee all output to a log file
#      - Non-TTY output is prefixed with '[install.ps1]' for easy log greping
#      - A final 'DONE: success|FAILED' line is emitted on every exit
# ============================================================================

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('', 'install', 'status', 'doctor', 'verify', 'update', 'uninstall', 'help')]
    [string]$Subcommand = '',

    # ---- Option flags (long form is preferred; aliases for parity with install.sh) ----
    [string]$Ref,
    [string]$InstallDir,
    [string]$ConfigDir,
    [switch]$NoVenv,
    [switch]$NoSetup,
    [switch]$DryRun,
    [switch]$Force,
    [string]$LogFile,
    [switch]$Uninstall,
    [switch]$Help,
    [switch]$HelpZh,
    [switch]$Version
)

# ============================================================================
#  Strict mode + error preferences
# ============================================================================
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'
$WarningPreference     = 'Continue'

# Ensure TLS 1.2 is used for all network calls.  On Windows PowerShell 5.1 the
# default is TLS 1.0 which causes Invoke-WebRequest / Invoke-RestMethod to
# fail when connecting to GitHub / api.github.com.  PowerShell 7+ already
# defaults to TLS 1.2, but setting it explicitly does no harm.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

# Ensure console speaks UTF-8 so non-ASCII (e.g. Chinese help) renders correctly.
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding           = [System.Text.Encoding]::UTF8
} catch {
    # Older hosts (e.g. Windows PowerShell ISE) may not support this — ignore.
}

# ============================================================================
#  Config (read-only defaults)
# ============================================================================
# Versioning scheme — mirrored from install.sh:65-66.  The version is the CalVer
# date of the release.  To install a different clawcodex version, fetch the
# install.ps1 that ships with that release tag — same rule as the bash installer.
$script:InstallerVersion  = '2026.6.24'
$script:ClawCodexVersion  = '2026.6.24'
${script:RepoRef}           = "dev-decoupling-refactor-b24b8cb"
$script:RepoUrl           = 'https://gitcode.com/chadwweng/clawcodex'

# Overridable paths.  Resolved from $env:USERPROFILE so we work under both
# the SYSTEM and the interactive user context (the latter is the common case).
$script:DefaultInstallDir = Join-Path $env:USERPROFILE '.clawcodex\clawcodex'
$script:DefaultConfigDir  = Join-Path $env:USERPROFILE '.clawcodex'
$script:LocalBin          = Join-Path $env:USERPROFILE '.local\bin'
$script:PythonMinVersion  = '3.10'
$script:EntryPoint        = 'clawcodex-dev'   # the single registered entry in pyproject.toml
$script:RcMarker          = '# clawcodex installer — managed by install.ps1'
$script:SponsorScript     = if ($MyInvocation.MyCommand.Path -and
                                (Test-Path $MyInvocation.MyCommand.Path) -and
                                $MyInvocation.MyCommand.Path -notlike "$env:TEMP\*" -and
                                $MyInvocation.MyCommand.Path -notlike "$env:LOCALAPPDATA\Temp\*") {
    $MyInvocation.MyCommand.Path
} else {
    'install.ps1'
}

# Effective (post-override) paths.  Resolved in Initialize-Config below.
$script:ClawCodexHome      = $null
$script:ClawCodexParentDir = $null
$script:ConfigDir          = $null
$script:UseVenv            = -not $NoVenv.IsPresent
$script:RunSetup           = -not $NoSetup.IsPresent
$script:AssumeYes          = $Force.IsPresent
$script:OS                 = 'unknown'
$script:ScriptStartTs      = [int][double]::Parse((Get-Date -UFormat %s))

# ============================================================================
#  UI helpers
# ============================================================================
if ($Host.UI.SupportsVirtualTerminal) {
    $script:C_Red    = "`e[0;31m"
    $script:C_Green  = "`e[0;32m"
    $script:C_Yellow = "`e[1;33m"
    $script:C_Blue   = "`e[0;34m"
    $script:C_Bold   = "`e[1m"
    $script:C_Reset  = "`e[0m"
} else {
    $script:C_Red = ''; $script:C_Green = ''; $script:C_Yellow = ''
    $script:C_Blue = ''; $script:C_Bold = ''; $script:C_Reset = ''
}

# Agent-friendly line prefix.  Emitted only when stdout/stderr is not a TTY
# (i.e. when the script is being driven by another process, an agent, a CI
# runner, or a piped tee).  Interactive users see clean output.
function script:ScriptP1 { if (-not [Console]::IsOutputRedirected -eq $false) { Write-Host '[install.ps1] ' -NoNewline } }
function script:ScriptP2 { if (-not [Console]::IsErrorRedirected  -eq $false) { [Console]::Error.Write('[install.ps1] ') } }

function script:Log-Info { param($Msg) ScriptP1; Write-Host "${C_Blue}==>${C_Reset} ${C_Bold}$Msg${C_Reset}" }
function script:Log-Ok   { param($Msg) ScriptP1; Write-Host "  ${C_Green}✓${C_Reset} $Msg" }
function script:Log-Warn { param($Msg) ScriptP1; Write-Host "  ${C_Yellow}!${C_Reset} $Msg" }
function script:Log-Err  { param($Msg) ScriptP2; [Console]::Error.WriteLine("${C_Red}✗${C_Reset} $Msg") }
function script:Log-Step { param($Msg) ScriptP1; Write-Host "`n${C_Bold}${C_Blue}>>>${C_Reset} ${C_Bold}$Msg${C_Reset}" }

# Print the script-tagged "DONE: success|FAILED" exit summary.  Mirrors
# install.sh's _on_exit_summary so log-greppers behave the same on both shells.
function script:Write-ExitSummary {
    param([int]$Rc)
    $elapsed = [int][double]::Parse((Get-Date -UFormat %s)) - $ScriptStartTs
    if ($Rc -eq 0) {
        ScriptP2
        [Console]::Error.WriteLine("DONE: SUCCESS (exit 0) after ${elapsed}s")
        if ($LogFile) {
            ScriptP2
            [Console]::Error.WriteLine("DONE: full log at: $LogFile")
        }
    } else {
        ScriptP2
        [Console]::Error.WriteLine("DONE: FAILED (exit $Rc) after ${elapsed}s")
        if ($LogFile) {
            ScriptP2
            [Console]::Error.WriteLine("DONE: failure log saved to: $LogFile")
        } else {
            ScriptP2
            [Console]::Error.WriteLine("DONE: re-run with -LogFile <path> to capture full output.")
        }
    }
}

# Run a command, or just print it under -DryRun.  Mirrors install.sh:run_or_dry.
function script:Run-OrDry {
    param([scriptblock]$Block, [string]$WhatIfText)
    if ($DryRun) {
        ScriptP1
        Write-Host "[DRY-RUN] would run: $WhatIfText"
        return
    }
    & $Block
}

# Fatal error with "next steps" hint list, mirroring install.sh:die_with_help.
function script:Die-With-Help {
    param(
        [Parameter(Mandatory)][string]$Header,
        [string[]]$NextSteps
    )
    Log-Err $Header
    if ($NextSteps -and $NextSteps.Count -gt 0) {
        [Console]::Error.WriteLine('')
        [Console]::Error.WriteLine('  Next steps to try:')
        foreach ($step in $NextSteps) { [Console]::Error.WriteLine("    -> $step") }
    }
    [Console]::Error.WriteLine('')
    [Console]::Error.WriteLine("  For diagnosis, run:    $($SponsorScript) doctor")
    [Console]::Error.WriteLine("  For full usage, run:    $($SponsorScript) -Help")
    exit 1
}

# ============================================================================
#  OS detection
# ============================================================================
function script:Detect-OS {
    # $IsWindows / $IsLinux / $IsMacOS are PowerShell 6+ automatic vars.
    # We probe them defensively so the script also runs on 5.1.
    $isWindows = $false
    $isLinux   = $false

    try {
        if (Get-Variable -Name 'IsWindows' -ErrorAction SilentlyContinue) { $isWindows = [bool]$IsWindows }
        if (Get-Variable -Name 'IsLinux'   -ErrorAction SilentlyContinue) { $isLinux   = [bool]$IsLinux }
    } catch { }

    if (-not $isWindows -and -not $isLinux) {
        # PowerShell 5.1 fallback — check the OS environment variable.
        $osName = $env:OS
        if ($osName -eq 'Windows_NT') { $isWindows = $true }
    }

    if ($isWindows) {
        # Detect WSL: the WSL interop exposes C:\Windows\System32\wsl.exe and
        # the WSL_DISTRO_NAME env var is set inside WSL-hosted PowerShell.
        if ($env:WSL_DISTRO_NAME) { return 'wsl' }
        if (Test-Path 'C:\Windows\System32\wsl.exe') {
            # WSL binary is present — could be native Win with WSL optional feature.
            # We only flip to 'wsl' if the WSL_DISTRO_NAME is set, otherwise treat
            # as plain windows.
        }
        return 'windows'
    }
    if ($isLinux) { return 'linux' }
    return 'unknown'
}

function script:Get-OsInstallHint {
    param([string]$OsType)
    switch ($OsType) {
        'windows' {
            '    Install Git for Windows:   https://git-scm.com/download/win'
            '    Or use winget:             winget install Git.Git'
            '    Or use Chocolatey:         choco install git'
        }
        'wsl' {
            '    You are inside WSL — install Git in your Linux distro:'
            '        Debian/Ubuntu : sudo apt update && sudo apt install -y git'
            '        Fedora/RHEL   : sudo dnf install -y git'
            '        Arch          : sudo pacman -S --noconfirm git'
        }
        default { '    install git via your package manager' }
    }
}

function script:Get-OsInstallHintOneLiner {
    param([string]$OsType)
    switch ($OsType) {
        'windows' { 'winget install Git.Git   (or: https://git-scm.com/download/win)' }
        'wsl'     { 'sudo apt install -y git   (or your distro package manager)' }
        default   { 'install git via your package manager' }
    }
}

# ============================================================================
#  Prerequisite: Git
# ============================================================================
function script:Check-Git {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        Log-Err 'Git is not installed.'
        Get-OsInstallHint $OS | ForEach-Object { [Console]::Error.WriteLine($_) }
        exit 1
    }
    $version = & git --version
    Log-Ok $version
}

# ============================================================================
#  Install / locate uv (Astral's Python package manager)
#  We try multiple strategies in order of reliability:
#    1. winget (built into modern Windows, most robust)
#    2. Direct binary download from GitHub releases (no temp-script issues)
# ============================================================================
function script:Install-Uv {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        $uvVer = (& uv --version) -replace '^uv\s+', ''
        Log-Ok "uv $uvVer already installed"
        return
    }

    Log-Info 'Installing uv (user-local, no admin) ...'

    if ($DryRun) {
        ScriptP1
        Write-Host "[DRY-RUN] would install uv via winget / GitHub binary"
        return
    }

    # Strategy 1: winget (available on Windows 10/11 by default)
    Log-Info 'Trying winget install ...'
    $wingetOk = $false
    try {
        $wingetCmd = Get-Command winget -ErrorAction Stop
        $wingetOk = $true
    } catch {
        Log-Warn 'winget not available — skipping to next method'
    }

    if ($wingetOk) {
        try {
            $env:Path = "$LocalBin;$((Join-Path $env:USERPROFILE '.cargo\bin'));$env:Path"
            $installArgs = @('install', '--id', 'AstralIndustries.uv', '--accept-package-agreements',
                             '--scope', 'user', '--source', 'winget', '-e')
            & winget $installArgs 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                $env:Path = "$LocalBin;$((Join-Path $env:USERPROFILE '.cargo\bin'));$env:Path"
                $uv = Get-Command uv -ErrorAction SilentlyContinue
                if ($uv) {
                    $uvVer = (& uv --version) -replace '^uv\s+', ''
                    Log-Ok "uv $uvVer installed via winget"
                    return
                }
            }
        } catch {
            Log-Warn "winget install failed: $_"
        }
    }

    # Strategy 2: Direct binary download from GitHub releases
    Log-Info 'Downloading uv from GitHub releases ...'
    $uvInstallDir = Join-Path $env:USERPROFILE '.local'
    $zipPath = $null
    try {
        # Detect architecture
        $arch = 'x86_64'
        if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { $arch = 'aarch64' }
        elseif ($env:PROCESSOR_ARCHITECTURE -eq 'ARM')   { $arch = 'aarch64' }

        $url = "https://github.com/astral-sh/uv/releases/latest/download/uv-${arch}-pc-windows-msvc.zip"
        $zipPath = Join-Path $env:TEMP "uv-${arch}.zip"
        $extractDir = Join-Path $uvInstallDir 'bin'

        # Download the zip
        Log-Info "  URL: $url"
        Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing -ErrorAction Stop | Out-Null

        # Extract
        if (-not (Test-Path $extractDir)) {
            New-Item -ItemType Directory -Path $extractDir -Force | Out-Null
        }
        Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

        # Cleanup
        Remove-Item -Path $zipPath -Force -ErrorAction SilentlyContinue

        # Verify
        $uvExe = Join-Path $extractDir 'uv.exe'
        if (Test-Path $uvExe) {
            $env:Path = "${extractDir};$env:Path"
            $uvVer = (& $uvExe --version) -replace '^uv\s+', ''
            Log-Ok "uv $uvVer installed (GitHub binary)"
            return
        }
    } catch {
        Log-Warn "GitHub binary download failed: $_"
        # Cleanup partial files (zipPath may be null if failure occurred early)
        if ($zipPath -and (Test-Path $zipPath)) {
            try { Remove-Item -Path $zipPath -Force -ErrorAction SilentlyContinue } catch { }
        }
    }

    # If all strategies fail, give the user a clear error with manual install steps
    Die-With-Help 'All uv installation methods failed.' `
        'Manual install (recommended):  iwr https://astral.sh/uv/install.ps1 -UseBasicParsing | iex' `
        "Or download:     https://github.com/astral-sh/uv/releases" `
        "Then add to PATH: $LocalBin" `
        "Retry:           $SponsorScript"
}

# ============================================================================
#  Python 3.10+ provisioning (via uv)
# ============================================================================
function script:Ensure-Python {
    if ($DryRun) {
        ScriptP1
        Write-Host "[DRY-RUN] would check for Python $PythonMinVersion+ via uv"
        return
    }

    $py = $null
    try {
        $py = & uv python find $PythonMinVersion 2>$null
    } catch { $py = $null }

    if ($py -and (Test-Path $py)) {
        $ver = & $py --version 2>&1
        Log-Ok "$ver"
        return
    }

    Log-Info "Python $PythonMinVersion+ not found — provisioning via uv (no admin) ..."
    if (-not (Run-OrDry -Block { & uv python install $PythonMinVersion } -WhatIfText "uv python install $PythonMinVersion")) {
        Die-With-Help "Failed to install Python $PythonMinVersion via uv." `
            "Retry:    $SponsorScript" `
            "Manual:   uv python install $PythonMinVersion" `
            'Or:       install Python 3.10+ from https://python.org'
    }

    $py = & uv python find $PythonMinVersion 2>$null
    if (-not $py -or -not (Test-Path $py)) {
        Die-With-Help "Python $PythonMinVersion still not found after uv install." `
            "Retry:    $SponsorScript" `
            "Diagnose: $SponsorScript doctor"
    }
    $ver = & $py --version 2>&1
    Log-Ok "$ver"
}

# ============================================================================
#  Clone or update the repo
# ============================================================================
function script:Clone-OrUpdate-Repo {
    $gitDir = Join-Path $ClawCodexHome '.git'
    if (Test-Path $gitDir) {
        Log-Info "Existing repo found at $ClawCodexHome — pulling latest changes ..."
        Push-Location $ClawCodexHome
        try {
            $savedEAP = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            & git pull --ff-only 2>&1 | Out-Null
            $pullExit = $LASTEXITCODE
            $ErrorActionPreference = $savedEAP
            if ($pullExit -eq 0) {
                Log-Ok 'Updated via fast-forward'
            } else {
                Log-Warn 'git pull --ff-only failed (likely local edits or non-FF history). Continuing with existing code.'
            }
        } finally {
            Pop-Location
        }
        return
    }

    if (Test-Path $ClawCodexHome) {
        # Exists but isn't a git repo — back it up so we don't clobber user work.
        $stamp = Get-Date -Format 'yyyyMMddHHmmss'
        $backup = "$ClawCodexHome.bak.$stamp"
        Log-Warn "$ClawCodexHome exists but is not a git checkout. Backing up to $backup"
        if ($DryRun) {
            ScriptP1
            Write-Host "[DRY-RUN] would move: $ClawCodexHome -> $backup"
        } else {
            Move-Item -LiteralPath $ClawCodexHome -Destination $backup -Force
        }
    }

    if ($DryRun) {
        ScriptP1
        Write-Host "[DRY-RUN] would create parent dir: $ClawCodexParentDir"
        ScriptP1
        Write-Host "[DRY-RUN] would clone: $RepoUrl (ref: $RepoRef) -> $ClawCodexHome"
        return
    }

    if (-not (Test-Path $ClawCodexParentDir)) {
        New-Item -ItemType Directory -Path $ClawCodexParentDir -Force | Out-Null
    }

    Log-Info "Cloning $RepoUrl (ref: $RepoRef) -> $ClawCodexHome"

    # Temporarily relax ErrorActionPreference so stderr from git (e.g. tag not
    # found on remote) triggers a non-terminating error, allowing the fallback
    # to default branch below.  Restored immediately after clone.
    $savedEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'

    # Try the pinned ref first.  This is what makes the install version-stable:
    # the matching uv.lock at REPO_REF pins every transitive dep to a known-good
    # version, so old install.ps1 + old clawcodex + old deps always line up.
    $cloneArgs = @('--depth', '1', '--branch', $RepoRef, $RepoUrl, $ClawCodexHome)
    $cloneOut = & git clone @cloneArgs 2>&1
    $cloneExit = $LASTEXITCODE
    if ($cloneExit -eq 0) {
        $ErrorActionPreference = $savedEAP
        Log-Ok "Cloned ref $RepoRef (clawcodex $ClawCodexVersion)"
        return
    }

    # The ref doesn't exist on the remote yet (e.g. tag not pushed).  Loud
    # warning, then fall back to the default branch so install can still
    # succeed in dev / pre-release scenarios.
    Log-Warn "Ref '$RepoRef' not found on $RepoUrl — falling back to default branch."
    Log-Warn "  This install will pull the LATEST clawcodex, not v$ClawCodexVersion."
    Log-Warn "  Push a '$RepoRef' git tag (or update -Ref) to enforce the version."

    $cloneOut = & git clone --depth 1 $RepoUrl $ClawCodexHome 2>&1
    $fallbackExit = $LASTEXITCODE
    $ErrorActionPreference = $savedEAP

    if ($fallbackExit -ne 0) {
        Die-With-Help 'git clone failed.' `
            'Check your network connection.' `
            "Verify:  Invoke-WebRequest -Method Head $RepoUrl" `
            "Retry:   $SponsorScript" `
            "Diagnose: $SponsorScript doctor"
    }
    Log-Ok 'Cloned default branch (clawcodex version NOT pinned)'
}

# ============================================================================
#  Initialize local release .env
# ============================================================================
function script:Ensure-Local-EnvFile {
    if ($DryRun) {
        ScriptP1
        Write-Host "[DRY-RUN] would create $ClawCodexHome\.env from .env.example if missing"
        return
    }

    $envFile     = Join-Path $ClawCodexHome '.env'
    $envExample  = Join-Path $ClawCodexHome '.env.example'

    if (Test-Path $envFile) {
        Log-Ok 'Local .env already exists (not modified)'
        return
    }

    if (Test-Path $envExample) {
        Copy-Item -LiteralPath $envExample -Destination $envFile -Force
    } else {
        $template = @(
            '# Local F-73 release credentials. Never commit real token values.'
            'GITCODE_TOKEN='
            'TEST_PYPI_TOKEN='
            '# PYPI_TOKEN='
            'GITCODE_OWNER='
            'GITCODE_REPO='
            'GITCODE_API_ROOT=https://api.gitcode.com'
        )
        Set-Content -LiteralPath $envFile -Value $template -Encoding UTF8
    }

    # 600 equivalent: remove inheritance and grant only the current user.
    try {
        $acl = Get-Acl -LiteralPath $envFile
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $env:USERNAME, 'FullControl', 'Allow')
        $acl.SetAccessRule($rule)
        Set-Acl -LiteralPath $envFile -AclObject $acl
    } catch {
        # ACL tweak is best-effort; non-fatal on environments that restrict it.
    }

    Log-Ok 'Created local .env template (fill tokens before release publishing)'
}

# ============================================================================
#  Create venv
# ============================================================================
function script:Create-Venv {
    if (-not $UseVenv) {
        Log-Info '-NoVenv specified — skipping venv creation (deps will install to system Python)'
        return
    }
    if ($DryRun) {
        ScriptP1
        Write-Host "[DRY-RUN] would run: uv venv --python $PythonMinVersion .venv   (in $ClawCodexHome)"
        return
    }

    $venvDir = Join-Path $ClawCodexHome '.venv'
    if (Test-Path $venvDir) {
        Log-Ok "Existing venv at $venvDir"
        return
    }

    Log-Info "Creating venv with Python $PythonMinVersion ..."
    Push-Location $ClawCodexHome
    try {
        & uv venv --python $PythonMinVersion .venv
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) {
        Die-With-Help 'uv venv failed.' `
            'Check:    uv --version' `
            "Retry:    $SponsorScript" `
            "Diagnose: $SponsorScript doctor"
    }
    Log-Ok 'Venv created'
}

# ============================================================================
#  Install dependencies
#  Mirrors install.sh:install_deps — try `uv sync --extra all` (lock-pinned)
#  first, fall back to `uv pip install -e ".[all]"` (fresh resolve) when the
#  installed clawcodex version predates the [all] extra or the lock is stale.
# ============================================================================
function script:Install-Deps {
    if ($DryRun) {
        ScriptP1
        Write-Host "[DRY-RUN] would run: uv sync --extra all   (in $ClawCodexHome)"
        return
    }

    Push-Location $ClawCodexHome
    try {
        Log-Info 'Installing project + [all] extra (lock-pinned to uv.lock when possible) ...'

        $venvPython = Join-Path $ClawCodexHome '.venv\Scripts\python.exe'

        if ($UseVenv) {
            if (-not (Test-Path $venvPython)) {
                Die-With-Help "Venv missing at $(Join-Path $ClawCodexHome '.venv') — run without -NoVenv or re-clone." `
                    "Retry:  $SponsorScript update"
            }
        }

        # Stage 1 — `uv sync --extra all` honors uv.lock.
        $syncOut = & uv sync --extra all 2>&1
        if ($LASTEXITCODE -eq 0) {
            Log-Ok "Dependencies installed (lock-pinned to uv.lock at $RepoRef)"
            return
        }

        # uv sync failed — inspect why and decide.
        $syncErr = ($syncOut -join "`n")

        if ($syncErr -match 'Extra `?all`? is not defined') {
            Log-Warn 'This clawcodex version has no [all] extra — falling back to uv pip install.'
            Log-Warn '  Dependency versions will be resolved fresh (NOT lock-pinned).'
            Log-Warn '  For strict version pinning, use an install.ps1 whose'
            Log-Warn '  ClawCodexVersion matches a release that includes [all].'
        } else {
            Log-Warn 'uv sync failed; falling back to uv pip install.'
            Log-Warn "  Sync error was: $syncErr"
        }

        # Stage 2 — fallback to `uv pip install -e ".[all]"`.
        $pipArgs = if ($UseVenv) { @('--python', $venvPython) } else { @('--system') }
        $pipErr = & uv pip install @pipArgs -e '.[all]' 2>&1
        if ($LASTEXITCODE -eq 0) {
            $target = if ($UseVenv) { '.venv' } else { 'system' }
            Log-Ok "Dependencies installed (fresh-resolve, NOT lock-pinned; target: $target)"
            return
        }

        $pipErrText = ($pipErr -join "`n")

        # uv's PEP 668 message has changed wording across versions; match both
        # the structured error code ('externally-managed-environment') and the
        # human message ('externally managed') defensively.
        if (-not $UseVenv -and $pipErrText -match 'externally[ -]managed') {
            Log-Warn 'System Python is externally managed (PEP 668). Retrying with --break-system-packages.'
            $retryErr = & uv pip install @pipArgs --break-system-packages -e '.[all]' 2>&1
            if ($LASTEXITCODE -ne 0) {
                Die-With-Help 'uv pip install to system failed even with --break-system-packages.' `
                    'Inspect the error above for missing system libraries.' `
                    "Retry:    $SponsorScript" `
                    "Or:       $SponsorScript uninstall ; $SponsorScript   (fresh install with venv)"
            }
            Log-Ok 'Dependencies installed (system, --break-system-packages)'
            return
        }

        Log-Err "uv pip install failed: $pipErrText"
        Die-With-Help 'Both uv sync and uv pip install failed.' `
            "Re-run with -LogFile <path> to capture full output." `
            "Retry:    $SponsorScript" `
            "Diagnose: $SponsorScript doctor" `
            "Clean:    $SponsorScript uninstall ; $SponsorScript"
    } finally {
        Pop-Location
    }
}

# ============================================================================
#  Install local Git hooks
# ============================================================================
function script:Find-Project-Python {
    if ($UseVenv) {
        foreach ($candidate in @(
            (Join-Path $ClawCodexHome '.venv\Scripts\python.exe'),
            (Join-Path $ClawCodexHome '.venv\bin\python'))) {
            if (Test-Path $candidate) { return (Resolve-Path $candidate).Path }
        }
        return $null
    }
    foreach ($candidate in @('python3', 'python')) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found) { return $found.Path }
    }
    return $null
}

function script:Install-Git-Hooks {
    Log-Info 'Installing local Git hooks (pre-commit, best-effort) ...'
    if ($DryRun) {
        ScriptP1
        Write-Host "[DRY-RUN] would run: python -m pre_commit install   (in $ClawCodexHome)"
        return
    }

    $gitDir     = Join-Path $ClawCodexHome '.git'
    $preCommit  = Join-Path $ClawCodexHome '.pre-commit-config.yaml'
    if (-not (Test-Path $gitDir) -or -not (Test-Path $preCommit)) {
        Log-Warn 'Skipping pre-commit hook install (not a Git worktree with .pre-commit-config.yaml).'
        return
    }

    $pythonBin = Find-Project-Python
    if (-not $pythonBin) {
        Log-Warn 'Skipping pre-commit hook install (project Python not found).'
        return
    }

    $preCommitAvailable = & $pythonBin -m pre_commit --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Log-Warn 'Skipping pre-commit hook install (pre-commit is not available in the install environment).'
        return
    }

    Push-Location $ClawCodexHome
    try {
        $hookOut = & $pythonBin -m pre_commit install --hook-type pre-commit 2>&1
        if ($LASTEXITCODE -eq 0) {
            Log-Ok 'Installed .git/hooks/pre-commit'
        } else {
            Log-Warn 'Could not install .git/hooks/pre-commit; run "python -m pre_commit install" manually if you develop in this checkout.'
        }
    } finally {
        Pop-Location
    }
}

# ============================================================================
#  Locate the venv's entry-point binary
# ============================================================================
function script:Find-Venv-Entry {
    param(
        [string]$VenvDir,
        [string]$Name
    )
    foreach ($candidate in @(
        (Join-Path $VenvDir "Scripts\$Name.exe"),
        (Join-Path $VenvDir "Scripts\$Name.cmd"),
        (Join-Path $VenvDir "Scripts\$Name"),
        (Join-Path $VenvDir "bin\$Name"))) {
        if (Test-Path $candidate) { return (Resolve-Path $candidate).Path }
    }
    return $null
}

# ============================================================================
#  Register global commands
#  - We write tiny .cmd wrappers in $env:USERPROFILE\.local\bin (more portable
#    than PowerShell .ps1 launchers, which require ExecutionPolicy tweaks).
#  - `clawcodex` is registered as an alias for `clawcodex-dev` (the only
#    declared entry point in pyproject.toml).
# ============================================================================
function script:Write-Wrapper {
    param(
        [string]$Name,
        [string]$Target
    )
    $wrapper = Join-Path $LocalBin "$Name.cmd"

    if (Test-Path $wrapper) {
        Remove-Item -LiteralPath $wrapper -Force
    }

    $body = '@echo off' + "`r`n" +
        'REM Auto-generated by clawcodex install.ps1 — do not edit by hand.' + "`r`n" +
        'REM Regenerate by re-running install.ps1.' + "`r`n" +
        'REM Point the runtime at the configured config dir; the wrapper itself is' + "`r`n" +
        'REM pinned to the install dir baked in at generation time, but the config' + "`r`n" +
        'REM dir can be re-pointed at runtime by the user via this env var.' + "`r`n" +
        'setlocal' + "`r`n" +
        "if `"%CLAWCODEX_CONFIG_DIR%`"==`"`" set `"CLAWCODEX_CONFIG_DIR=$ConfigDir`"" + "`r`n" +
        "`"$Target`" %*" + "`r`n" +
        'endlocal'
    if ($DryRun) {
        ScriptP1
        Write-Host "[DRY-RUN] would write: $wrapper"
        return
    }
    Set-Content -LiteralPath $wrapper -Value $body -Encoding ASCII
    Log-Ok "$wrapper -> $Target  (CLAWCODEX_CONFIG_DIR=$ConfigDir)"
}

function script:Register-Commands {
    if ($DryRun) {
        ScriptP1
        Write-Host "[DRY-RUN] would register: $LocalBin\clawcodex-dev.cmd, $LocalBin\clawcodex.cmd"
        return
    }
    if (-not (Test-Path $LocalBin)) {
        New-Item -ItemType Directory -Path $LocalBin -Force | Out-Null
    }

    $entry = $null
    if ($UseVenv) {
        $entry = Find-Venv-Entry -VenvDir (Join-Path $ClawCodexHome '.venv') -Name $EntryPoint
        if (-not $entry) {
            Die-With-Help "Entry point '$EntryPoint' not found inside $(Join-Path $ClawCodexHome '.venv') — dependency install may have failed." `
                "Retry:    $SponsorScript update" `
                "Diagnose: $SponsorScript doctor"
        }
    } else {
        foreach ($candidate in @(
            (Join-Path $LocalBin "$EntryPoint.exe"),
            (Join-Path $LocalBin "$EntryPoint.cmd"),
            (Join-Path $LocalBin "$EntryPoint"))) {
            if (Test-Path $candidate) { $entry = (Resolve-Path $candidate).Path; break }
        }
        if (-not $entry) {
            $found = Get-Command $EntryPoint -ErrorAction SilentlyContinue
            if ($found) { $entry = $found.Path }
        }
        if (-not $entry) {
            Die-With-Help "Entry point '$EntryPoint' not found on PATH after system install — check 'Get-Command $EntryPoint'." `
                "Retry:  $SponsorScript"
        }
    }

    Write-Wrapper -Name 'clawcodex-dev' -Target $entry
    Write-Wrapper -Name 'clawcodex'    -Target $entry
}

# ============================================================================
#  Add $env:USERPROFILE\.local\bin to the User PATH (persistent)
#  Mirrors install.sh:update_shell_rc — same idempotence contract: if the
#  dir is already there, no change; if not, append.
# ============================================================================
function script:Update-User-Path {
    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ([string]::IsNullOrEmpty($current)) { $current = '' }

    # Compare with normalized separators.  Windows Path is semicolon-separated
    # on user scope.
    $entries = $current -split ';' | Where-Object { $_ -and $_ -ne $LocalBin }
    if ($entries -contains $LocalBin -or ($current -split ';' | Where-Object { $_.TrimEnd('\') -ieq ($LocalBin.TrimEnd('\')) }) -contains $LocalBin) {
        Log-Ok "$LocalBin is already in User PATH"
        return
    }

    if ($DryRun) {
        ScriptP1
        Write-Host "[DRY-RUN] would append $LocalBin to User PATH"
        return
    }

    $newPath = if ($current) { "$LocalBin;$current" } else { $LocalBin }
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')

    # Reflect in the current process so the rest of this session sees it.
    $env:Path = "$LocalBin;$env:Path"

    Log-Ok "Appended $LocalBin to User PATH  (open a new shell to make it visible everywhere)"
}

# ============================================================================
#  Post-install setup hint (non-blocking)
# ============================================================================
function script:Run-PostInstall-Setup {
    if (-not $RunSetup) {
        Log-Warn 'Setup wizard skipped (-NoSetup). Run clawcodex-dev manually to configure.'
        return
    }

    Log-Info 'Post-install setup wizard is available — launching clawcodex-dev setup ...'
    # We intentionally do NOT spawn a blocking interactive REPL here.  The
    # install script must remain non-interactive so it can run unattended
    # in CI / Docker / by orchestrators.  The wizard itself is a subcommand
    # the user runs themselves; we just announce it.
    $cmd = Get-Command clawcodex-dev -ErrorAction SilentlyContinue
    if ($cmd) {
        Log-Ok 'Run one of:'
        Write-Host "    ${C_Bold}clawcodex-dev${C_RESET}          # start the interactive REPL (triggers first-run setup if config is empty)"
        Write-Host "    ${C_Bold}clawcodex-dev -Help${C_RESET}   # see all options"
    } else {
        Log-Warn 'clawcodex-dev not on PATH yet — close and reopen PowerShell first.'
    }
}

# ============================================================================
#  Inspection subcommands (no side effects — safe for agents to call)
# ============================================================================
function script:Get-InstallStatus {
    Write-Host '=== clawcodex install status ==='
    Write-Host "  Installer   : v$InstallerVersion  (would install clawcodex v$ClawCodexVersion)"
    Write-Host "  Repo URL    : $RepoUrl"
    Write-Host "  Git ref     : $RepoRef"
    Write-Host "  Install dir : $ClawCodexHome"
    Write-Host "  Config dir  : $ConfigDir"
    Write-Host "  Local bin   : $LocalBin"
    Write-Host ''

    $gitDir = Join-Path $ClawCodexHome '.git'
    if (Test-Path $gitDir) {
        Push-Location $ClawCodexHome
        try {
            $sha     = (& git rev-parse --short HEAD 2>$null) -join ''
            $branch  = (& git rev-parse --abbrev-ref HEAD 2>$null) -join ''
        } finally {
            Pop-Location
        }
        if (-not $sha)     { $sha = 'unknown' }
        if (-not $branch)  { $branch = 'unknown' }

        Write-Host '  Git state   :'
        Write-Host "    branch    : $branch"
        Write-Host "    commit    : $sha"

        $venvPython = Join-Path $ClawCodexHome '.venv\Scripts\python.exe'
        if (Test-Path $venvPython) {
            $pyVer = (& $venvPython --version 2>&1) -join ''
            Write-Host "  Venv        : present (Python: $pyVer)"
        } else {
            Write-Host "  Venv        : MISSING (run '$SponsorScript update' to recreate)"
        }
    } else {
        Write-Host "  Git state   : NOT INSTALLED (run '$SponsorScript install')"
    }

    Write-Host ''
    Write-Host '  Commands:'
    foreach ($cmd in @('clawcodex-dev', 'clawcodex')) {
        $wrapper = Join-Path $LocalBin "$cmd.cmd"
        if (Test-Path $wrapper) { Write-Host "    $wrapper : present" } else { Write-Host "    $wrapper : MISSING" }
    }
    Write-Host ''

    $resolved = Get-Command clawcodex-dev -ErrorAction SilentlyContinue
    if ($resolved) { Write-Host "  clawcodex-dev resolves to: $($resolved.Path)" }
    else { Write-Host '  clawcodex-dev NOT on PATH (open a new shell)' }
    Write-Host ''
    Write-Host '=== end of status ==='
}

# Diagnose the environment.  Exit 0 if all critical checks pass, 1 otherwise.
function script:Invoke-Doctor {
    $fail = 0; $warn = 0
    Write-Host '=== clawcodex environment doctor ==='
    Write-Host ''

    # 1. OS
    Write-Host '[1/10] OS detection'
    if ($OS -eq 'unknown') { Write-Host '        X unknown OS'; $fail++ }
    else                    { Write-Host "        OK $OS" }

    # 2. Git
    Write-Host '[2/10] Git'
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) { Write-Host "        OK $(& git --version)" }
    else {
        Write-Host '        X git not found'
        Write-Host "          install: $(Get-OsInstallHintOneLiner $OS)"
        $fail++
    }

    # 3. Python
    Write-Host "[3/10] Python >= $PythonMinVersion"
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        $py = $null
        try { $py = & uv python find $PythonMinVersion 2>$null } catch { $py = $null }
        if ($py -and (Test-Path $py)) {
            $ver = & $py --version 2>&1
            Write-Host "        OK $py ($ver)"
        } else {
            Write-Host "        ! no Python $PythonMinVersion+ found (uv will provision on install)"
            $warn++
        }
    } else {
        Write-Host '        ! uv not on PATH yet (Python check deferred to install time)'
        $warn++
    }

    # 4. uv
    Write-Host '[4/10] uv'
    if ($uv) { Write-Host "        OK $(& uv --version)" }
    else     { Write-Host "        ! uv not on PATH (will be installed by $SponsorScript)"; $warn++ }

    # 5. Network reachability
    Write-Host '[5/10] Network reachability'
    try {
        $null = Invoke-WebRequest -Uri $RepoUrl -Method Head -UseBasicParsing -TimeoutSec 5
        Write-Host "        OK repo reachable: $RepoUrl"
    } catch {
        Write-Host "        X cannot reach $RepoUrl"
        Write-Host '          check: proxy settings, VPN, DNS, firewall'
        $fail++
    }

    # 6. Write access to install dir
    Write-Host '[6/10] Write access to install dir'
    if (-not (Test-Path $ClawCodexParentDir)) {
        try { New-Item -ItemType Directory -Path $ClawCodexParentDir -Force | Out-Null } catch { }
    }
    if (Test-Path $ClawCodexParentDir) {
        $probe = Join-Path $ClawCodexParentDir '.doctor-write-test'
        try {
            'probe' | Set-Content -LiteralPath $probe -Force
            Remove-Item -LiteralPath $probe -Force
            Write-Host "        OK writable: $ClawCodexParentDir"
        } catch {
            Write-Host "        X cannot write: $ClawCodexParentDir"
            $fail++
        }
    } else {
        Write-Host "        X cannot create: $ClawCodexParentDir"
        $fail++
    }

    # 7. Write access to config dir
    Write-Host '[7/10] Write access to config dir'
    if (-not (Test-Path $ConfigDir)) {
        try { New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null } catch { }
    }
    if (Test-Path $ConfigDir) {
        $probe = Join-Path $ConfigDir '.doctor-write-test'
        try {
            'probe' | Set-Content -LiteralPath $probe -Force
            Remove-Item -LiteralPath $probe -Force
            Write-Host "        OK writable: $ConfigDir"
        } catch {
            Write-Host "        X cannot write: $ConfigDir"
            $fail++
        }
    } else {
        Write-Host "        X cannot create: $ConfigDir"
        $fail++
    }

    # 8. Disk space
    Write-Host '[8/10] Disk space'
    try {
        $drive = (Get-Item $ClawCodexParentDir).PSDrive
        if ($drive -and $drive.Free -gt 524288000) {
            Write-Host "        OK $([math]::Round($drive.Free / 1MB, 0))MB available on $($drive.Name)"
        } else {
            Write-Host "        X < 512MB available at $ClawCodexParentDir (need ~500MB for venv + deps)"
            $fail++
        }
    } catch {
        Write-Host "        ! cannot determine free space on $ClawCodexParentDir"
        $warn++
    }

    # 9. PATH
    Write-Host '[9/10] User PATH'
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($userPath -and ($userPath -split ';' | Where-Object { $_.TrimEnd('\') -ieq ($LocalBin.TrimEnd('\')) })) {
        Write-Host "        OK $LocalBin is in User PATH"
    } else {
        Write-Host "        ! $LocalBin NOT in User PATH (will be added on install)"
        $warn++
    }

    # 10. Existing install
    Write-Host '[10/10] Existing install'
    $gitDir = Join-Path $ClawCodexHome '.git'
    if (Test-Path $gitDir) {
        Write-Host "        OK installed at $ClawCodexHome"
        Write-Host "          (run '$SponsorScript verify' to check health, '$SponsorScript update' to refresh)"
    } else {
        Write-Host '        ! not installed yet'
        $warn++
    }

    Write-Host ''
    Write-Host '=== summary ==='
    Write-Host "  critical : $fail"
    Write-Host "  warnings : $warn"
    Write-Host ''
    if ($fail -gt 0) { Write-Host "  Result: NOT READY ($fail critical issue(s))"; exit 1 }
    Write-Host '  Result: READY to install (or already installed)'
    exit 0
}

# Health check an existing install.  No side effects.
function script:Invoke-Verify {
    $fail = 0; $warn = 0
    Write-Host '=== clawcodex install verification ==='
    Write-Host ''

    # 1. Repo
    Write-Host '[1/6] Repo'
    $gitDir = Join-Path $ClawCodexHome '.git'
    if (Test-Path $gitDir) { Write-Host "      OK present at $ClawCodexHome" }
    else {
        Write-Host "      X NOT FOUND at $ClawCodexHome"
        Write-Host "        run: $SponsorScript install"
        $fail++
    }

    # 2. Venv
    Write-Host '[2/6] Venv'
    $venvDir = Join-Path $ClawCodexHome '.venv'
    $venvPy  = Join-Path $venvDir 'Scripts\python.exe'
    if (Test-Path $venvDir) {
        Write-Host "      OK present at $venvDir"
        if (Test-Path $venvPy) {
            $pyVer = (& $venvPy --version 2>&1) -join ' '
            Write-Host "      OK python works: $pyVer"
        } else {
            Write-Host '      X python missing in venv'
            $fail++
        }
    } else {
        Write-Host "      X venv MISSING at $venvDir"
        Write-Host "        run: $SponsorScript update   (or: $SponsorScript install)"
        $fail++
    }

    # 3. Entry point
    Write-Host '[3/6] Entry point'
    $entry = $null
    if (Test-Path $venvDir) { $entry = Find-Venv-Entry -VenvDir $venvDir -Name $EntryPoint }
    if ($entry) { Write-Host "      OK $EntryPoint at $entry" }
    else {
        Write-Host "      X $EntryPoint not found in venv"
        Write-Host "        run: $SponsorScript update"
        $fail++
    }

    # 4. Wrappers
    Write-Host '[4/6] Command wrappers'
    foreach ($cmd in @('clawcodex-dev', 'clawcodex')) {
        $wrapper = Join-Path $LocalBin "$cmd.cmd"
        if (Test-Path $wrapper) { Write-Host "      OK $wrapper" }
        else {
            Write-Host "      X $wrapper MISSING"
            Write-Host "        run: $SponsorScript install"
            $fail++
        }
    }

    # 5. PATH
    Write-Host '[5/6] PATH'
    $resolved = Get-Command clawcodex-dev -ErrorAction SilentlyContinue
    if ($resolved) { Write-Host "      OK clawcodex-dev resolves to: $($resolved.Path)" }
    else {
        Write-Host '      ! clawcodex-dev NOT on PATH (wrappers exist but not exported)'
        Write-Host "        open a new PowerShell, or: `$env:Path = '$LocalBin;' + `$env:Path"
        $warn++
    }

    # 6. Smoke test
    Write-Host '[6/6] Smoke test (clawcodex-dev --version)'
    if ($resolved) {
        $smokeOut = & clawcodex-dev --version 2>&1
        if ($LASTEXITCODE -eq 0) { Write-Host '      OK clawcodex-dev --version works' }
        else { Write-Host "      X clawcodex-dev --version FAILED (exit $LASTEXITCODE)"; $fail++ }
    } else {
        Write-Host '      ! skipped (not on PATH)'
        $warn++
    }

    Write-Host ''
    if ($fail -gt 0) {
        Write-Host "=== Result: UNHEALTHY ($fail issue(s), $warn warning(s)) ==="
        Write-Host ''
        Write-Host 'Try:'
        Write-Host "  $SponsorScript update                                  # re-pull and re-install deps"
        Write-Host "  $SponsorScript uninstall ; $SponsorScript             # full clean reinstall"
        exit 1
    }
    Write-Host "=== Result: HEALTHY ($warn warning(s)) ==="
    exit 0
}

# Update: pull latest and reinstall deps.
function script:Update-Install {
    Log-Info "Updating clawcodex at $ClawCodexHome (ref: $RepoRef) ..."
    if (-not (Test-Path (Join-Path $ClawCodexHome '.git'))) {
        Die-With-Help "No existing install at $ClawCodexHome." `
            "Run: $SponsorScript install   (fresh install)" `
            "Or:  $SponsorScript doctor    (diagnose environment)"
    }
    Clone-OrUpdate-Repo
    Ensure-Local-EnvFile
    Install-Deps
    Install-Git-Hooks
    Register-Commands
    Update-User-Path
    Log-Ok 'Update complete.'
    Log-Info "Run '$SponsorScript verify' to confirm health."
}

# Uninstall: only removes what this script created.
function script:Uninstall-Install {
    Log-Info 'Uninstalling clawcodex ...'
    Log-Info "  Install dir : $ClawCodexHome"
    Log-Info "  Config dir  : $ConfigDir"
    Log-Info "  Local bin   : $LocalBin"

    foreach ($name in @('clawcodex-dev', 'clawcodex')) {
        $wrapper = Join-Path $LocalBin "$name.cmd"
        if (Test-Path $wrapper) {
            # Safety check: only remove wrappers that point inside THIS install
            # dir.  This protects multi-install users from cascading deletes
            # when they uninstall one install while another (sharing $LocalBin)
            # is still active.
            $content = Get-Content -LiteralPath $wrapper -Raw -ErrorAction SilentlyContinue
            if ($content -and $content -like "*$ClawCodexHome*") {
                if ($DryRun) {
                    ScriptP1
                    Write-Host "[DRY-RUN] would remove: $wrapper"
                } else {
                    Remove-Item -LiteralPath $wrapper -Force
                    Log-Ok "Removed $wrapper"
                }
            } else {
                Log-Warn "Skipped $wrapper — does not point inside $ClawCodexHome (other install?)"
            }
        }
    }

    if (Test-Path $ClawCodexHome) {
        if ($DryRun) {
            ScriptP1
            Write-Host "[DRY-RUN] would remove: $ClawCodexHome"
        } else {
            Remove-Item -LiteralPath $ClawCodexHome -Recurse -Force
            Log-Ok "Removed $ClawCodexHome"
        }
    }

    # Only auto-remove the install's parent dir if it's empty AND it's NOT
    # also the config dir.  Otherwise -ConfigDir == -InstallDir-parent would
    # nuke the runtime state we explicitly keep.
    if ((Test-Path $ClawCodexParentDir) -and
        ($ClawCodexParentDir -ne $ConfigDir) -and
        -not (Get-ChildItem -LiteralPath $ClawCodexParentDir -Force -ErrorAction SilentlyContinue)) {
        if ($DryRun) {
            ScriptP1
            Write-Host "[DRY-RUN] would rmdir empty: $ClawCodexParentDir"
        } else {
            Remove-Item -LiteralPath $ClawCodexParentDir -Force
            Log-Ok "Removed empty $ClawCodexParentDir"
        }
    }

    # Config dir is preserved by design — it contains the user's sessions,
    # auth tokens, history, etc.  Removing it requires an explicit rm.
    if (Test-Path $ConfigDir) {
        Log-Warn "Preserved config dir: $ConfigDir  (delete manually with Remove-Item -Recurse -Force if desired)"
    }

    Log-Warn "Note: this script does not edit User PATH automatically.  To remove the"
    Log-Warn "PATH entry, run:  [Environment]::SetEnvironmentVariable('Path', <without $LocalBin>, 'User')"
    Log-Ok 'Uninstall complete.'
}

# ============================================================================
#  Help
# ============================================================================
function script:Show-Help {
    @(
        "clawcodex installer v$InstallerVersion  (installs clawcodex v$ClawCodexVersion)"
        ""
        "USAGE"
        "    $SponsorScript [SUBCOMMAND] [OPTIONS]"
        "    powershell -ExecutionPolicy Bypass -File $SponsorScript [SUBCOMMAND] [OPTIONS]"
        ""
        "SUBCOMMANDS"
        "    (none) / install    Install clawcodex (default action)."
        "    status              Show current install state — no side effects."
        "    doctor              Diagnose the environment (git, python, network, disk,"
        "                        permissions) — no side effects."
        "    verify              Health-check an existing install (venv, entry point,"
        "                        PATH, smoke test) — no side effects."
        "    update              Pull latest from the configured ref and reinstall deps."
        "    uninstall           Remove everything this installer created."
        "    help                Show this help."
        ""
        "OPTIONS"
        "    -Ref <ref>             Override the git ref to install (commit SHA, tag, or"
        "                           branch).  Default: $RepoRef (derived from ClawCodexVersion)."
        "                           Useful for pinning to an exact commit during bisection"
        "                           or for testing unreleased code."
        "    -InstallDir <path>     Override the project clone + venv location."
        "                           Default: $DefaultInstallDir"
        "    -ConfigDir <path>      Override the runtime config directory (sessions, auth,"
        "                           history).  Default: $DefaultConfigDir"
        "                           Exposed to clawcodex-dev via the CLAWCODEX_CONFIG_DIR"
        "                           env var injected by the wrapper scripts."
        "    -NoVenv                Skip virtual-environment creation.  Dependencies are"
        "                           installed into the active system Python via"
        "                           'uv pip install --system'.  Use this in containers or"
        "                           any environment where the venv would be redundant."
        "    -NoSetup               Skip the post-install configuration-wizard hint."
        "                           Use for non-interactive / CI / Docker installs."
        "                           You can configure later by running clawcodex-dev."
        "    -DryRun                Preview every change without applying it.  Prints each"
        "                           command that would run as '[DRY-RUN] would run: ...'."
        "                           Combines well with status / doctor."
        "    -Yes / -Force          Assume 'yes' for any interactive prompts."
        "    -LogFile <path>        Tee all output (stdout + stderr) to <path>.  The EXIT"
        "                           summary prints the log file path on success and on"
        "                           failure."
        "    -Uninstall             Alias for the 'uninstall' subcommand."
        "    -Help                  Show this help (English)."
        "    -HelpZh                Show help in Chinese (中文帮助)."
        "    -Version               Print installer version."
        ""
        "DEFAULTS"
        "    Repo         : $RepoUrl"
        "    Git ref      : $RepoRef  (override with -Ref)"
        "    Install path : $DefaultInstallDir  (override with -InstallDir)"
        "    Config path  : $DefaultConfigDir  (override with -ConfigDir)"
        "    Python       : >= $PythonMinVersion  (provisioned by uv if missing)"
        "    Tooling      : uv (Astral's package manager — installed user-local, no admin)"
        ""
        "EXAMPLES"
        "    # First-time install (most common):"
        "    $SponsorScript"
        ""
        "    # Check if install is healthy (agent / CI / post-deploy check):"
        "    $SponsorScript verify"
        ""
        "    # See what's installed and where:"
        "    $SponsorScript status"
        ""
        "    # Diagnose the environment before installing:"
        "    $SponsorScript doctor"
        ""
        "    # Install a specific tag (e.g. for bisection):"
        "    $SponsorScript -Ref v0.5.0"
        ""
        "    # Custom install + config directories (e.g. system-wide):"
        "    $SponsorScript -InstallDir C:\Apps\clawcodex -ConfigDir C:\ProgramData\clawcodex"
        ""
        "    # Non-interactive install for CI / Docker (no venv, no setup hint):"
        "    $SponsorScript -NoVenv -NoSetup -Force -LogFile C:\Temp\install.log"
        ""
        "    # Preview what an install would do without applying:"
        "    $SponsorScript -DryRun"
        ""
        "    # Re-run after a failed install to capture full output for bug reports:"
        "    $SponsorScript -LogFile C:\Temp\install.log"
        "    # ... and read C:\Temp\install.log"
        ""
        "    # Remove everything this script installed (preserves config dir):"
        "    $SponsorScript uninstall"
        ""
        "TROUBLESHOOTING"
        '    "Git is not installed"'
        "        Install Git: winget install Git.Git, or download from"
        "        https://git-scm.com/download/win, then reopen PowerShell."
        ""
        '    "uv installer failed to download" / network errors'
        "        Check your network, proxy, and VPN.  Retry:  $SponsorScript"
        "        Manual uv install:  iwr https://astral.sh/uv/install.ps1 -UseBasicParsing | iex"
        ""
        '    "git clone failed"'
        "        Verify network:  Test-NetConnection $RepoUrl -Port 443"
        "        If behind a firewall, configure a proxy or use a mirror."
        ""
        '    "uv venv failed" / "uv sync failed" / "uv pip install failed"'
        "        Re-run with -LogFile to capture full output:"
        "            $SponsorScript -LogFile C:\Temp\out.log"
        "        Diagnose:  $SponsorScript doctor"
        "        Clean reinstall:  $SponsorScript uninstall ; $SponsorScript"
        ""
        '    "clawcodex-dev: command not found" after install'
        "        Your shell hasn't picked up the new PATH yet.  Either:"
        '          - Open a new PowerShell window, or'
        "          - Run:  `$env:Path = '$LocalBin;' + `$env:Path"
        ""
        "    Permission errors when writing to $LocalBin or $DefaultInstallDir"
        "        Pick a writable location:"
        "            $SponsorScript -InstallDir C:\Users\<you>\apps\clawcodex"
        ""
        "    Stale install (changes don't take effect)"
        "        Pull latest + reinstall:  $SponsorScript update"
        "        Hard reset:               $SponsorScript uninstall ; $SponsorScript"
        ""
        "EXIT CODES"
        "    0    Success."
        "    1    Installation / verification / doctor found a problem."
        "    2    Invalid CLI argument (unknown flag, missing value)."
        "    3    Doctor / verify found critical issues."
        ""
        "VERSIONING"
        "    This install.ps1 is paired 1:1 with a clawcodex release.  ClawCodexVersion"
        "    and RepoRef are the version pin; the matching uv.lock pins every transitive"
        "    dependency.  To install a different clawcodex version, download the"
        "    install.ps1 that ships with that release — do NOT just edit these constants"
        "    in isolation, since the lock file is what actually pins the dependency"
        "    versions.  The -Ref flag is a deliberate escape hatch for testing specific"
        "    commits and is NOT a substitute for shipping a properly tagged installer."
        ""
        "NOTES"
        "    - Re-running this script is safe: existing repos are fast-forwarded,"
        "      existing venvs are reused, command wrappers are regenerated."
        "    - install/update creates a local .env template when missing and attempts"
        "      to install .git/hooks/pre-commit after deps are available.  Hook"
        "      installation is best-effort and never blocks CLI setup."
        "    - On Windows, run from PowerShell 5.1+ (built-in) or PowerShell 7+ (pwsh)."
        "      On WSL, prefer the bash install.sh — this script targets the Windows"
        "      side of things but works in WSL-hosted PowerShell too."
        "    - In non-TTY mode (piped / agent / CI), every emitted line is prefixed"
        "      with '[install.ps1]'.  A 'DONE: SUCCESS|FAILED' line is emitted on exit,"
        "      so you can grep the tail of any captured log."
    ) -join "`n" | Write-Host
}

function script:Show-HelpZh {
    @(
        "clawcodex 安装脚本 v$InstallerVersion  (安装 clawcodex v$ClawCodexVersion)"
        ""
        "用法"
        "    $SponsorScript [子命令] [选项]"
        "    powershell -ExecutionPolicy Bypass -File $SponsorScript [子命令] [选项]"
        ""
        "子命令"
        "    （无） / install    安装 clawcodex（默认动作）。"
        "    status              显示当前安装状态——无副作用。"
        "    doctor              诊断环境（git、python、网络、磁盘、权限）——无副作用。"
        "    verify              健康检查已有安装（venv、入口、PATH、烟雾测试）——无副作用。"
        "    update              拉取最新代码并重装依赖。"
        "    uninstall           卸载本脚本创建的所有内容。"
        "    help                显示英文版帮助。"
        ""
        "选项"
        "    -Ref <引用>            覆盖要安装的 git 引用（commit SHA、tag 或分支）。"
        "                           默认：$RepoRef（由 ClawCodexVersion 推导得出）。"
        "                           常用于 bisect 时精确锁定 commit，或测试未发布代码。"
        "    -InstallDir <路径>     覆盖项目克隆和 venv 所在的位置。"
        "                           默认：$DefaultInstallDir"
        "    -ConfigDir <路径>      覆盖运行时配置目录（会话、鉴权、历史记录）。"
        "                           默认：$DefaultConfigDir"
        "                           通过 wrapper 脚本注入的 CLAWCODEX_CONFIG_DIR"
        "                           环境变量暴露给 clawcodex-dev。"
        "    -NoVenv                跳过虚拟环境的创建。依赖直接安装到当前系统"
        "                           Python（使用 'uv pip install --system'）。适用"
        "                           于容器或任何 venv 多余的环境。"
        "    -NoSetup               跳过安装后的配置提示。适用于非交互 / CI /"
        "                           Docker 场景。之后可随时手动运行 clawcodex-dev"
        "                           进行配置。"
        "    -DryRun                预览所有改动但不实际执行。把每条会运行的命令打"
        "                           印为 '[DRY-RUN] would run: ...'。与 status /"
        "                           doctor 配合使用效果更佳。"
        "    -Yes / -Force          对所有交互式提示默认回答 yes。"
        "    -LogFile <路径>        把所有输出（stdout + stderr）同时写入 <路径>。"
        "                           退出摘要会在成功 / 失败时都打印日志路径。"
        "    -Uninstall             'uninstall' 子命令的简写。"
        "    -Help                  显示英文版帮助。"
        "    -HelpZh                显示本中文版帮助。"
        "    -Version               打印安装脚本版本。"
        ""
        "默认值"
        "    仓库地址   ：$RepoUrl"
        "    Git 引用  ：$RepoRef  （用 -Ref 覆盖）"
        "    安装路径  ：$DefaultInstallDir  （用 -InstallDir 覆盖）"
        "    配置路径  ：$DefaultConfigDir  （用 -ConfigDir 覆盖）"
        "    Python    ：>= $PythonMinVersion  （缺失时由 uv 自动提供）"
        "    工具链    ：uv（Astral 的包管理器——用户级安装，无需管理员权限）"
        ""
        "示例"
        "    # 首次安装（最常见）："
        "    $SponsorScript"
        ""
        "    # 检查安装是否健康（agent / CI / 部署后检查）："
        "    $SponsorScript verify"
        ""
        "    # 查看已安装的内容和位置："
        "    $SponsorScript status"
        ""
        "    # 安装前诊断环境："
        "    $SponsorScript doctor"
        ""
        "    # 安装特定 tag（例如 bisect 时）："
        "    $SponsorScript -Ref v0.5.0"
        ""
        "    # 自定义安装和配置目录："
        "    $SponsorScript -InstallDir C:\Apps\clawcodex -ConfigDir C:\ProgramData\clawcodex"
        ""
        "    # CI / Docker 环境的非交互式安装（无 venv、无配置提示）："
        "    $SponsorScript -NoVenv -NoSetup -Force -LogFile C:\Temp\install.log"
        ""
        "    # 预览安装流程而不实际执行："
        "    $SponsorScript -DryRun"
        ""
        "    # 安装失败后重新运行以捕获完整输出供排查："
        "    $SponsorScript -LogFile C:\Temp\install.log"
        "    # ... 然后查看 C:\Temp\install.log"
        ""
        "    # 移除本脚本安装的所有内容（保留配置目录）："
        "    $SponsorScript uninstall"
        ""
        "故障排查"
        '    "Git is not installed"'
        "        安装 Git：winget install Git.Git，或从"
        "        https://git-scm.com/download/win 下载，然后重开 PowerShell。"
        ""
        '    "uv installer failed to download" / 网络错误'
        "        检查网络、代理、VPN。重试：$SponsorScript"
        "        手动安装 uv：iwr https://astral.sh/uv/install.ps1 -UseBasicParsing | iex"
        ""
        '    "git clone failed"'
        "        验证网络：Test-NetConnection $RepoUrl -Port 443"
        "        如果在防火墙后，配置代理或使用镜像。"
        ""
        '    "uv venv failed" / "uv sync failed" / "uv pip install failed"'
        "        重新运行并用 -LogFile 捕获完整输出："
        "            $SponsorScript -LogFile C:\Temp\out.log"
        "        诊断：$SponsorScript doctor"
        "        干净重装：$SponsorScript uninstall ; $SponsorScript"
        ""
        '    安装后提示 "clawcodex-dev: command not found"'
        "        当前 shell 还没加载新的 PATH。请："
        '          - 新开一个 PowerShell 窗口，或'
        "          - 执行 `$env:Path = '$LocalBin;' + `$env:Path"
        ""
        "    写入 $LocalBin 或 $DefaultInstallDir 时权限错误"
        "        选择可写位置："
        "            $SponsorScript -InstallDir C:\Users\<你>\apps\clawcodex"
        ""
        "    安装版本陈旧（修改不生效）"
        "        拉取最新 + 重装：$SponsorScript update"
        "        硬重置：          $SponsorScript uninstall ; $SponsorScript"
        ""
        "退出码"
        "    0    成功。"
        "    1    安装 / 验证 / 诊断发现问题。"
        "    2    无效的 CLI 参数（未知选项、缺少值）。"
        "    3    doctor / verify 发现严重问题。"
        ""
        "版本控制"
        "    本 install.ps1 与 clawcodex 的某个发布版本一一对应。ClawCodexVersion"
        "    和 RepoRef 是版本钉子；对应的 uv.lock 把所有传递依赖一并锁定。要"
        "    安装不同版本的 clawcodex，请下载该发布版自带的 install.ps1——不要"
        "    单独修改这些常量，因为真正钉住依赖版本的是 lock 文件。-Ref 标志"
        "    是用于测试特定 commit 的有意保留的逃生口，**不能**替代正规打 tag"
        "    的安装脚本。"
        ""
        "注意事项"
        "    - 重复运行本脚本是安全的：已存在的仓库会 fast-forward，已存在的"
        "      venv 会复用，command wrapper 会重新生成。"
        "    - install/update 会在缺失时创建本地 .env 模板，并在依赖可用后尝试"
        "      安装 .git/hooks/pre-commit。hook 安装是 best-effort，不会阻断"
        "      CLI 安装。"
        "    - 在 Windows 上请从 PowerShell 5.1+（系统自带）或 PowerShell 7+"
        "      （pwsh）运行。在 WSL 上请优先使用 bash 版的 install.sh——本脚本"
        "      面向 Windows 侧，但在 WSL 托管的 PowerShell 中也能工作。"
        "    - 在非 TTY 模式（管道 / agent / CI）下，每一行输出都会加上"
        "      '[install.ps1]' 前缀。退出时会单独输出一行"
        "      'DONE: SUCCESS|FAILED'，所以你可以直接 grep 日志末尾判断结果。"
    ) -join "`n" | Write-Host
}


# ============================================================================
#  Install pipeline (default subcommand)
# ============================================================================
function script:Install-Main {
    Write-Host "${C_Bold}clawcodex installer v$InstallerVersion${C_Reset}"
    Write-Host "  ${C_Bold}OS:${C_Reset}          $OS"
    Write-Host "  ${C_Bold}Install dir:${C_Reset} $ClawCodexHome"
    Write-Host "  ${C_Bold}Config dir:${C_Reset}  $ConfigDir"
    Write-Host "  ${C_Bold}Git ref:${C_Reset}     $RepoRef"
    if ($UseVenv) { Write-Host "  ${C_Bold}Venv:${C_Reset}        create at $ClawCodexHome\.venv" }
    else          { Write-Host "  ${C_Bold}Venv:${C_Reset}        ${C_Yellow}skipped (-NoVenv, system Python)${C_Reset}" }
    if ($RunSetup) { Write-Host '  Setup wizard: announce only (non-blocking)' }
    else            { Write-Host "  ${C_Bold}Setup wizard:${C_Reset} ${C_Yellow}skipped (-NoSetup)${C_Reset}" }
    if ($DryRun)    { Write-Host "  ${C_Bold}Mode:${C_Reset}        ${C_Yellow}DRY-RUN (no changes will be made)${C_Reset}" }
    if ($LogFile)   { Write-Host "  ${C_Bold}Log file:${C_Reset}    $LogFile" }

    Log-Step '1/9  Checking prerequisites'
    Check-Git

    Log-Step '2/9  Installing uv (Astral, no admin)'
    # Re-expose uv on PATH in case it was installed earlier in this session.
    $env:Path = "$LocalBin;$((Join-Path $env:USERPROFILE '.cargo\bin'));$env:Path"
    Install-Uv

    Log-Step "3/9  Provisioning Python $PythonMinVersion+"
    Ensure-Python

    Log-Step '4/9  Cloning / updating repository'
    Clone-OrUpdate-Repo

    Log-Step '5/9  Initializing local release .env'
    Ensure-Local-EnvFile

    if ($UseVenv) { Log-Step '6/9  Creating virtual environment' } else { Log-Step '6/9  Preparing (no venv — using system Python)' }
    Create-Venv

    Log-Step '7/9  Installing dependencies (uv sync --extra all, lock-pinned)'
    Install-Deps

    Log-Step '8/9  Installing local Git hooks'
    Install-Git-Hooks

    Log-Step '9/9  Registering global commands & patching PATH'
    Register-Commands
    Update-User-Path

    Write-Host ''
    Log-Ok 'Installation complete!'
    Write-Host ''
    Write-Host "  ${C_Bold}Try it:${C_Reset}"
    Write-Host "    clawcodex-dev -Help    # primary command"
    Write-Host "    clawcodex    -Help     # alias of clawcodex-dev"
    Write-Host ''
    Write-Host "  ${C_Bold}Installed at:${C_Reset}  $ClawCodexHome"
    Write-Host "  ${C_Bold}Config at:${C_Reset}    $ConfigDir"
    Write-Host "  ${C_Bold}Commands at:${C_Reset}   $LocalBin\clawcodex-dev.cmd, $LocalBin\clawcodex.cmd"
    Write-Host ''

    Run-PostInstall-Setup

    Log-Warn 'Open a new PowerShell window, or run:  $env:Path = ' + "'$LocalBin;$env:Path'"
}

# ============================================================================
#  CLI argument parser — populates overrides, resolved below.
# ============================================================================
function script:Print-Usage-Hint {
    [Console]::Error.WriteLine("Try '$SponsorScript -Help' for usage.")
}

# ============================================================================
#  Init: resolve effective paths, set up log file, run.
# ============================================================================
function script:Initialize-Config {
    # Resolve overrides -> effective install/config paths.  Must run BEFORE
    # the install pipeline, otherwise -InstallDir / -Ref are silently ignored.
    $script:ClawCodexHome      = if ($InstallDir) { $InstallDir } else { $DefaultInstallDir }
    $script:ClawCodexParentDir = Split-Path -Path $ClawCodexHome -Parent
    $script:ConfigDir          = if ($ConfigDir)  { $ConfigDir }  else { $DefaultConfigDir }
    if ($Ref) { $script:RepoRef = $Ref }

    $script:OS = Detect-OS

    # Make uv visible early in case it's already installed but not on PATH.
    $env:Path = "$LocalBin;$((Join-Path $env:USERPROFILE '.cargo\bin'));$env:Path"

    # Set up log-file tee if requested.  Must happen AFTER $LogFile is bound
    # but BEFORE any other output.  After this redirection, [Console]::IsOutputRedirected
    # becomes true, so the [install.ps1] prefix is added on every line.
    if ($LogFile) {
        $logDir = Split-Path -Path $LogFile -Parent
        if ($logDir -and -not (Test-Path $logDir)) {
            try { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
            catch {
                Log-Warn "Cannot create log dir $logDir; -LogFile ignored"
                $script:LogFile = $null
            }
        }
        if ($LogFile) {
            # The actual teeing happens in Invoke-With-LogFile, which wraps
            # the main body.  Here we just validate the path is writable.
            try {
                # Touch the file so a permission error shows up here (under
                # the script's log dir creation), not deep inside the
                # pipeline where it would be harder to diagnose.
                $touchDir = Split-Path -Path $LogFile -Parent
                if ($touchDir -and -not (Test-Path $touchDir)) {
                    New-Item -ItemType Directory -Path $touchDir -Force | Out-Null
                }
                if (-not (Test-Path $LogFile)) {
                    Set-Content -LiteralPath $LogFile -Value '' -Encoding UTF8
                }
            } catch {
                Log-Warn "Cannot open log file $LogFile; -LogFile ignored"
                $script:LogFile = $null
            }
        }
    }
}

# Apply log-file redirection.  This is called by the main entry below; doing
# it as a function lets us wire it once and let try/finally handle the cleanup.
function script:Invoke-With-LogFile {
    param([scriptblock]$Body)
    if (-not $LogFile) {
        & $Body
        return
    }
    # Tee-Object writes each input object to BOTH the file (append) AND its
    # output stream — so console output is preserved while a full transcript
    # is captured on disk.  *>&1 merges error stream into output so the file
    # gets both.  The DONE: line goes to stderr (via Write-ExitSummary) so
    # agent log-greppers can find it even when the body flood the pipeline.
    try {
        & $Body *>&1 | Tee-Object -FilePath $LogFile -Append
    } catch {
        # If the body throws, re-throw so the outer try/catch can set $rc.
        throw
    }
}

# ============================================================================
#  Entry point
# ============================================================================
# Handle flag-only invocations that must short-circuit before main.
if ($Help)    { Show-Help;    exit 0 }
if ($HelpZh)  { Show-HelpZh;  exit 0 }
if ($Version) { Write-Host "install.ps1 v$InstallerVersion (installs clawcodex v$ClawCodexVersion)"; exit 0 }

# -Uninstall is an alias for the 'uninstall' subcommand.
if ($Uninstall) { $Subcommand = 'uninstall' }

# If no subcommand was given, default to 'install'.
if (-not $Subcommand) { $Subcommand = 'install' }

Initialize-Config

$rc = 0
try {
    Invoke-With-LogFile -Body {
        switch ($Subcommand) {
            'install'   { Install-Main }
            'status'    { Get-InstallStatus }
            'doctor'    { Invoke-Doctor }
            'verify'    { Invoke-Verify }
            'update'    { Update-Install }
            'uninstall' { Uninstall-Install }
            'help'      { Show-Help }
            default {
                Log-Err "Unknown subcommand: $Subcommand"
                Print-Usage-Hint
                $script:rc = 1
            }
        }
    }
} catch {
    Log-Err "Installer crash: $_"
    $rc = 1
} finally {
    Write-ExitSummary $rc
}

exit $rc
