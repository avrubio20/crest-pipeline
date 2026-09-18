#!/bin/bash
# Exercises the job script runcrest.py generates, against a stub crest.
# Fails loudly if the copy-back policy, the NaN guards, or the refusal to run
# cregen on a crashed search stop doing what runcrest.py claims they do.
set -uo pipefail
TOOLS="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
RAW="$TOOLS/runcrest.py"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
cd "$T" || exit 1

fail() { echo "FAIL: $*"; exit 1; }

# --- stub crest: writes what a real search leaves behind, and can be told to
#     crash or to produce NaN coordinates ---
mkdir -p fakebin
cat > fakebin/crest <<'STUB'
#!/bin/bash
if [[ "${2:-}" == "-cregen" ]]; then
  echo "cregen ran on $1" > cregen.log
  exit 0
fi
echo "search ran: $*" > crest.log
if [[ -n "${STUB_FAIL:-}" ]]; then echo "boom" >&2; exit 1; fi
coord="C 0.0 0.0 0.0"
[[ -n "${STUB_NAN:-}" ]] && coord="C NaN NaN NaN"
printf '1\n\n%s\n' "$coord" > crest_best.xyz
printf '1\n\n%s\n' "$coord" > crest_conformers.xyz
printf '1\n\nC 1.0 0.0 0.0\n' > crest_dynamics.trj
echo "energies" > ensemble_energies.log
exit 0
STUB
chmod +x fakebin/crest
export PATH="$T/fakebin:$PATH"

cat > crest.conf <<CONF
crest     = $T/fakebin/crest
xtb_bin   = $T/fakebin
xtb_path  = $T/fakebin/share
scratch   = $T/scratch
scheduler = slurm
CONF
export CREST_CONF="$T/crest.conf"

cat > mol.toml <<'TOML'
threads = 4
input = "mol.xyz"
TOML
printf '1\n\nC 0.0 0.0 0.0\n' > mol.xyz

# Most checks read Slurm directives and drive the script with SLURM_* vars, so
# the scheduler is pinned: on a UGE machine it would otherwise write #$ lines.
R() { "$RAW" --scheduler slurm "$@"; }
runjob() { env SLURM_JOB_ID=111 SLURM_SUBMIT_DIR="$T" "$@" bash mol_crest.sh; }

# 1. a script is generated and not submitted
R mol.toml --no-submit >/dev/null 2>&1 || fail "generation failed"
[[ -f mol_crest.sh ]] || fail "no mol_crest.sh written"

# 2. threads come from the .toml, and memory is 2 GB per thread from there
grep -q 'cpus-per-task=4' mol_crest.sh || fail "threads not taken from the .toml"
grep -q 'mem=8192' mol_crest.sh || fail "memory not 2 GB/thread from the .toml"

# 3. -p overrides the .toml, and memory becomes 4 GB per thread
R mol.toml -p 8 --no-submit >/dev/null 2>&1
grep -q 'cpus-per-task=8' mol_crest.sh || fail "-p did not override the .toml"
grep -q 'mem=32768' mol_crest.sh || fail "-m default not 4 GB/thread for -p"

# 4. the UGE dialect is emitted on request, with per-slot memory
"$RAW" mol.toml --scheduler uge --no-submit >/dev/null 2>&1
grep -q '^#\$ -pe shared 4' mol_crest.sh || fail "no UGE parallel environment"
grep -q 'h_data=2048M' mol_crest.sh || fail "UGE memory is not per slot"
grep -q '^#\$ -notify' mol_crest.sh || fail "no -notify, so no USR1 warning"
grep -q 'NSLOTS' mol_crest.sh || fail "UGE script does not read NSLOTS"

# 5. --dry-run writes nothing at all
rm -f mol_crest.sh
R mol.toml --dry-run >/dev/null 2>&1
[[ ! -f mol_crest.sh ]] || fail "--dry-run wrote a script"

# 6. a normal run copies the ensemble back and leaves the churn behind
R mol.toml --no-submit >/dev/null 2>&1
runjob >/dev/null 2>&1 || fail "a clean run exited nonzero"
[[ -f crest_best.xyz && -f crest_conformers.xyz ]] || fail "ensemble not copied back"
[[ -f crest.log ]] || fail "log not copied back"
[[ ! -f crest_dynamics.trj ]] || fail "crest_dynamics.trj should not come back"
[[ ! -f ensemble_energies.log ]] || fail "ensemble_energies.log should not come back"

# 7. scratch is deleted after a clean run
[[ -z "$(ls -A "$T/scratch" 2>/dev/null)" ]] || fail "scratch survived a clean run"

# 8. a crashed search does not run cregen, and says so
rm -f crest_best.xyz crest_conformers.xyz crest.log cregen.log
runjob STUB_FAIL=1 >out.txt 2>&1 && fail "a crashed search exited 0"
grep -q 'not running cregen' out.txt || fail "cregen guard did not fire: $(cat out.txt)"
[[ ! -f cregen.log ]] || fail "cregen ran on a crashed search"

# 9. scratch is kept when the job fails, for debugging
[[ -n "$(ls -A "$T/scratch" 2>/dev/null)" ]] || fail "scratch was deleted after a failure"
rm -rf "$T/scratch"

# 10. NaN coordinates are refused rather than laundered by cregen
printf '1\n\nC 9.9 9.9 9.9\n' > crest_best.xyz      # a good result from last time
runjob STUB_NAN=1 >out.txt 2>&1 && fail "a NaN search exited 0"
grep -q 'NaN' out.txt || fail "NaN not reported: $(cat out.txt)"

# 11. and the NaN structure did not overwrite the good one
grep -q '9.9' crest_best.xyz || fail "a NaN result overwrote a good ensemble"
rm -rf "$T/scratch"

# 12. --notopo reaches both the search and the final sort
R mol.toml --notopo --no-submit >/dev/null 2>&1
[[ $(grep -c -- '--notopo' mol_crest.sh) -ge 2 ]] || fail "--notopo not passed to both passes"

# 13. --ewin reaches the search and widens the cregen window
R mol.toml --ewin 12 --no-submit >/dev/null 2>&1
grep -q -- '--ewin 12' mol_crest.sh || fail "--ewin not passed to the search"
grep -q -- '-ewin 12' mol_crest.sh || fail "--ewin did not widen the cregen window"

# 14. a missing .xyz is skipped rather than half-submitted
cp mol.toml lonely.toml
out=$(R lonely.toml --no-submit 2>&1)
grep -q 'skip' <<<"$out" || fail "a .toml with no .xyz was not skipped: $out"
[[ ! -f lonely_crest.sh ]] || fail "a script was written for a missing .xyz"

# 15. without a recorded crest, it says so here instead of failing in the job
out=$(env CREST_CONF=/nonexistent "$RAW" mol.toml --no-submit 2>&1); rc=$?
[[ $rc -ne 0 ]] || fail "a missing crest path still exited 0"
grep -q 'crest' <<<"$out" || fail "unhelpful message for a missing crest: $out"

echo "PASS: all 15 checks"
