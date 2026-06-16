#!/usr/bin/env bash
# ============================================================================
#  install.sh — One-click installer for clawcodex (agent-friendly edition)
# ----------------------------------------------------------------------------
#  - OS detection (Linux / macOS / WSL / Git Bash)
#  - Git prerequisite check
#  - uv installation (no sudo, via official astral.sh installer)
#  - Python 3.10+ provisioning (via uv)
#  - Repo clone/update to ~/.clawcodex/clawcodex
#  - Venv creation (uv-managed)
#  - Dependency install: pip install -e ".[all]"
#  - Global commands: ~/.local/bin/clawcodex  +  ~/.local/bin/clawcodex-dev
#  - Shell rc patch: .bashrc / .zshrc / .profile  (PATH += ~/.local/bin)
#
#  Subcommands (use exactly one, or omit for default 'install'):
#     ./install.sh                # install (default)
#     ./install.sh install        # explicit install
#     ./install.sh status         # show current install state
#     ./install.sh doctor         # diagnose the environment
#     ./install.sh verify         # health-check an existing install
#     ./install.sh update         # pull latest + reinstall deps
#     ./install.sh uninstall      # remove everything this script created
#     ./install.sh help           # show usage
#     ./install.sh --help         # English help
#     ./install.sh --help-zh      # 中文使用说明
#     ./install.sh --version      # print installer version
#
#  Agent-friendly features:
#     - Subcommands (status / doctor / verify) for inspection without side effects
#     - --dry-run             preview every change before applying
#     - --yes / -y            assume yes for any prompts
#     - --log-file <path>     tee all output to a log file
#     - [install.sh] prefix on every line when stdout is not a TTY
#     - "DONE: success|FAILED" summary line on exit (grep-friendly)
#     - Each die() includes a "Next steps" block with actionable fixes
# ----------------------------------------------------------------------------
set -euo pipefail
# ERR trap: if a command fails under set -e, print the line number and
# failing command before exit.  Makes headless / TTY / CI failures
# self-diagnosing without requiring "bash -x".
set -E
trap 'log_err "Installer crash at line $LINENO: $BASH_COMMAND"' ERR

# ============================================================================
#  Config (read-only defaults)
# ============================================================================
# Versioning scheme
# -----------------
#   INSTALLER_VERSION  — version of this install.sh script
#   CLAWCODEX_VERSION  — version of clawcodex that THIS install.sh installs
#   REPO_REF           — git ref (tag/branch) the install clones
#
# The install.sh script is released alongside the clawcodex tag it ships
# with, so INSTALLER_VERSION == CLAWCODEX_VERSION for the bundle. Small
# script changes (typo fixes, log tweaks, new flags) do NOT bump the
# installer version — the version moves only when a new clawcodex tag
# is cut. To install a different clawcodex version, fetch the install.sh
# from that version's tag; an old install.sh still installs the old
# clawcodex (with its old uv.lock), never the bleeding edge.
# If REPO_REF doesn't resolve on the remote, the install falls back to the
# default branch with a loud warning — useful during the pre-tag period of
# a release but should never ship in a tagged installer.
readonly INSTALLER_VERSION="0.5.0"
readonly CLAWCODEX_VERSION="0.5.0"
# REPO_REF is intentionally NOT readonly — it gets reassigned when the user
# passes --ref. Same for CLAWCODEX_HOME / CLAWCODEX_PARENT_DIR / CONFIG_DIR
# (derived from overridable defaults below).
REPO_REF="v${CLAWCODEX_VERSION}"
readonly REPO_URL="https://gitcode.com/chadwweng/clawcodex"
# --- Overridable paths (defaults; overridden by --install-dir / --config-dir) ---
# Install dir = where the project source is cloned and (by default) the .venv lives.
# Config dir  = where clawcodex-dev stores its runtime state (sessions, auth, history).
#               Exposed to the runtime via $CLAWCODEX_CONFIG_DIR; the wrapper scripts
#               below set that env var on every invocation.
readonly DEFAULT_INSTALL_DIR="$HOME/.clawcodex/clawcodex"
readonly DEFAULT_CONFIG_DIR="$HOME/.clawcodex"
readonly LOCAL_BIN="$HOME/.local/bin"
readonly PYTHON_MIN_VERSION="3.10"
readonly ENTRY_POINT="clawcodex-dev"   # the single registered entry in pyproject.toml
readonly RC_MARKER="# clawcodex installer — managed by install.sh"

# ============================================================================
#  UI helpers
# ============================================================================
if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
    C_RED=$'\033[0;31m'; C_GREEN=$'\033[0;32m'; C_YELLOW=$'\033[1;33m'
    C_BLUE=$'\033[0;34m'; C_BOLD=$'\033[1m'; C_RESET=$'\033[0m'
else
    C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_BOLD=''; C_RESET=''
fi

# Agent-friendly line prefix. Emitted only when stdout/stderr is not a TTY
# (i.e. when the script is being driven by another process, an agent, a CI
# runner, or a piped tee). Interactive users see clean output.
_script_p1() { [[ ! -t 1 ]] && printf '[install.sh] '; return 0; }
_script_p2() { [[ ! -t 2 ]] && printf '[install.sh] ' >&2; return 0; }

log_info() { _script_p1; echo -e "${C_BLUE}==>${C_RESET} ${C_BOLD}$1${C_RESET}"; }
log_ok()   { _script_p1; echo -e "  ${C_GREEN}✓${C_RESET} $1"; }
log_warn() { _script_p1; echo -e "  ${C_YELLOW}!${C_RESET} $1"; }
log_err()  { _script_p2; echo -e "${C_RED}✗${C_RESET} $1" >&2; }
log_step() { _script_p1; echo -e "\n${C_BOLD}${C_BLUE}>>>${C_RESET} ${C_BOLD}$1${C_RESET}"; }

die() { log_err "$1"; exit 1; }

# Like die(), but accepts 0+ "next steps" lines that are printed in a clear
# "what to do next" block. Designed for agent-driven installs where the
# failure handler needs to know what to retry.
#
# Usage: die_with_help "primary error message" \
#                      "try this first" \
#                      "or this second"
die_with_help() {
    local header="$1"; shift
    _script_p2
    echo -e "${C_RED}✗${C_RESET} $header" >&2
    if [[ $# -gt 0 ]]; then
        echo "" >&2
        echo "  Next steps to try:" >&2
        for step in "$@"; do
            echo "    → $step" >&2
        done
    fi
    echo "" >&2
    echo "  For diagnosis, run:    $0 doctor" >&2
    echo "  For full usage, run:    $0 --help" >&2
    exit 1
}

# Wrap a command: if DRY_RUN=1, just print what would happen. Otherwise run it.
# Returns the exit status of the wrapped command.
run_or_dry() {
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would run: $*"
        return 0
    fi
    "$@"
}

# Exit-time summary. Emitted by the EXIT trap after the script's main work
# is done (success or failure). Agents tail the log for this line to know
# whether the install succeeded.
_on_exit_summary() {
    local rc=$1
    local elapsed=$(( $(date +%s) - SCRIPT_START_TS ))
    if [[ $rc -eq 0 ]]; then
        _script_p1
        echo "DONE: success in ${elapsed}s"
        if [[ -n "${LOG_FILE:-}" ]]; then
            _script_p1
            echo "DONE: full log saved to: $LOG_FILE"
        fi
    else
        _script_p2
        echo "DONE: FAILED (exit $rc) after ${elapsed}s" >&2
        if [[ -n "${LOG_FILE:-}" ]]; then
            _script_p2
            echo "DONE: failure log saved to: $LOG_FILE" >&2
        else
            _script_p2
            echo "DONE: re-run with --log-file <path> to capture full output." >&2
        fi
    fi
}

# ============================================================================
#  OS detection
# ============================================================================
detect_os() {
    local ostype="${OSTYPE:-}"
    if [[ "$ostype" == "linux-gnu"* || "$ostype" == "linux-musl"* ]]; then
        # Distinguish WSL from native Linux
        if [[ -r /proc/version ]] && grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
            echo "wsl"
        else
            echo "linux"
        fi
    elif [[ "$ostype" == "darwin"* ]]; then
        echo "macos"
    elif [[ "$ostype" == "msys"* || "$ostype" == "cygwin"* || "$ostype" == "win32" ]]; then
        echo "windows-like"
    elif [[ -r /proc/version ]] && grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
        echo "wsl"
    else
        echo "unknown"
    fi
}

os_install_hint() {
    case "$1" in
        linux|wsl)
            cat <<'EOF'
    Install Git for your distro, e.g.:
        Debian/Ubuntu : sudo apt update && sudo apt install -y git
        Fedora/RHEL   : sudo dnf install -y git
        Arch          : sudo pacman -S --noconfirm git
        openSUSE      : sudo zypper install -y git
EOF
            ;;
        macos)
            cat <<'EOF'
    Install Git on macOS:
        xcode-select --install          # Apple Command Line Tools
        — or —
        brew install git
EOF
            ;;
        windows-like)
            cat <<'EOF'
    On Windows, install one of:
        Git for Windows : https://git-scm.com/download/win  (then run from Git Bash)
        WSL             : https://learn.microsoft.com/windows/wsl/install  (recommended)
EOF
            ;;
    esac
}

# One-liner variant for the doctor output.
os_install_hint_oneliner() {
    case "$1" in
        linux|wsl) echo "sudo apt install -y git   (or your distro's package manager)" ;;
        macos)     echo "xcode-select --install    (or: brew install git)" ;;
        windows-like) echo "install Git for Windows or WSL" ;;
        *)         echo "install git via your package manager" ;;
    esac
}

# ============================================================================
#  Prerequisite: Git
# ============================================================================
check_git() {
    if ! command -v git >/dev/null 2>&1; then
        log_err "Git is not installed."
        os_install_hint "$OS"
        exit 1
    fi
    local version
    version=$(git --version)
    log_ok "$version"
}

# ============================================================================
#  Install / locate uv (Astral's Python package manager, no sudo)
# ============================================================================
install_uv() {
    if command -v uv >/dev/null 2>&1; then
        log_ok "uv $(uv --version | awk '{print $2}') already installed"
        return
    fi

    log_info "Installing uv via official astral.sh installer (no sudo)..."
    # The official installer drops uv into ~/.local/bin and ~/.cargo/bin.
    # We capture its output so we can show progress in our own style.
    local tmp
    tmp=$(mktemp)
    if ! run_or_dry curl -LsSf --max-time 60 https://astral.sh/uv/install.sh -o "$tmp"; then
        rm -f "$tmp"
        die_with_help "Failed to download uv installer (network issue?)." \
                      "Check your network connection and proxy settings." \
                      "Retry:    $0" \
                      "Manual:   see https://docs.astral.sh/uv/"
    fi
    if ! run_or_dry env UV_INSTALL_DIR="$HOME/.local" sh "$tmp"; then
        rm -f "$tmp"
        die_with_help "uv installer exited with an error." \
                      "Inspect the output above for the exact failure." \
                      "Retry:    $0" \
                      "Manual:   curl -LsSf https://astral.sh/uv/install.sh | sh"
    fi
    rm -f "$tmp"

    # Make uv visible to this session, then verify.
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if [[ "${DRY_RUN:-0}" -eq 0 ]] && ! command -v uv >/dev/null 2>&1; then
        die_with_help "uv still not on PATH after install." \
                      "Check:    ls -la $HOME/.local/bin/uv" \
                      "Or:       export PATH=\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH" \
                      "Then:     $0"
    fi
    log_ok "uv $(uv --version | awk '{print $2}') installed"
}

# ============================================================================
#  Python 3.10+ provisioning (via uv)
# ============================================================================
ensure_python() {
    # Ask uv for any 3.10+ interpreter it can see (system or uv-managed).
    local py
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would check for Python $PYTHON_MIN_VERSION+ via uv"
        return 0
    fi
    if py=$(uv python find "$PYTHON_MIN_VERSION" 2>/dev/null) && [[ -n "$py" && -x "$py" ]]; then
        log_ok "Python $($py --version 2>&1 | awk '{print $1, $2}')"
        return
    fi

    log_info "Python $PYTHON_MIN_VERSION+ not found — provisioning via uv (no sudo)..."
    if ! run_or_dry uv python install "$PYTHON_MIN_VERSION"; then
        die_with_help "Failed to install Python $PYTHON_MIN_VERSION via uv." \
                      "Retry:    $0" \
                      "Manual:   uv python install $PYTHON_MIN_VERSION" \
                      "Or:       install Python $PYTHON_MIN_VERSION+ from https://python.org"
    fi
    py=$(uv python find "$PYTHON_MIN_VERSION" 2>/dev/null || true)
    if [[ -z "$py" || ! -x "$py" ]]; then
        die_with_help "Python $PYTHON_MIN_VERSION still not found after uv install." \
                      "Retry:    $0" \
                      "Diagnose: $0 doctor"
    fi
    log_ok "Python $($py --version 2>&1 | awk '{print $1, $2}')"
}

# ============================================================================
#  Clone or update the repo
# ============================================================================
clone_or_update_repo() {
    if [[ -d "$CLAWCODEX_HOME/.git" ]]; then
        log_info "Existing repo found at $CLAWCODEX_HOME — pulling latest changes..."
        if (cd "$CLAWCODEX_HOME" && git pull --ff-only) >/dev/null 2>&1; then
            log_ok "Updated via fast-forward"
        else
            log_warn "git pull --ff-only failed (likely local edits or non-FF history). Continuing with existing code."
        fi
        return
    fi

    if [[ -e "$CLAWCODEX_HOME" ]]; then
        # Exists but isn't a git repo — back it up so we don't clobber user work.
        local stamp
        stamp=$(date +%Y%m%d%H%M%S)
        log_warn "$CLAWCODEX_HOME exists but is not a git checkout. Backing up to ${CLAWCODEX_HOME}.bak.${stamp}"
        mv "$CLAWCODEX_HOME" "${CLAWCODEX_HOME}.bak.${stamp}"
    fi

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would create parent dir: $CLAWCODEX_PARENT_DIR"
        _script_p1
        echo "[DRY-RUN] would clone: $REPO_URL (ref: $REPO_REF) -> $CLAWCODEX_HOME"
        return 0
    fi

    mkdir -p "$CLAWCODEX_PARENT_DIR"
    log_info "Cloning $REPO_URL (ref: $REPO_REF) → $CLAWCODEX_HOME"
    # Try the pinned ref first. This is what makes the install version-stable:
    # the matching uv.lock at REPO_REF pins every transitive dep to a known-good
    # version, so old install.sh + old clawcodex + old deps always line up.
    if git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$CLAWCODEX_HOME" 2>/dev/null; then
        log_ok "Cloned ref $REPO_REF (clawcodex $CLAWCODEX_VERSION)"
        return
    fi

    # The ref doesn't exist on the remote yet (e.g. tag not pushed). Loud
    # warning, then fall back to the default branch so install can still
    # succeed in dev / pre-release scenarios.
    log_warn "Ref '$REPO_REF' not found on $REPO_URL — falling back to default branch."
    log_warn "  This install will pull the LATEST clawcodex, not v$CLAWCODEX_VERSION."
    log_warn "  Push a '$REPO_REF' git tag (or update REPO_REF) to enforce the version."
    if ! git clone --depth 1 "$REPO_URL" "$CLAWCODEX_HOME"; then
        die_with_help "git clone failed." \
                      "Check your network connection." \
                      "Verify:  curl -I $REPO_URL" \
                      "Retry:   $0" \
                      "Diagnose: $0 doctor"
    fi
    log_ok "Cloned default branch (clawcodex version NOT pinned)"
}

# ============================================================================
#  Create venv
# ============================================================================
create_venv() {
    if [[ "$USE_VENV" -eq 0 ]]; then
        log_info "--no-venv specified — skipping venv creation (deps will install to system Python)"
        return
    fi
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would run: uv venv --python $PYTHON_MIN_VERSION .venv   (in $CLAWCODEX_HOME)"
        return 0
    fi
    cd "$CLAWCODEX_HOME"
    if [[ -d ".venv" ]]; then
        log_ok "Existing venv at $CLAWCODEX_HOME/.venv"
        return
    fi
    log_info "Creating venv with Python $PYTHON_MIN_VERSION..."
    if ! run_or_dry uv venv --python "$PYTHON_MIN_VERSION" .venv; then
        die_with_help "uv venv failed." \
                      "Check:    uv --version" \
                      "Retry:    $0" \
                      "Diagnose: $0 doctor"
    fi
    log_ok "Venv created"
}

# ============================================================================
#  Install dependencies
# ============================================================================
install_deps() {
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        log_info "Installing project + [all] extra (lock-pinned when possible)..."
        _script_p1
        echo "[DRY-RUN] would run: uv sync --extra all   (in $CLAWCODEX_HOME)"
        return 0
    fi
    cd "$CLAWCODEX_HOME"
    log_info "Installing project + [all] extra (lock-pinned to uv.lock when possible)..."

    # Two-stage install: prefer `uv sync` (honors uv.lock → exact transitive
    # versions), fall back to `uv pip install` if the project doesn't declare
    # the [all] extra or the lock is out of sync.
    #
    # Why a fallback?
    #   - Production (matched install.sh + clawcodex release): uv sync uses
    #     the lock file from the matching git tag, giving every user the
    #     SAME resolved dep set. This is what prevents "old install.sh
    #     picks up latest deps and breaks" — the dep versions are baked
    #     into uv.lock at release time.
    #   - Mismatch (new install.sh running on old clawcodex, OR a clawcodex
    #     release that pre-dates the [all] extra): uv sync rejects
    #     `--extra all` because the extra doesn't exist in pyproject.toml.
    #     We fall back to uv pip install, which is lenient about missing
    #     extras. Deps are no longer lock-pinned in this case, but the
    #     install at least succeeds.

    # --- With venv: uv sync operates on the venv created by create_venv.
    # --- Without venv (--no-venv): install to the active Python via --system.
    local install_target_args=()
    if [[ "$USE_VENV" -eq 1 ]]; then
        [[ -d ".venv" ]] || die "Venv missing at $CLAWCODEX_HOME/.venv — run without --no-venv or re-clone."
        install_target_args=(--python .venv/bin/python)
    else
        install_target_args=(--system)
    fi

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would run: uv sync --extra all"
        return 0
    fi

    if uv sync --extra all 2>/tmp/uv-sync.log; then
        log_ok "Dependencies installed (lock-pinned to uv.lock at $REPO_REF)"
        rm -f /tmp/uv-sync.log
        return
    fi

    # uv sync failed — inspect why and decide.
    local sync_err
    sync_err=$(cat /tmp/uv-sync.log 2>/dev/null || true)
    rm -f /tmp/uv-sync.log

    if echo "$sync_err" | grep -qE 'Extra `all` is not defined'; then
        # The clawcodex version we're installing doesn't have the [all]
        # extra in its pyproject.toml. This is expected for any release
        # that pre-dates the [all] extra (added with install.sh v1.1).
        log_warn "This clawcodex version has no [all] extra — falling back to uv pip install."
        log_warn "  Dependency versions will be resolved fresh (NOT lock-pinned)."
        log_warn "  For strict version pinning, use an install.sh whose"
        log_warn "  CLAWCODEX_VERSION matches a release that includes [all]."
    else
        log_warn "uv sync failed; falling back to uv pip install."
        log_warn "  Sync error was: ${sync_err:-<no stderr captured>}"
    fi

    if ! uv pip install "${install_target_args[@]}" -e ".[all]" 2>/tmp/uv-pip.log; then
        local pip_err
        pip_err=$(cat /tmp/uv-pip.log 2>/dev/null || true)
        rm -f /tmp/uv-pip.log
        # uv's PEP 668 message has changed wording across versions; match
        # both the structured error code ("externally-managed-environment")
        # and the human message ("externally managed") defensively.
        if [[ "$USE_VENV" -eq 0 ]] && echo "$pip_err" | grep -qiE 'externally[ -]managed'; then
            log_warn "System Python is externally managed (PEP 668). Retrying with --break-system-packages."
            if ! uv pip install "${install_target_args[@]}" --break-system-packages -e ".[all]"; then
                die_with_help "uv pip install to system failed even with --break-system-packages." \
                              "Inspect the error above for missing system libraries." \
                              "Retry:    $0" \
                              "Or:       $0 uninstall && $0   (fresh install with venv)"
            fi
        else
            log_err "uv pip install failed: ${pip_err:-<no stderr captured>}"
            die_with_help "Both uv sync and uv pip install failed." \
                          "Re-run with --log-file <path> to capture full output." \
                          "Retry:    $0" \
                          "Diagnose: $0 doctor" \
                          "Clean:    $0 uninstall && $0"
        fi
    fi
    rm -f /tmp/uv-pip.log
    log_ok "Dependencies installed (fresh-resolve, NOT lock-pinned; target: $([[ $USE_VENV -eq 1 ]] && echo .venv || echo system))"
}

# ============================================================================
#  Locate the venv's entry-point binary
# ============================================================================
find_venv_entry() {
    local venv_dir="$1" name="$2"
    # Linux/macOS layout
    if [[ -x "$venv_dir/bin/$name" ]]; then
        echo "$venv_dir/bin/$name"; return 0
    fi
    # Windows layout (Git Bash / WSL interop)
    if [[ -x "$venv_dir/Scripts/$name.exe" ]]; then
        echo "$venv_dir/Scripts/$name.exe"; return 0
    fi
    if [[ -x "$venv_dir/Scripts/$name" ]]; then
        echo "$venv_dir/Scripts/$name"; return 0
    fi
    return 1
}

# ============================================================================
#  Register global commands
#  - We write tiny wrapper scripts in ~/.local/bin (more portable than symlinks
#    on Windows / Git Bash, and survives venv re-creation).
#  - `clawcodex` is registered as an alias for `clawcodex-dev` (the only
#    declared entry point in pyproject.toml).
# ============================================================================
register_commands() {
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would register: $LOCAL_BIN/clawcodex-dev, $LOCAL_BIN/clawcodex"
        return 0
    fi
    mkdir -p "$LOCAL_BIN"

    local entry
    if [[ "$USE_VENV" -eq 1 ]]; then
        # Venv mode: look for the entry inside the project's .venv
        if ! entry=$(find_venv_entry "$CLAWCODEX_HOME/.venv" "$ENTRY_POINT"); then
            die "Entry point '$ENTRY_POINT' not found inside $CLAWCODEX_HOME/.venv — dependency install may have failed."
        fi
    else
        # --no-venv mode: look for the entry on PATH (uv pip install --system
        # drops scripts in /usr/local/bin or ~/.local/bin). We check a few
        # common locations explicitly so we don't depend on the just-installed
        # PATH being effective in this very shell.
        entry=""
        for candidate in \
            "$HOME/.local/bin/$ENTRY_POINT" \
            "/usr/local/bin/$ENTRY_POINT" \
            "$(command -v "$ENTRY_POINT" 2>/dev/null || true)"; do
            if [[ -n "$candidate" && ( -x "$candidate" || -L "$candidate" ) ]]; then
                entry="$candidate"; break
            fi
        done
        [[ -n "$entry" ]] || die "Entry point '$ENTRY_POINT' not found on PATH after system install — check 'which $ENTRY_POINT'."
    fi

    write_wrapper() {
        local name="$1" target="$2"
        local wrapper="$LOCAL_BIN/$name"

        # Always (re)write so the wrapper reflects any new install dir.
        if [[ -L "$wrapper" || -e "$wrapper" ]]; then
            rm -f "$wrapper"
        fi

        cat > "$wrapper" <<EOF
#!/usr/bin/env bash
# Auto-generated by clawcodex install.sh — do not edit by hand.
# Regenerate by re-running install.sh.
# Point the runtime at the configured config dir; the wrapper itself is
# pinned to the install dir baked in at generation time, but the config
# dir can be re-pointed at runtime by the user via this env var.
export CLAWCODEX_CONFIG_DIR="\${CLAWCODEX_CONFIG_DIR:-${CONFIG_DIR}}"
exec "$target" "\$@"
EOF
        chmod +x "$wrapper"
        log_ok "$wrapper → $target  (CLAWCODEX_CONFIG_DIR=${CONFIG_DIR})"
    }

    write_wrapper "clawcodex-dev" "$entry"
    write_wrapper "clawcodex"    "$entry"
}

# ============================================================================
#  Patch shell rc files to include ~/.local/bin in PATH
# ============================================================================
update_shell_rc() {
    local path_line='export PATH="$HOME/.local/bin:$PATH"'
    local rc_files=()

    [[ -f "$HOME/.bashrc" ]] && rc_files+=("$HOME/.bashrc")
    [[ -f "$HOME/.zshrc"  ]] && rc_files+=("$HOME/.zshrc")
    [[ -f "$HOME/.profile" ]] && rc_files+=("$HOME/.profile")

    if [[ ${#rc_files[@]} -eq 0 ]]; then
        log_warn "No shell rc file detected — please add '$path_line' to your shell's startup file."
        return
    fi

    for rc in "${rc_files[@]}"; do
        if grep -qF "$HOME/.local/bin" "$rc" 2>/dev/null; then
            log_ok "PATH already contains ~/.local/bin in $rc"
            continue
        fi
        if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
            _script_p1
            echo "[DRY-RUN] would append PATH entry to: $rc"
            continue
        fi
        {
            echo ""
            echo "$RC_MARKER"
            echo "$path_line"
        } >> "$rc"
        log_ok "Patched $rc (added ~/.local/bin to PATH)"
    done
}

# ============================================================================
#  Post-install setup wizard (the interactive first-run configuration)
# ============================================================================
run_post_install_setup() {
    if [[ "$RUN_SETUP" -eq 0 ]]; then
        log_warn "Setup wizard skipped (--no-setup). Run 'clawcodex-dev' manually to configure."
        return
    fi

    log_info "Post-install setup wizard is available — launching clawcodex-dev setup…"
    # We intentionally do NOT exec a blocking interactive REPL here. The
    # install script must remain non-interactive so it can run unattended
    # in CI / Docker / by orchestrators. The wizard itself (if present) is
    # a subcommand the user runs themselves; we just announce it.
    if command -v clawcodex-dev >/dev/null 2>&1; then
        log_ok "Run one of:"
        echo -e "    ${C_BOLD}clawcodex-dev${C_RESET}          # start the interactive REPL (triggers first-run setup if config is empty)"
        echo -e "    ${C_BOLD}clawcodex-dev --help${C_RESET}  # see all options"
    else
        log_warn "clawcodex-dev not on PATH yet — run 'source ~/.bashrc' (or ~/.zshrc) first."
    fi
}

# ============================================================================
#  Inspection subcommands (no side effects — safe for agents to call)
# ============================================================================

# Show current install state. No side effects.
cmd_status() {
    echo "=== clawcodex install status ==="
    echo "  Installer   : v${INSTALLER_VERSION}  (would install clawcodex v${CLAWCODEX_VERSION})"
    echo "  Repo URL    : $REPO_URL"
    echo "  Git ref     : $REPO_REF"
    echo "  Install dir : $CLAWCODEX_HOME"
    echo "  Config dir  : $CONFIG_DIR"
    echo "  Local bin   : $LOCAL_BIN"
    echo ""
    if [[ -d "$CLAWCODEX_HOME/.git" ]]; then
        local installed_sha installed_branch
        installed_sha=$(cd "$CLAWCODEX_HOME" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
        installed_branch=$(cd "$CLAWCODEX_HOME" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
        echo "  Git state   :"
        echo "    branch    : $installed_branch"
        echo "    commit    : $installed_sha"
        if [[ -d "$CLAWCODEX_HOME/.venv" ]]; then
            local py_ver
            py_ver=$("$CLAWCODEX_HOME/.venv/bin/python" --version 2>&1 | head -1 || echo "missing")
            echo "  Venv        : present (Python: $py_ver)"
        else
            echo "  Venv        : MISSING (run '$0 update' to recreate)"
        fi
    else
        echo "  Git state   : NOT INSTALLED (run '$0 install')"
    fi
    echo ""
    echo "  Commands:"
    for cmd in clawcodex-dev clawcodex; do
        if [[ -x "$LOCAL_BIN/$cmd" ]]; then
            echo "    $LOCAL_BIN/$cmd : present"
        else
            echo "    $LOCAL_BIN/$cmd : MISSING"
        fi
    done
    echo ""
    if command -v clawcodex-dev >/dev/null 2>&1; then
        echo "  clawcodex-dev resolves to: $(command -v clawcodex-dev)"
    else
        echo "  clawcodex-dev NOT on PATH (run: source ~/.bashrc)"
    fi
    echo ""
    echo "=== end of status ==="
}

# Diagnose the environment. No side effects (only reads).
# Exit 0 if all critical checks pass, 1 if any fail.
cmd_doctor() {
    local ok=0 fail=0 warn=0
    echo "=== clawcodex environment doctor ==="
    echo ""

    # 1. OS
    echo "[1/10] OS detection"
    if [[ "$OS" == "unknown" ]]; then
        echo "        ✗ unknown OS"
        fail=$((fail+1))
    else
        echo "        ✓ $OS"
    fi

    # 2. Git
    echo "[2/10] Git"
    if command -v git >/dev/null 2>&1; then
        echo "        ✓ $(git --version)"
    else
        echo "        ✗ git not found"
        echo "          install: $(os_install_hint_oneliner "$OS")"
        fail=$((fail+1))
    fi

    # 3. Python
    echo "[3/10] Python >= $PYTHON_MIN_VERSION"
    if command -v uv >/dev/null 2>&1; then
        local py
        if py=$(uv python find "$PYTHON_MIN_VERSION" 2>/dev/null) && [[ -n "$py" ]]; then
            echo "        ✓ $py ($($py --version 2>&1))"
        else
            echo "        ! no Python $PYTHON_MIN_VERSION+ found (uv will provision on install)"
            warn=$((warn+1))
        fi
    else
        echo "        ! uv not on PATH yet (Python check deferred to install time)"
        warn=$((warn+1))
    fi

    # 4. uv
    echo "[4/10] uv"
    if command -v uv >/dev/null 2>&1; then
        echo "        ✓ $(uv --version)"
    else
        echo "        ! uv not on PATH (will be installed by $0)"
        warn=$((warn+1))
    fi

    # 5. Network
    echo "[5/10] Network reachability"
    if curl -sSf --max-time 5 -o /dev/null "$REPO_URL" 2>/dev/null; then
        echo "        ✓ repo reachable: $REPO_URL"
    else
        echo "        ✗ cannot reach $REPO_URL"
        echo "          check: proxy settings, VPN, DNS, firewall"
        fail=$((fail+1))
    fi

    # 6. Write access to install dir
    echo "[6/10] Write access to install dir"
    local parent
    parent=$(dirname -- "$CLAWCODEX_HOME")
    if mkdir -p "$parent" 2>/dev/null && [[ -w "$parent" ]]; then
        echo "        ✓ writable: $parent"
    else
        echo "        ✗ cannot write: $parent"
        echo "          fix: sudo chown -R \$USER $parent   (or pick a different --install-dir)"
        fail=$((fail+1))
    fi

    # 7. Write access to config dir
    echo "[7/10] Write access to config dir"
    if mkdir -p "$CONFIG_DIR" 2>/dev/null && [[ -w "$CONFIG_DIR" ]]; then
        echo "        ✓ writable: $CONFIG_DIR"
    else
        echo "        ✗ cannot write: $CONFIG_DIR"
        fail=$((fail+1))
    fi

    # 8. Disk space
    echo "[8/10] Disk space"
    local avail_kb
    avail_kb=$(df -Pk "$CLAWCODEX_PARENT_DIR" 2>/dev/null | awk 'NR==2 {print $4}')
    if [[ -n "$avail_kb" ]] && [[ $avail_kb -gt 524288 ]]; then
        echo "        ✓ $(( avail_kb / 1024 ))MB available"
    else
        echo "        ✗ < 512MB available at $CLAWCODEX_PARENT_DIR (need ~500MB for venv + deps)"
        fail=$((fail+1))
    fi

    # 9. PATH
    echo "[9/10] ~/.local/bin in PATH"
    if [[ ":$PATH:" == *":$HOME/.local/bin:"* ]]; then
        echo "        ✓ $HOME/.local/bin is in current PATH"
    else
        echo "        ! $HOME/.local/bin NOT in current PATH (will be patched on install)"
        warn=$((warn+1))
    fi

    # 10. Existing install
    echo "[10/10] Existing install"
    if [[ -d "$CLAWCODEX_HOME/.git" ]]; then
        echo "        ✓ installed at $CLAWCODEX_HOME"
        echo "          (run '$0 verify' to check health, '$0 update' to refresh)"
    else
        echo "        ! not installed yet"
        warn=$((warn+1))
    fi

    echo ""
    echo "=== summary ==="
    echo "  critical : $fail"
    echo "  warnings : $warn"
    echo ""
    if [[ $fail -gt 0 ]]; then
        echo "  Result: NOT READY ($fail critical issue(s))"
        exit 1
    else
        echo "  Result: READY to install (or already installed)"
        exit 0
    fi
}

# Health check an existing install. No side effects.
cmd_verify() {
    local fail=0 warn=0
    echo "=== clawcodex install verification ==="
    echo ""

    # 1. Repo
    echo "[1/6] Repo"
    if [[ -d "$CLAWCODEX_HOME/.git" ]]; then
        echo "      ✓ present at $CLAWCODEX_HOME"
    else
        echo "      ✗ NOT FOUND at $CLAWCODEX_HOME"
        echo "        run: $0 install"
        fail=$((fail+1))
    fi

    # 2. Venv
    echo "[2/6] Venv"
    if [[ -d "$CLAWCODEX_HOME/.venv" ]]; then
        echo "      ✓ present at $CLAWCODEX_HOME/.venv"
        if [[ -x "$CLAWCODEX_HOME/.venv/bin/python" ]]; then
            echo "      ✓ python works: $($CLAWCODEX_HOME/.venv/bin/python --version 2>&1)"
        else
            echo "      ✗ python missing in venv"
            fail=$((fail+1))
        fi
    else
        echo "      ✗ venv MISSING at $CLAWCODEX_HOME/.venv"
        echo "        run: $0 update   (or: $0 install)"
        fail=$((fail+1))
    fi

    # 3. Entry point
    echo "[3/6] Entry point"
    local entry=""
    if [[ -d "$CLAWCODEX_HOME/.venv" ]]; then
        entry=$(find_venv_entry "$CLAWCODEX_HOME/.venv" "$ENTRY_POINT" 2>/dev/null || true)
    fi
    if [[ -n "$entry" && -x "$entry" ]]; then
        echo "      ✓ $ENTRY_POINT at $entry"
    else
        echo "      ✗ $ENTRY_POINT not found in venv"
        echo "        run: $0 update"
        fail=$((fail+1))
    fi

    # 4. Wrappers
    echo "[4/6] Command wrappers"
    for cmd in clawcodex-dev clawcodex; do
        if [[ -x "$LOCAL_BIN/$cmd" ]]; then
            echo "      ✓ $LOCAL_BIN/$cmd"
        else
            echo "      ✗ $LOCAL_BIN/$cmd MISSING"
            echo "        run: $0 install"
            fail=$((fail+1))
        fi
    done

    # 5. PATH
    echo "[5/6] PATH"
    if command -v clawcodex-dev >/dev/null 2>&1; then
        echo "      ✓ clawcodex-dev resolves to: $(command -v clawcodex-dev)"
    else
        echo "      ! clawcodex-dev NOT on PATH (wrappers exist but not exported)"
        echo "        run: source ~/.bashrc   (or ~/.zshrc)"
        warn=$((warn+1))
    fi

    # 6. Smoke test
    echo "[6/6] Smoke test (clawcodex-dev --version)"
    if command -v clawcodex-dev >/dev/null 2>&1; then
        if clawcodex-dev --version >/dev/null 2>&1; then
            echo "      ✓ clawcodex-dev --version works"
        else
            echo "      ✗ clawcodex-dev --version FAILED (exit $?)"
            fail=$((fail+1))
        fi
    else
        echo "      ! skipped (not on PATH)"
        warn=$((warn+1))
    fi

    echo ""
    if [[ $fail -gt 0 ]]; then
        echo "=== Result: UNHEALTHY ($fail issue(s), $warn warning(s)) ==="
        echo ""
        echo "Try:"
        echo "  $0 update                                  # re-pull and re-install deps"
        echo "  $0 uninstall && $0                         # full clean reinstall"
        exit 1
    else
        echo "=== Result: HEALTHY ($warn warning(s)) ==="
        exit 0
    fi
}

# Update: pull latest and reinstall deps. Side effects: yes.
cmd_update() {
    log_info "Updating clawcodex at $CLAWCODEX_HOME (ref: $REPO_REF)..."
    if [[ ! -d "$CLAWCODEX_HOME/.git" ]]; then
        die_with_help "No existing install at $CLAWCODEX_HOME." \
                      "Run: $0 install   (fresh install)" \
                      "Or:  $0 doctor    (diagnose environment)"
    fi
    clone_or_update_repo
    install_deps
    register_commands
    log_ok "Update complete."
    log_info "Run '$0 verify' to confirm health."
}

# ============================================================================
#  Uninstall — only removes what this script created
# ============================================================================
uninstall() {
    log_info "Uninstalling clawcodex..."
    log_info "  Install dir : $CLAWCODEX_HOME"
    log_info "  Config dir  : $CONFIG_DIR"
    log_info "  Local bin   : $LOCAL_BIN"

    for f in clawcodex-dev clawcodex; do
        local wrapper="$LOCAL_BIN/$f"
        if [[ -e "$wrapper" || -L "$wrapper" ]]; then
            # Safety check: only remove wrappers that point inside THIS
            # install dir. This protects multi-install users from
            # cascading deletes when they uninstall one install while
            # another (sharing $LOCAL_BIN) is still active. It also
            # prevents `uninstall --install-dir /tmp/test` from wiping
            # the production wrappers in $HOME/.local/bin.
            if grep -qF "$CLAWCODEX_HOME" "$wrapper" 2>/dev/null; then
                rm -f "$wrapper"
                log_ok "Removed $wrapper"
            else
                log_warn "Skipped $wrapper — does not point inside $CLAWCODEX_HOME (other install?)"
            fi
        fi
    done

    if [[ -d "$CLAWCODEX_HOME" ]]; then
        rm -rf "$CLAWCODEX_HOME"
        log_ok "Removed $CLAWCODEX_HOME"
    fi
    # Only auto-remove the install's parent dir if it's empty AND it's NOT
    # also the config dir. Otherwise --config-dir == --install-dir-parent
    # would nuke the runtime state we explicitly keep.
    if [[ -d "$CLAWCODEX_PARENT_DIR" ]] \
        && [[ "$CLAWCODEX_PARENT_DIR" != "$CONFIG_DIR" ]] \
        && [[ -z "$(ls -A "$CLAWCODEX_PARENT_DIR" 2>/dev/null)" ]]; then
        rmdir "$CLAWCODEX_PARENT_DIR" 2>/dev/null || true
        log_ok "Removed empty $CLAWCODEX_PARENT_DIR"
    fi

    # Config dir is preserved by design — it contains the user's sessions,
    # auth tokens, history, etc. Removing it requires an explicit rm.
    if [[ -d "$CONFIG_DIR" ]]; then
        log_warn "Preserved config dir: $CONFIG_DIR  (delete manually with 'rm -rf' if desired)"
    fi

    log_warn "Note: this script does not edit your shell rc files. To remove the"
    log_warn "PATH entry, search for '$RC_MARKER' in ~/.bashrc / ~/.zshrc / ~/.profile"
    log_warn "and delete the two lines under it."
    log_ok "Uninstall complete."
}

# ============================================================================
#  Help / version
# ============================================================================
print_help() {
    cat <<EOF
clawcodex installer v${INSTALLER_VERSION}  (installs clawcodex v${CLAWCODEX_VERSION})

USAGE
    $0 [SUBCOMMAND] [OPTIONS]

SUBCOMMANDS
    (none) / install   Install clawcodex (default action).
    status             Show current install state — no side effects.
    doctor             Diagnose the environment (git, python, network, disk,
                       permissions) — no side effects.
    verify             Health-check an existing install (venv, entry point,
                       PATH, smoke test) — no side effects.
    update             Pull latest from the configured ref and reinstall deps.
    uninstall          Remove everything this installer created.
    help               Show this help.

OPTIONS
    --ref <ref>            Override the git ref to install (commit SHA, tag, or
                           branch). Default: ${REPO_REF} (derived from
                           CLAWCODEX_VERSION). Useful for pinning to an exact
                           commit during bisection or for testing unreleased
                           code.
    --install-dir <path>   Override the project clone + venv location.
                           Default: ${DEFAULT_INSTALL_DIR}
    --config-dir <path>    Override the runtime config directory
                           (sessions, auth, history). Default: ${DEFAULT_CONFIG_DIR}
                           Exposed to clawcodex-dev via the CLAWCODEX_CONFIG_DIR
                           env var injected by the wrapper scripts.
    --no-venv              Skip virtual-environment creation. Dependencies are
                           installed into the active system Python via
                           'uv pip install --system'. Use this in Docker
                           images, system-Python distros, or any environment
                           where the venv would be redundant.
    --no-setup             Skip the post-install configuration-wizard prompt.
                           Use for non-interactive / CI / Docker installs.
                           You can configure later by running 'clawcodex-dev'.
    --debug                Enable shell trace mode (set -x) for debugging
                           installer failures.  Produces verbose output of
                           every command executed.
    --dry-run              Preview every change without applying it. Prints
                           each command that would run as '[DRY-RUN] would
                           run: ...'. Combines well with status / doctor.
    --yes, -y              Assume 'yes' for any interactive prompts.
    --log-file <path>      Tee all output (stdout + stderr) to <path>. The
                           EXIT summary prints the log file path on success
                           and on failure.
    --uninstall, -u        Alias for the 'uninstall' subcommand.
    --help, -h             Show this help (English).
    --help-zh              Show help in Chinese (中文帮助).
    --version, -v          Print installer version.

DEFAULTS
    Repo         : ${REPO_URL}
    Git ref      : ${REPO_REF}  (override with --ref)
    Install path : ${DEFAULT_INSTALL_DIR}  (override with --install-dir)
    Config path  : ${DEFAULT_CONFIG_DIR}  (override with --config-dir)
    Python       : >= ${PYTHON_MIN_VERSION}  (provisioned by uv if missing)
    Tooling      : uv (Astral's package manager — installed user-local, no sudo)

EXAMPLES
    # First-time install (most common):
    $0

    # Check if install is healthy (agent / CI / post-deploy check):
    $0 verify

    # See what's installed and where:
    $0 status

    # Diagnose the environment before installing:
    $0 doctor

    # Install a specific tag (e.g. for bisection):
    $0 --ref v0.5.0

    # Custom install + config directories (e.g. system-wide):
    sudo $0 --install-dir /opt/clawcodex --config-dir /var/lib/clawcodex

    # Non-interactive install for CI / Docker (no venv, no setup wizard):
    $0 --no-venv --no-setup --yes --log-file /tmp/install.log

    # Preview what an install would do without applying:
    $0 --dry-run

    # Re-run after a failed install to capture full output for bug reports:
    $0 --log-file /tmp/install.log
    # ... and read /tmp/install.log

    # Remove everything this script installed (preserves config dir):
    $0 uninstall

TROUBLESHOOTING
    "Git is not installed"
        Install Git for your platform (apt/dnf/brew/xcode-select). Re-run $0.

    "uv installer failed to download" / network errors
        Check your network, proxy, or VPN. Retry: $0.
        Manual uv install: curl -LsSf https://astral.sh/uv/install.sh | sh

    "git clone failed"
        Verify network: curl -I ${REPO_URL}
        If behind a firewall, configure a proxy or use a mirror.

    "uv venv failed" / "uv sync failed" / "uv pip install failed"
        Re-run with --log-file to capture full output: $0 --log-file /tmp/out.log
        Diagnose: $0 doctor
        Clean reinstall: $0 uninstall && $0

    "clawcodex-dev: command not found" after install
        Your shell hasn't picked up the new PATH yet. Run:
            source ~/.bashrc   # or: source ~/.zshrc
        Or open a new terminal.

    Permission errors when writing to $HOME/.local/bin or $HOME/.clawcodex
        Pick a writable location: $0 --install-dir ~/apps/clawcodex

    Stale install (changes don't take effect)
        Pull latest + reinstall: $0 update
        Hard reset:             $0 uninstall && $0

EXIT CODES
    0    Success.
    1    Installation / verification / doctor found a problem.
    2    Invalid CLI argument (unknown flag, missing value).
    3    Doctor / verify found critical issues.

VERSIONING
    This install.sh is paired 1:1 with a clawcodex release. CLAWCODEX_VERSION and
    REPO_REF are the version pin; the matching uv.lock pins every transitive
    dependency. To install a different clawcodex version, download the
    install.sh that ships with that release — do NOT just edit these constants
    in isolation, since the lock file is what actually pins the dependency
    versions. The --ref flag is a deliberate escape hatch for testing specific
    commits and is NOT a substitute for shipping a properly tagged installer.

NOTES
    - Re-running this script is safe: existing repos are fast-forwarded,
      existing venvs are reused, command wrappers are regenerated.
    - On Windows, run from Git Bash or WSL. To set up:
        Git Bash : install Git for Windows (https://git-scm.com/download/win),
                   open "Git Bash" from the Start menu, then run this script.
        WSL2     : open PowerShell as Admin, run 'wsl --install -d Ubuntu',
                   then run this script in the Ubuntu terminal.
        The script detects native cmd.exe / PowerShell and exits with a
        clear instruction — it does NOT support those shells directly.
    - In non-TTY mode (piped / agent / CI), every emitted line is prefixed
      with '[install.sh]'. The EXIT trap emits a 'DONE: success|FAILED'
      line on its own, so you can grep the tail of any captured log.
EOF
}

print_help_zh() {
    cat <<EOF
clawcodex 安装脚本 v${INSTALLER_VERSION}  (安装 clawcodex v${CLAWCODEX_VERSION})

用法
    $0 [子命令] [选项]

子命令
    （无） / install   安装 clawcodex（默认动作）。
    status             显示当前安装状态——无副作用。
    doctor             诊断环境（git、python、网络、磁盘、权限）——无副作用。
    verify             健康检查已有安装（venv、入口、PATH、烟雾测试）——无副作用。
    update             拉取最新代码并重装依赖。
    uninstall          卸载本脚本创建的所有内容。
    help               显示本帮助。

选项
    --ref <引用>           覆盖要安装的 git 引用（commit SHA、tag 或分支）。
                           默认：${REPO_REF}（由 CLAWCODEX_VERSION 推导得出）。
                           常用于 bisect 时精确锁定 commit，或测试未发布代码。
    --install-dir <路径>   覆盖项目克隆和 venv 所在的位置。
                           默认：${DEFAULT_INSTALL_DIR}
    --config-dir <路径>    覆盖运行时配置目录（会话、鉴权、历史记录）。
                           默认：${DEFAULT_CONFIG_DIR}
                           通过 wrapper 脚本注入的 CLAWCODEX_CONFIG_DIR
                           环境变量暴露给 clawcodex-dev。
    --no-venv              跳过虚拟环境的创建。依赖直接安装到当前系统
                           Python（使用 'uv pip install --system'）。适用
                           于 Docker 镜像、发行版自带 Python、或任何 venv
                           多余的环境。
    --no-setup             跳过安装后的交互式配置向导。适用于非交互 / CI
                           / Docker 场景。之后可随时手动运行
                           'clawcodex-dev' 进行配置。
    --debug                启用 shell 追踪模式（set -x），用于调试安装
                           失败原因。会输出每一条执行的命令。
    --dry-run              预览所有改动但不实际执行。把每条会运行的命令打
                           印为 '[DRY-RUN] would run: ...'。与 status /
                           doctor 配合使用效果更佳。
    --yes, -y              对所有交互式提示默认回答 yes。
    --log-file <路径>      把所有输出（stdout + stderr）同时写入 <路径>。
                           退出摘要会在成功 / 失败时都打印日志路径。
    --uninstall, -u        'uninstall' 子命令的简写。
    --help, -h             显示英文版帮助。
    --help-zh              显示本中文版帮助。
    --version, -v          打印安装脚本版本。

默认值
    仓库地址   ：${REPO_URL}
    Git 引用  ：${REPO_REF}  （用 --ref 覆盖）
    安装路径  ：${DEFAULT_INSTALL_DIR}  （用 --install-dir 覆盖）
    配置路径  ：${DEFAULT_CONFIG_DIR}  （用 --config-dir 覆盖）
    Python    ：>= ${PYTHON_MIN_VERSION}  （缺失时由 uv 自动提供）
    工具链    ：uv（Astral 的包管理器——用户级安装，无需 sudo）

示例
    # 首次安装（最常见）：
    $0

    # 检查安装是否健康（agent / CI / 部署后检查）：
    $0 verify

    # 查看已安装的内容和位置：
    $0 status

    # 安装前诊断环境：
    $0 doctor

    # 安装特定 tag（例如 bisect 时）：
    $0 --ref v0.5.0

    # 自定义安装和配置目录（例如系统级）：
    sudo $0 --install-dir /opt/clawcodex --config-dir /var/lib/clawcodex

    # CI / Docker 环境的非交互式安装（无 venv、无配置向导）：
    $0 --no-venv --no-setup --yes --log-file /tmp/install.log

    # 预览安装流程而不实际执行：
    $0 --dry-run

    # 安装失败后重新运行以捕获完整输出供排查：
    $0 --log-file /tmp/install.log
    # ... 然后查看 /tmp/install.log

    # 移除本脚本安装的所有内容（保留配置目录）：
    $0 uninstall

故障排查
    "Git is not installed"
        安装 Git：apt/dnf/brew/xcode-select，然后重新运行 $0。

    "uv installer failed to download" / 网络错误
        检查网络、代理、VPN。重试：$0。
        手动安装 uv：curl -LsSf https://astral.sh/uv/install.sh | sh

    "git clone failed"
        验证网络：curl -I ${REPO_URL}
        如果在防火墙后，配置代理或使用镜像。

    "uv venv failed" / "uv sync failed" / "uv pip install failed"
        重新运行并用 --log-file 捕获完整输出：$0 --log-file /tmp/out.log
        诊断：$0 doctor
        干净重装：$0 uninstall && $0

    安装后提示 "clawcodex-dev: command not found"
        当前 shell 还没加载新的 PATH。运行：
            source ~/.bashrc   # 或：source ~/.zshrc
        或新开一个终端。

    写入 $HOME/.local/bin 或 $HOME/.clawcodex 时权限错误
        选择可写位置：$0 --install-dir ~/apps/clawcodex

    安装版本陈旧（修改不生效）
        拉取最新 + 重装：$0 update
        硬重置：        $0 uninstall && $0

退出码
    0    成功。
    1    安装 / 验证 / 诊断发现问题。
    2    无效的 CLI 参数（未知选项、缺少值）。
    3    doctor / verify 发现严重问题。

版本控制
    本 install.sh 与 clawcodex 的某个发布版本一一对应。CLAWCODEX_VERSION
    和 REPO_REF 是版本钉子；对应的 uv.lock 把所有传递依赖一并锁定。要
    安装不同版本的 clawcodex，请下载该发布版自带的 install.sh——不要
    单独修改这些常量，因为真正钉住依赖版本的是 lock 文件。--ref 标志
    是用于测试特定 commit 的有意保留的逃生口，**不能**替代正规打 tag
    的安装脚本。

注意事项
    - 重复运行本脚本是安全的：已存在的仓库会 fast-forward，已存在的
      venv 会复用，命令 wrapper 会重新生成。
    - 在 Windows 上请从 Git Bash 或 WSL 运行。设置方式：
        Git Bash : 安装 Git for Windows (https://git-scm.com/download/win)，
                   在开始菜单中打开 "Git Bash"，然后运行本脚本。
        WSL2     : 以管理员身份打开 PowerShell，执行 'wsl --install -d Ubuntu'，
                   重启后在 Ubuntu 终端中运行本脚本。
        原生 cmd.exe / PowerShell 不支持本脚本——运行时会被检测到并给出
        明确的提示信息。
    - 在非 TTY 模式（管道 / agent / CI）下，每一行输出都会加上
      '[install.sh]' 前缀。EXIT trap 会单独输出一行
      'DONE: success|FAILED'，所以你可以直接 grep 日志末尾判断结果。
EOF
}

# ============================================================================
#  Install pipeline
# ============================================================================
install_main() {
    echo -e "${C_BOLD}clawcodex installer v${INSTALLER_VERSION}${C_RESET}"
    echo -e "  ${C_BOLD}OS:${C_RESET}          $OS"
    echo -e "  ${C_BOLD}Install dir:${C_RESET} $CLAWCODEX_HOME"
    echo -e "  ${C_BOLD}Config dir:${C_RESET}  $CONFIG_DIR"
    echo -e "  ${C_BOLD}Git ref:${C_RESET}     $REPO_REF"
    echo -e "  ${C_BOLD}Venv:${C_RESET}        $([[ $USE_VENV -eq 1 ]] && echo "create at $CLAWCODEX_HOME/.venv" || echo "${C_YELLOW}skipped (--no-venv, system Python)${C_RESET}")"
    echo -e "  ${C_BOLD}Setup wizard:${C_RESET} $([[ $RUN_SETUP -eq 1 ]] && echo "announce only (non-blocking)" || echo "${C_YELLOW}skipped (--no-setup)${C_RESET}")"
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        echo -e "  ${C_BOLD}Mode:${C_RESET}        ${C_YELLOW}DRY-RUN (no changes will be made)${C_RESET}"
    fi
    if [[ -n "${LOG_FILE:-}" ]]; then
        echo -e "  ${C_BOLD}Log file:${C_RESET}    $LOG_FILE"
    fi
    if [[ "${DEBUG:-0}" -eq 1 ]]; then
        echo -e "  ${C_BOLD}Debug:${C_RESET}       ${C_YELLOW}ON (set -x trace)${C_RESET}"
    fi

    log_step "1/7  Checking prerequisites"
    check_git

    log_step "2/7  Installing uv (Astral, no sudo)"
    # Re-source in case it wasn't on PATH at the top of the script.
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    install_uv

    log_step "3/7  Provisioning Python $PYTHON_MIN_VERSION+"
    ensure_python

    log_step "4/7  Cloning / updating repository"
    clone_or_update_repo

    log_step "5/7  $([[ $USE_VENV -eq 1 ]] && echo "Creating virtual environment" || echo "Preparing (no venv — using system Python)")"
    create_venv

    log_step "6/7  Installing dependencies (uv sync --extra all, lock-pinned)"
    install_deps

    log_step "7/7  Registering global commands & patching PATH"
    register_commands
    update_shell_rc

    echo ""
    log_ok "Installation complete!"
    echo ""
    echo -e "  ${C_BOLD}Try it:${C_RESET}"
    echo -e "    clawcodex-dev --help      # primary command"
    echo -e "    clawcodex    --help       # alias of clawcodex-dev"
    echo ""
    echo -e "  ${C_BOLD}Installed at:${C_RESET}  $CLAWCODEX_HOME"
    echo -e "  ${C_BOLD}Config at:${C_RESET}    $CONFIG_DIR"
    echo -e "  ${C_BOLD}Commands at:${C_RESET}   $LOCAL_BIN/{clawcodex,clawcodex-dev}"
    echo ""

    # Step 8 (post-install setup) lives outside the 1–7 numbered pipeline
    # because it's optional and varies the most.
    run_post_install_setup

    log_warn "Open a new shell, or run:  source ~/.bashrc   (or ~/.zshrc)"
}

# ============================================================================
#  CLI argument parser — populates the *OVERRIDE globals, then they're
#  resolved into the actual install/config/ref variables below.
# ============================================================================
REF_OVERRIDE=""
INSTALL_DIR_OVERRIDE=""
CONFIG_DIR_OVERRIDE=""
USE_VENV=1       # --no-venv flips to 0
RUN_SETUP=1      # --no-setup flips to 0
DRY_RUN=0        # --dry-run flips to 1
ASSUME_YES=0     # --yes/-y flips to 1
LOG_FILE=""      # --log-file <path>
DEBUG=0          # --debug flips to 1 (set -x trace)
SUBCOMMAND=""    # positional verb (install/status/doctor/verify/update/uninstall/help)
SCRIPT_START_TS=$(date +%s)

print_usage_hint() {
    echo "Try '$0 --help' for usage." >&2
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            # --- Subcommands (positional verbs) ---
            install|status|doctor|verify|update|uninstall|help)
                SUBCOMMAND="$1"; shift ;;

            # --- Option flags ---
            --ref)
                [[ $# -ge 2 ]] || { log_err "--ref requires a value (commit/tag/branch)"; print_usage_hint; exit 1; }
                REF_OVERRIDE="$2"; shift 2 ;;
            --install-dir)
                [[ $# -ge 2 ]] || { log_err "--install-dir requires a path"; print_usage_hint; exit 1; }
                INSTALL_DIR_OVERRIDE="$2"; shift 2 ;;
            --config-dir)
                [[ $# -ge 2 ]] || { log_err "--config-dir requires a path"; print_usage_hint; exit 1; }
                CONFIG_DIR_OVERRIDE="$2"; shift 2 ;;
            --log-file)
                [[ $# -ge 2 ]] || { log_err "--log-file requires a path"; print_usage_hint; exit 1; }
                LOG_FILE="$2"; shift 2 ;;
            --dry-run)
                DRY_RUN=1; shift ;;
            --yes|-y)
                ASSUME_YES=1; shift ;;
            --no-venv)
                USE_VENV=0; shift ;;
            --no-setup)
                RUN_SETUP=0; shift ;;
            --debug)
                DEBUG=1; shift ;;
            --uninstall|-u)
                SUBCOMMAND="uninstall"; shift ;;
            --help|-h)
                print_help; exit 0 ;;
            --help-zh)
                print_help_zh; exit 0 ;;
            --version|-v)
                echo "install.sh v${INSTALLER_VERSION} (installs clawcodex v${CLAWCODEX_VERSION})"
                exit 0 ;;

            --)
                shift; break ;;
            -*)
                log_err "Unknown option: $1"; print_usage_hint; exit 1 ;;
            *)
                log_err "Unexpected positional argument: $1"; print_usage_hint; exit 1 ;;
        esac
    done
}

# ============================================================================
#  Entry point
# ============================================================================
parse_args "$@"

# Resolve overrides → effective install/config paths. Must run AFTER
# parse_args, otherwise INSTALL_DIR_OVERRIDE / REF_OVERRIDE are still
# empty when CLAWCODEX_HOME / REPO_REF get resolved and the flags are
# silently ignored.
CLAWCODEX_HOME="${INSTALL_DIR_OVERRIDE:-$DEFAULT_INSTALL_DIR}"
CLAWCODEX_PARENT_DIR="$(dirname -- "$CLAWCODEX_HOME")"
CONFIG_DIR="${CONFIG_DIR_OVERRIDE:-$DEFAULT_CONFIG_DIR}"
[[ -n "$REF_OVERRIDE" ]] && REPO_REF="$REF_OVERRIDE"

OS=$(detect_os)

# Bail out for native Windows shells — this script targets bash, not cmd/PS.
if [[ "$OS" == "unknown" ]] && [[ -n "${COMSPEC:-}" || -n "${WINDIR:-}" ]]; then
    cat >&2 <<'END_MSG'
✗ Native Windows shell detected (cmd.exe or PowerShell).

  install.sh is a bash script and cannot run directly in cmd or PowerShell.
  Please use one of the following options:

  Option A — Git Bash (recommended, zero-config):
    1. Install Git for Windows from https://git-scm.com/download/win
    2. Open "Git Bash" from the Start menu
    3. In Git Bash, run:    bash install.sh

  Option B — WSL2 (full Linux environment):
    1. Open PowerShell as Administrator and run:
         wsl --install -d Ubuntu
    2. Restart your computer
    3. Open the Ubuntu terminal and run:
         sudo apt update && sudo apt install -y git curl
         bash install.sh

  Option C — Install manually from source:
    1. Install Git, Python 3.10+, and curl
    2. Run:
         git clone https://gitcode.com/chadwweng/clawcodex /tmp/clawcodex
         cd /tmp/clawcodex
         pip install -e ".[all]"
    (See https://gitcode.com/chadwweng/clawcodex for details)

END_MSG
    exit 1
fi

# Make uv visible early in case it's already installed but not on PATH for this shell.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# Set up log-file tee if requested. Must happen AFTER parse_args so LOG_FILE
# is set, but BEFORE any other output. After this exec, [[ -t 1 ]] is false
# (it's a pipe), so the [install.sh] prefix is added on every line.
if [[ -n "$LOG_FILE" ]]; then
    log_file_dir=$(dirname -- "$LOG_FILE")
    if [[ ! -d "$log_file_dir" ]]; then
        mkdir -p "$log_file_dir" 2>/dev/null || { log_warn "Cannot create log dir $log_file_dir; --log-file ignored"; LOG_FILE=""; }
    fi
    if [[ -n "$LOG_FILE" ]]; then
        exec > >(tee -a "$LOG_FILE") 2>&1
    fi
fi

# Install the EXIT trap. Runs on every exit (normal, error, or signal).
# Emits a structured "DONE: success|FAILED" line plus log-file location.
trap '_on_exit_summary $?' EXIT

# Activate debug mode (set -x) if --debug was passed.  Must come after the
# trap setup so the trace output is visible from the very first command.
if [[ "$DEBUG" -eq 1 ]]; then
    set -x
fi

# Dispatch to subcommand. Default to 'install' when none was given.
case "${SUBCOMMAND:-install}" in
    install)   install_main ;;
    status)    cmd_status ;;
    doctor)    cmd_doctor ;;
    verify)    cmd_verify ;;
    update)    cmd_update ;;
    uninstall) uninstall ;;
    help)      print_help ;;
    *)
        log_err "Unknown subcommand: $SUBCOMMAND"
        print_usage_hint
        exit 1
        ;;
esac
