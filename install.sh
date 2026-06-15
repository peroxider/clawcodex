#!/usr/bin/env bash
# ============================================================================
#  install.sh — One-click installer for clawcodex
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
#  Usage:
#     ./install.sh                # install
#     ./install.sh --uninstall    # remove everything this script created
#     ./install.sh --help
# ----------------------------------------------------------------------------
set -euo pipefail

# ============================================================================
#  Config
# ============================================================================
# Versioning scheme
# -----------------
#   INSTALLER_VERSION  — version of this install.sh script itself
#   CLAWCODEX_VERSION  — version of clawcodex that THIS install.sh installs
#   REPO_REF           — git ref (tag/branch) the install clones
#
# Bump CLAWCODEX_VERSION in lockstep with clawcodex releases and commit it
# alongside the matching tag on the remote. That way an OLD install.sh always
# installs the OLD clawcodex (with its OLD uv.lock), never the bleeding edge.
# If REPO_REF doesn't resolve on the remote, the install falls back to the
# default branch with a loud warning — useful during the pre-tag period of
# a release but should never ship in a tagged installer.
readonly INSTALLER_VERSION="1.2.0"
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

log_info() { echo -e "${C_BLUE}==>${C_RESET} ${C_BOLD}$1${C_RESET}"; }
log_ok()   { echo -e "  ${C_GREEN}✓${C_RESET} $1"; }
log_warn() { echo -e "  ${C_YELLOW}!${C_RESET} $1"; }
log_err()  { echo -e "${C_RED}✗${C_RESET} $1" >&2; }
log_step() { echo -e "\n${C_BOLD}${C_BLUE}>>>${C_RESET} ${C_BOLD}$1${C_RESET}"; }

die() { log_err "$1"; exit 1; }

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
    if ! curl -LsSf --max-time 60 https://astral.sh/uv/install.sh -o "$tmp"; then
        rm -f "$tmp"
        die "Failed to download uv installer (network issue?). Retry or install manually: https://docs.astral.sh/uv/"
    fi
    if ! env UV_INSTALL_DIR="$HOME/.local" sh "$tmp"; then
        rm -f "$tmp"
        die "uv installer exited with an error."
    fi
    rm -f "$tmp"

    # Make uv visible to this session, then verify.
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        die "uv still not on PATH after install. Check $HOME/.local/bin and $HOME/.cargo/bin."
    fi
    log_ok "uv $(uv --version | awk '{print $2}') installed"
}

# ============================================================================
#  Python 3.10+ provisioning (via uv)
# ============================================================================
ensure_python() {
    # Ask uv for any 3.10+ interpreter it can see (system or uv-managed).
    local py
    if py=$(uv python find "$PYTHON_MIN_VERSION" 2>/dev/null) && [[ -n "$py" && -x "$py" ]]; then
        log_ok "Python $($py --version 2>&1 | awk '{print $1, $2}')"
        return
    fi

    log_info "Python $PYTHON_MIN_VERSION+ not found — provisioning via uv (no sudo)..."
    if ! uv python install "$PYTHON_MIN_VERSION"; then
        die "Failed to install Python $PYTHON_MIN_VERSION via uv."
    fi
    py=$(uv python find "$PYTHON_MIN_VERSION" 2>/dev/null || true)
    if [[ -z "$py" || ! -x "$py" ]]; then
        die "Python $PYTHON_MIN_VERSION still not found after uv install."
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
        die "git clone failed. Check your network and the repo URL."
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
    cd "$CLAWCODEX_HOME"
    if [[ -d ".venv" ]]; then
        log_ok "Existing venv at $CLAWCODEX_HOME/.venv"
        return
    fi
    log_info "Creating venv with Python $PYTHON_MIN_VERSION..."
    if ! uv venv --python "$PYTHON_MIN_VERSION" .venv; then
        die "uv venv failed."
    fi
    log_ok "Venv created"
}

# ============================================================================
#  Install dependencies
# ============================================================================
install_deps() {
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
                die "uv pip install to system failed even with --break-system-packages."
            fi
        else
            log_err "uv pip install failed: ${pip_err:-<no stderr captured>}"
            die "Both uv sync and uv pip install failed. See warnings above for details."
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
#  Uninstall — only removes what this script created
# ============================================================================
uninstall() {
    log_info "Uninstalling clawcodex..."
    log_info "  Install dir : $CLAWCODEX_HOME"
    log_info "  Config dir  : $CONFIG_DIR"
    log_info "  Local bin   : $LOCAL_BIN"

    for f in clawcodex-dev clawcodex; do
        if [[ -e "$LOCAL_BIN/$f" || -L "$LOCAL_BIN/$f" ]]; then
            rm -f "$LOCAL_BIN/$f"
            log_ok "Removed $LOCAL_BIN/$f"
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
    $0 [OPTIONS]

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
    --uninstall, -u        Remove everything this installer created.
    --help, -h             Show this help.
    --version, -v          Print installer version.

DEFAULTS
    Repo         : ${REPO_URL}
    Git ref      : ${REPO_REF}  (override with --ref)
    Install path : ${DEFAULT_INSTALL_DIR}  (override with --install-dir)
    Config path  : ${DEFAULT_CONFIG_DIR}  (override with --config-dir)
    Python       : >= ${PYTHON_MIN_VERSION}  (provisioned by uv if missing)
    Tooling      : uv (Astral's package manager — installed user-local, no sudo)

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
    - On Windows, run from Git Bash or WSL. Native cmd / PowerShell is not
      supported by this shell script.
    - All flags can be combined: e.g.
        $0 --ref v0.5.0 --install-dir /opt/clawcodex --config-dir /var/lib/clawcodex --no-venv --no-setup
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

print_usage_hint() {
    echo "Try '$0 --help' for usage." >&2
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --ref)
                [[ $# -ge 2 ]] || { log_err "--ref requires a value (commit/tag/branch)"; print_usage_hint; exit 1; }
                REF_OVERRIDE="$2"; shift 2 ;;
            --install-dir)
                [[ $# -ge 2 ]] || { log_err "--install-dir requires a path"; print_usage_hint; exit 1; }
                INSTALL_DIR_OVERRIDE="$2"; shift 2 ;;
            --config-dir)
                [[ $# -ge 2 ]] || { log_err "--config-dir requires a path"; print_usage_hint; exit 1; }
                CONFIG_DIR_OVERRIDE="$2"; shift 2 ;;
            --no-venv)
                USE_VENV=0; shift ;;
            --no-setup)
                RUN_SETUP=0; shift ;;
            --uninstall|-u)
                uninstall; exit 0 ;;
            --help|-h)
                print_help; exit 0 ;;
            --version|-v)
                echo "install.sh v${INSTALLER_VERSION} (installs clawcodex v${CLAWCODEX_VERSION})"
                exit 0 ;;
            install|"")
                shift ;;   # default action; ignore the bare verb
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
    die "Native Windows shell detected. Please run install.sh from Git Bash or WSL."
fi

# Make uv visible early in case it's already installed but not on PATH for this shell.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

install_main
