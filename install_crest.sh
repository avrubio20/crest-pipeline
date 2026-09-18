#!/bin/bash
# install_crest.sh -- install the CREST conformer-search pipeline for one account.
#
#   ./install_crest.sh                     install with this host's defaults
#   ./install_crest.sh --prefix ~/crest    install somewhere else
#   ./install_crest.sh --check             can this machine actually run it?
#   ./install_crest.sh --example           write a ready-to-run test case
#   ./install_crest.sh --dry-run           print what it would do, write nothing
#
#   --prefix DIR      the tools go here            [$HOME/crest]
#   --bindir DIR      just the tools               [PREFIX/bin]
#   --crest-bin PATH  the crest binary             [found on PATH]
#   --xtb-bin DIR     the directory holding xtb    [found on PATH]
#   --scratch DIR     fast temporary space         [detected]
#   --config FILE     where the choices go         [$HOME/.crest.conf]
#   --shared          make the install readable by your unix group
#   --add-path        put bindir on your PATH
#   --force           replace installed files that differ from these
#
# CREST and xtb are not downloaded -- clusters have them. This finds them and
# records where. Re-running is safe and nothing here ever submits a job.
set -uo pipefail

TOOLS=(runcrest.py prepcrest.py)
SUITES=(test_runcrest.sh)
SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

# Per-machine defaults, written into the config.
if [[ -n "${SGE_ROOT:-}" || -d /u/local/Modules ]]; then
    HOST=hoffman2; SCHEDULER=uge; DEF_SCRATCH='${TMPDIR:-${SCRATCH:-/tmp}}'
elif command -v sbatch >/dev/null; then
    HOST=slurm; SCHEDULER=slurm; DEF_SCRATCH='${SCRATCH:-/tmp}'
else
    HOST=unknown; SCHEDULER=slurm; DEF_SCRATCH='/tmp'
fi

DEFAULT_PREFIX="$HOME/crest"
PREFIX=""; BINDIR=""; CREST_BIN=""; XTB_BIN=""; SCRATCH=""
CONFIG="$HOME/.crest.conf"
DRY=0; FORCE=0; CHECK=0; ADDPATH=0; EXAMPLE=0; SHARED=0

argval() {
    [[ -n "${2:-}" && "${2:-}" != --* ]] && return 0
    echo "ERROR: $1 needs a value" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)    argval "$1" "${2:-}"; PREFIX="$2";    shift 2;;
        --bindir)    argval "$1" "${2:-}"; BINDIR="$2";    shift 2;;
        --crest-bin) argval "$1" "${2:-}"; CREST_BIN="$2"; shift 2;;
        --xtb-bin)   argval "$1" "${2:-}"; XTB_BIN="$2";   shift 2;;
        --scratch)   argval "$1" "${2:-}"; SCRATCH="$2";   shift 2;;
        --config)    argval "$1" "${2:-}"; CONFIG="$2";    shift 2;;
        --check)     CHECK=1;   shift;;
        --example)   EXAMPLE=1; shift;;
        --add-path)  ADDPATH=1; shift;;
        --shared)    SHARED=1;  shift;;
        --dry-run)   DRY=1;     shift;;
        --force)     FORCE=1;   shift;;
        -h|--help)   sed -n '2,23p' "$0"; exit 0;;
        *) echo "ERROR: unknown option $1 (try --help)" >&2; exit 1;;
    esac
done

if [[ $CHECK -eq 1 ]] \
   && [[ $EXAMPLE -eq 1 || $ADDPATH -eq 1 || $SHARED -eq 1 || $DRY -eq 1 || $FORCE -eq 1 ]]; then
    echo "ERROR: --check only reports. Run it on its own, then install." >&2
    exit 1
fi

expand() { echo "${1/#\~/$HOME}"; }
CONFIG="$(expand "$CONFIG")"

run() {
    if [[ $DRY -eq 1 ]]; then echo "  would: $(printf '%q ' "$@")"
    else "$@"; fi
}
ok()   { echo "  ok    $*"; PASSED=$((PASSED + 1)); TOTAL=$((TOTAL + 1)); }
bad()  { echo "  FAIL  $*"; FAILED=1;  TOTAL=$((TOTAL + 1)); }
note() { echo "  note  $*"; }

# An existing config fills in whatever you did not pass this time.
cfg() { [[ -f "$CONFIG" ]] && sed -n "s/^ *$1 *= *//p" "$CONFIG" | head -1; }
CFG_BINDIR="$(cfg bindir)"; CFG_CREST="$(cfg crest)"
CFG_XTB_BIN="$(cfg xtb_bin)"; CFG_SCRATCH="$(cfg scratch)"

# PATH first (a module or group install puts them there), then by hand.
find_crest() {
    command -v crest 2>/dev/null && return 0
    local c
    for c in "$HOME"/project-houk/Programs/crest-*/crest "$HOME"/Programs/crest-*/crest \
             /u/project/*/apps/crest*/crest; do
        [[ -x "$c" ]] && { echo "$c"; return 0; }
    done
    return 1
}
find_xtb() {
    local x
    x="$(command -v xtb 2>/dev/null)" && { dirname "$x"; return 0; }
    for x in "$HOME"/project-houk/Programs/xtb-*/bin/xtb "$HOME"/Programs/xtb-*/bin/xtb; do
        [[ -x "$x" ]] && { dirname "$x"; return 0; }
    done
    return 1
}

[[ -n "$PREFIX" && -z "$BINDIR" ]] && BINDIR="$(expand "$PREFIX")/bin"
BINDIR="$(expand "${BINDIR:-${CFG_BINDIR:-$DEFAULT_PREFIX/bin}}")"
CREST_BIN="${CREST_BIN:-${CFG_CREST:-$(find_crest || true)}}"
XTB_BIN="${XTB_BIN:-${CFG_XTB_BIN:-$(find_xtb || true)}}"
SCRATCH="${SCRATCH:-${CFG_SCRATCH:-$DEF_SCRATCH}}"
# xtb needs its parameter directory; it sits beside bin/ in every release.
XTB_PATH=""
[[ -n "$XTB_BIN" && -d "$(dirname "$XTB_BIN")/share/xtb" ]] \
    && XTB_PATH="$(dirname "$XTB_BIN")/share/xtb"

if [[ $CHECK -eq 1 ]]; then
    echo "Environment check ($HOST)"
    FAILED=0; PASSED=0; TOTAL=0
    [[ -f "$CONFIG" ]] && ok "config: $CONFIG" || note "no config yet; install first"

    if [[ "$SCHEDULER" == uge ]]; then
        qsub_path="$(command -v qsub 2>/dev/null)"
        for c in "${SGE_ROOT:-/u/systems}"/*/bin/*/qsub /u/local/bin/qsub; do
            [[ -n "$qsub_path" ]] && break
            [[ -x "$c" ]] && qsub_path="$c"
        done
        [[ -n "$qsub_path" ]] && ok "qsub: $qsub_path" \
            || bad "no qsub found -- are you on a login node?"
    else
        command -v sbatch >/dev/null && ok "sbatch: $(command -v sbatch)" \
            || note "no sbatch on PATH; you can prepare jobs here but not submit"
    fi

    if [[ -x "$CREST_BIN" ]] && "$CREST_BIN" --version >/dev/null 2>&1; then
        ok "crest runs: $CREST_BIN"
    else
        bad "crest does not run: ${CREST_BIN:-not found}"
        echo "        Point at it with --crest-bin /path/to/crest"
    fi

    if [[ -x "$XTB_BIN/xtb" ]] && "$XTB_BIN/xtb" --version >/dev/null 2>&1; then
        ok "xtb runs: $XTB_BIN/xtb"
        "$XTB_BIN/xtb" --help 2>&1 | grep -q -- --gxtb \
            && ok "this xtb knows --gxtb" \
            || note "this xtb has no --gxtb; fine for CREST, not for g-xTB work"
    else
        bad "xtb does not run: ${XTB_BIN:-not found}/xtb"
        echo "        Point at it with --xtb-bin /path/to/xtb/bin"
    fi
    [[ -n "$XTB_PATH" ]] && ok "xtb parameters: $XTB_PATH" \
        || note "no share/xtb beside $XTB_BIN; xtb may not find its parameters"

    for tool in "${TOOLS[@]}"; do
        command -v "$tool" >/dev/null && ok "$tool on PATH" \
            || bad "$tool not on PATH (add $BINDIR to it)"
    done

    for suite in "${SUITES[@]}"; do
        path="$BINDIR/$suite"; [[ -f "$path" ]] || path="$SRC/$suite"
        if [[ -f "$BINDIR/$suite" && -f "$SRC/$suite" ]] \
           && ! cmp -s "$BINDIR/$suite" "$SRC/$suite"; then
            note "$suite here differs from the installed one; testing the"\
                 "installed copy. Re-run with --force to update it."
        fi
        if [[ -f "$path" ]]; then
            echo "  ...   running $suite"
            output=$(bash "$path" 2>&1); rc=$?
            result=$(tail -1 <<<"$output")
            [[ $rc -eq 0 && "$result" == PASS* ]] \
                && ok "$suite: $result" || bad "$suite: $result (exit $rc)"
        else
            bad "$suite not found in $BINDIR or $SRC -- reinstall"
        fi
    done

    echo
    [[ $FAILED -ne 0 ]] \
        && echo "Passed $PASSED/$TOTAL checks. Fix the FAIL lines above." \
        || echo "Passed $PASSED/$TOTAL checks."
    exit $FAILED
fi

echo "CREST pipeline install"
echo "  host:     $HOST ($SCHEDULER)"
echo "  tools:    $BINDIR"
echo "  crest:    ${CREST_BIN:-NOT FOUND}"
echo "  xtb:      ${XTB_BIN:-NOT FOUND}"
echo "  config:   $CONFIG"
[[ $DRY -eq 1 ]] && echo "  (dry run -- nothing will be written)"
echo

if [[ -z "$CREST_BIN" || -z "$XTB_BIN" ]]; then
    echo "ERROR: could not find crest and/or xtb on this machine." >&2
    echo "       They are not downloaded for you -- clusters usually have them." >&2
    echo "       Load the module that provides them, or point at them:" >&2
    echo "         ./install_crest.sh --crest-bin /path/to/crest --xtb-bin /path/to/xtb/bin" >&2
    exit 1
fi

echo "Tools: $BINDIR"
run mkdir -p "$BINDIR" || { echo "ERROR: cannot create $BINDIR" >&2; exit 1; }
STALE=0
for f in "${TOOLS[@]}" "${SUITES[@]}"; do
    [[ -f "$SRC/$f" ]] || { echo "  ERROR: $SRC/$f is missing" >&2; exit 1; }
    if [[ -e "$BINDIR/$f" ]] && cmp -s "$SRC/$f" "$BINDIR/$f"; then
        echo "  $f (already current)"
        continue
    fi
    if [[ -e "$BINDIR/$f" && $FORCE -eq 0 ]]; then
        echo "  $f DIFFERS from the copy here -- --force to replace"
        STALE=1
        continue
    fi
    run cp "$SRC/$f" "$BINDIR/$f" || { echo "ERROR: cannot write $BINDIR/$f" >&2; exit 1; }
    run chmod +x "$BINDIR/$f" || exit 1
    echo "  $f"
done

echo "Config: $CONFIG"
if [[ $DRY -eq 1 ]]; then
    echo "  would: record bindir, crest, xtb_bin, xtb_path, scratch, scheduler"
else
    mkdir -p "$(dirname "$CONFIG")" \
        || { echo "ERROR: cannot create $(dirname "$CONFIG")" >&2; exit 1; }
    [[ ! -e "$CONFIG" || -w "$CONFIG" ]] \
        || { echo "ERROR: $CONFIG is not yours to write" >&2; exit 1; }
    tmp_config="$CONFIG.$$"
    cat > "$tmp_config" <<CONF
# CREST pipeline. Written by install_crest.sh on $(date +%F).
# Re-run it to change these, or edit them here -- the tools read this file.
bindir    = $BINDIR
crest     = $CREST_BIN
xtb_bin   = $XTB_BIN
xtb_path  = $XTB_PATH
scratch   = $SCRATCH
scheduler = $SCHEDULER

# UGE only: the parallel environment and node policy at your site.
uge_pe        = shared
uge_resources = arch=intel*
CONF
    [[ -s "$tmp_config" ]] && mv "$tmp_config" "$CONFIG" \
        || { rm -f "$tmp_config"; echo "ERROR: could not write $CONFIG" >&2; exit 1; }
    echo "  recorded; CREST_CONF overrides the location"
    shared_dir="$(dirname "$BINDIR")/etc"
    if mkdir -p "$shared_dir" 2>/dev/null && cp "$CONFIG" "$shared_dir/crest.conf" 2>/dev/null; then
        echo "  copy at $shared_dir/crest.conf for anyone else using this install"
    fi
fi

if [[ $EXAMPLE -eq 1 ]]; then
    echo "Example: ./crest_example"
    for f in butanol.xyz butanol.toml; do
        [[ -f "$SRC/examples/$f" ]] \
            || { echo "ERROR: $SRC/examples/$f is missing" >&2; exit 1; }
    done
    run mkdir -p crest_example || exit 1
    run cp "$SRC/examples/butanol.xyz" "$SRC/examples/butanol.toml" crest_example/ \
        || { echo "ERROR: cannot write ./crest_example" >&2; exit 1; }
    echo "  butanol.xyz + butanol.toml (a small, fast conformer search)"
fi

case "${SHELL:-/bin/bash}" in
    *csh) RC="$HOME/.cshrc"; PATH_LINE="setenv PATH \"\${PATH}:$BINDIR\"";;
    *)    RC="$HOME/.bashrc"; PATH_LINE="export PATH=\"\$PATH:$BINDIR\"";;
esac
echo
if [[ ":${PATH:-}:" == *":$BINDIR:"* ]]; then
    echo "PATH: $BINDIR is already on it."
elif [[ $ADDPATH -eq 1 ]]; then
    if grep -qsF "$PATH_LINE" "$RC"; then
        echo "$RC already has: $PATH_LINE"
    else
        run bash -c "printf '\n# CREST pipeline\n%s\n' \"\$1\" >> '$RC'" _ "$PATH_LINE" \
            || { echo "ERROR: cannot write $RC; add this line yourself:" >&2
                 echo "    $PATH_LINE" >&2; exit 1; }
        echo "$RC += $PATH_LINE"
    fi
    echo "Run 'source $RC' or log back in."
    if grep -qsE '^\s*(\[\[ \$-|case \$-)' "$RC"; then
        echo
        echo "NOTE: your $RC returns early for non-interactive shells, and the"
        echo "      line above was appended after that point. It applies when you"
        echo "      are typing at a prompt, but not to 'ssh host \"command\"'."
    fi
else
    echo "Add to $RC (or re-run with --add-path):"
    echo "    $PATH_LINE"
fi

if [[ $SHARED -eq 1 ]]; then
    echo
    echo "Shared: making $BINDIR readable by your group"
    run chmod -R g+rX "$BINDIR" \
        || { echo "ERROR: could not make the install group-readable" >&2; exit 1; }
    run find "$BINDIR" -type d -exec chmod g+s {} + \
        || echo "  WARNING: could not set setgid" >&2
fi

if [[ $STALE -eq 1 ]]; then
    cat >&2 <<STALE_MSG

Some tools already installed differ from the ones here and were left alone, so
$BINDIR is now a mix of two versions. Re-run with --force to replace them.
STALE_MSG
    exit 1
fi

cat <<NEXT

Next, from this directory -- install_crest.sh is not copied onto your PATH:
    ./install_crest.sh --check       verifies crest, xtb and the tools
    ./install_crest.sh --example     writes ./crest_example/
    cd crest_example
    runcrest.py butanol.toml             submit the search
    ls crest_conformers.xyz              the ensemble, when it lands
Then your own molecule:
    prepcrest.py mol.xyz                 build mol.toml interactively
    runcrest.py mol.toml
NEXT
