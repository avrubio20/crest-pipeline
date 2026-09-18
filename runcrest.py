#!/usr/bin/env python3
"""
runcrest.py

Submit CREST conformer searches from <base>.toml + <base>.xyz, on Slurm or UGE.

    runcrest.py mol.toml                    one job, threads from the .toml
    runcrest.py *.toml                      one job each
    runcrest.py mol.toml -p 16 -m 32        override threads and memory
    runcrest.py mol.toml --dry-run          print the script, submit nothing

The job runs in node-local scratch and copies results back: crest_best.xyz,
the conformer and rotamer ensembles, logs. Trajectories and the inputs stay
behind. Scratch is deleted on success and kept on failure.

Paths to crest and xtb come from the config install_crest.sh writes
(~/.crest.conf, or CREST_CONF). --scheduler forces slurm or uge if detection
is wrong.

Two safety behaviours worth knowing, both of which cost real jobs to learn:

  * A crashed search still leaves crest_best.xyz on disk, and a following
    cregen pass reads it happily -- reporting one conformer at 0.000 kcal/mol
    and exiting 0, with every coordinate NaN. The search's exit code is checked
    before cregen runs, and the structure is checked for NaN.
  * Copy-back skips any .xyz containing NaN, so a failed run cannot overwrite
    a good ensemble from a previous one.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

DEFAULT_THREADS = 12
DEFAULT_MEM_PER_CORE = 4    # GB, when threads comes from -p or the default
TOML_MEM_PER_CORE = 2       # GB, when threads comes from the .toml
DEFAULT_TIME_H = 24

# What comes back from scratch, and what is left behind.
COPY_BACK = ('crest_best.xyz', 'crest_conformers.xyz', 'crest_rotamers.xyz',
             'crest_conformers.xyz.sorted', 'crest_ensemble.xyz', '*.log', '*.trj')
DO_NOT_COPY = ('{base}.toml', '{base}.xyz', 'ensemble_energies.log', '*energies',
               'crest_dynamics.trj')

UGE_RESOURCES = 'arch=intel*'
UGE_PE = 'shared'

SCHEDULERS = {
    'slurm': {
        'submit': 'sbatch',
        'job_id': '${SLURM_JOB_ID:-$$}',
        'submit_dir': '${SLURM_SUBMIT_DIR:-$PWD}',
        'threads_var': '${SLURM_CPUS_PER_TASK:-%d}',
        'scratch': '${SCRATCH:-/tmp}',
    },
    'uge': {
        'submit': 'qsub',
        'job_id': '${JOB_ID:-$$}',
        'submit_dir': '${SGE_O_WORKDIR:-$PWD}',
        'threads_var': '${NSLOTS:-%d}',
        'scratch': '${TMPDIR:-${SCRATCH:-/tmp}}',
    },
}


def config_path() -> Path:
    """CREST_CONF, else ~/.crest.conf, else the config beside the tools."""
    if os.environ.get('CREST_CONF'):
        return Path(os.environ['CREST_CONF'])
    personal = Path.home() / '.crest.conf'
    if personal.is_file():
        return personal
    shared = Path(__file__).resolve().parent.parent / 'etc/crest.conf'
    return shared if shared.is_file() else personal


CONFIG_PATH = config_path()


def load_config() -> dict:
    """`key = value`, with indented lines continuing the value above."""
    config, key = {}, None
    try:
        text = CONFIG_PATH.read_text()
    except FileNotFoundError:
        return config
    except OSError as exc:
        sys.exit(f'ERROR: cannot read {CONFIG_PATH}: {exc}')
    for line in text.splitlines():
        if not line.strip():
            key = None
            continue
        if line.lstrip().startswith('#'):
            continue
        if line[0].isspace() and key:
            config[key] += '\n' + line.strip()
        elif '=' in line:
            key, _, value = line.partition('=')
            key = key.strip()
            config[key] = value.strip()
    return config


def detect_scheduler() -> str | None:
    """Slurm or UGE, asked of the machine. None if neither is here."""
    if os.environ.get('SGE_ROOT') or submit_command('uge'):
        return 'uge'
    if submit_command('slurm'):
        return 'slurm'
    return None


def submit_command(scheduler: str) -> str | None:
    name = SCHEDULERS[scheduler]['submit']
    found = shutil.which(name)
    if found:
        return found
    if name != 'qsub':
        return None
    # qsub is off PATH in a non-interactive shell, so look where UGE puts it.
    root = os.environ.get('SGE_ROOT')
    if root:
        found = next(Path(root).glob('bin/*/qsub'), None)
        if found:
            return str(found)
    return next((c for c in ('/u/local/bin/qsub', '/usr/bin/qsub')
                 if Path(c).is_file()), None)


def binaries(config: dict) -> tuple[str, str, str]:
    """crest, the xtb bin directory, and XTBPATH."""
    crest = os.environ.get('CREST_BIN') or config.get('crest', '')
    if not crest:
        sys.exit("ERROR: where crest lives is not recorded. Run install_crest.sh, "
                 f'or write `crest = <path>` into {CONFIG_PATH}, '
                 'or export CREST_BIN.')
    return crest, config.get('xtb_bin', ''), config.get('xtb_path', '')


def hms(time_arg: str) -> str:
    return time_arg if ':' in time_arg else f'{int(time_arg):02d}:00:00'


def seconds(time_hms: str) -> int:
    h, m, s = (int(x) for x in time_hms.split(':'))
    return h * 3600 + m * 60 + s


def toml_threads(toml_file: str) -> int | None:
    """The 'threads' value from a CREST .toml, or None if absent/unusable."""
    try:
        with open(toml_file, 'rb') as fh:
            val = tomllib.load(fh).get('threads')
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f'[warn] could not read threads from {toml_file} ({exc}); '
              'using the default.')
        return None
    if val is None:
        return None
    if not isinstance(val, int) or isinstance(val, bool) or val < 1:
        print(f'[warn] {toml_file}: threads = {val!r} is not a positive integer; '
              'using the default.')
        return None
    return val


def directives(scheduler: str, base: str, nproc: int, mem_mb: int,
               time_hms: str, cfg: dict) -> str:
    if scheduler == 'slurm':
        lines = [f'#SBATCH --job-name={base}',
                 '#SBATCH --output=joblogs/cjoblog.%j',
                 '#SBATCH --ntasks=1',
                 f'#SBATCH --cpus-per-task={nproc}',
                 f'#SBATCH --mem={mem_mb}',
                 f'#SBATCH --time={time_hms}',
                 # USR1 five minutes early is the only warning a walltime kill gives.
                 '#SBATCH --signal=B:USR1@300']
        if cfg.get('account'):
            lines.append(f'#SBATCH -A {cfg["account"]}')
        if cfg.get('partition'):
            lines.append(f'#SBATCH -p {cfg["partition"]}')
        return '\n'.join(lines)

    total = seconds(time_hms)
    per_slot = -(-mem_mb // nproc)          # ceil: h_data is per slot
    lines = ['#$ -cwd', f'#$ -N {base}',
             '#$ -o joblogs/cjoblog.$JOB_ID', '#$ -j y',
             '#$ -notify',        # UGE sends USR1 at s_rt
             '#$ -r n',           # a restarted conformer search is not the same search
             f'#$ -l h_data={per_slot}M,h_rt={total},s_rt={max(60, total - 300)},'
             + (cfg.get('uge_resources') or UGE_RESOURCES)]
    if cfg.get('uge_project'):
        lines.append(f'#$ -P {cfg["uge_project"]}')
    lines.append(f'#$ -pe {cfg.get("uge_pe") or UGE_PE} {nproc}')
    return '\n'.join(lines)


def build_script(base: str, nproc: int, mem_mb: int, time_hms: str,
                 scheduler: str, cfg: dict, notopo: bool, extra: str) -> str:
    sched = SCHEDULERS[scheduler]
    crest, xtb_bin, xtb_path = binaries(cfg)
    topo = '--notopo' if notopo else ''
    scratch_root = cfg.get('scratch') or sched['scratch']
    copy_back = ' '.join(f'"{p}"' for p in COPY_BACK)
    do_not_copy = ' '.join(f'"{p.format(base=base)}"' for p in DO_NOT_COPY)
    xtb_lines = ''
    if xtb_bin:
        xtb_lines += f'export PATH="$PATH:{xtb_bin}"\n'
    if xtb_path:
        xtb_lines += f'export XTBPATH="{xtb_path}"\n'

    return f"""#!/bin/bash
# Generated by runcrest.py. {sched['submit']} {base}_crest.sh
{directives(scheduler, base, nproc, mem_mb, time_hms, cfg)}

# CREST 3.0.2 statically links OpenBLAS (DYNAMIC_ARCH). On newer nodes it picks
# the AVX-512 kernel, whose eigensolver corrupts memory -- the GFN0 "double
# free" crash and the GFN2 trial-MD "did not converge" failures are both this.
# Forcing a non-AVX-512 kernel fixes both. Standalone xtb is unaffected.
export OPENBLAS_CORETYPE=Haswell
# Parallelism is --T across the MTD workers; each worker's BLAS stays single
# threaded.
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OMP_MAX_ACTIVE_LEVELS=1
export OMP_STACKSIZE=4G
ulimit -s unlimited 2>/dev/null || true
{xtb_lines}
submitdir="{sched['submit_dir']}"
jobid="{sched['job_id']}"
threads="{sched['threads_var'] % nproc}"
tempdir="{scratch_root}/crest_{base}_$jobid"
start=$(date +%s)
cd "$submitdir" || exit 1
mkdir -p joblogs
echo "Job $jobid started on $(hostname) at $(date)"
echo "scratch: $tempdir"

[[ -f "$submitdir/{base}.toml" && -f "$submitdir/{base}.xyz" ]] || {{
  echo "ERROR: need both {base}.toml and {base}.xyz in $submitdir" >&2; exit 1; }}

COPY_BACK=( {copy_back} )
DO_NOT_COPY=( {do_not_copy} )
_skip() {{ local b="$1"; for x in "${{DO_NOT_COPY[@]}}"; do [[ "$b" == $x ]] && return 0; done; return 1; }}
copy_back() {{
  shopt -s nullglob
  for pat in "${{COPY_BACK[@]}}"; do
    for f in "$tempdir"/$pat; do
      [[ -f "$f" ]] || continue
      _skip "$(basename "$f")" && continue
      # A crashed search can leave an .xyz of all-NaN coordinates. Copying that
      # back would overwrite a good ensemble from a previous run, so it stays.
      if [[ "$f" == *.xyz ]] && grep -qi nan "$f"; then
        echo "[warn] not copying back $(basename "$f"): contains NaN (kept in $tempdir)" >&2
        continue
      fi
      cp -a "$f" "$submitdir/" 2>/dev/null || true
    done
  done
  shopt -u nullglob
}}
_on_exit() {{
  rc=$?
  copy_back
  end=$(date +%s)
  printf 'Job %s ended at %s (elapsed %02d:%02d:%02d, rc=%s)\\n' "$jobid" "$(date)" \\
    $(((end-start)/3600)) $(((end-start)%3600/60)) $(((end-start)%60)) "$rc"
  if [[ $rc -eq 0 ]]; then rm -rf "$tempdir"; else echo "scratch kept for debugging: $tempdir"; fi
}}
trap copy_back USR1          # five minutes before the walltime kill
trap 'exit 143' TERM
trap _on_exit EXIT

mkdir -p "$tempdir"
cp "$submitdir/{base}.toml" "$submitdir/{base}.xyz" "$tempdir/"
cd "$tempdir"

# --T is passed explicitly and equals what the scheduler gave us: CREST's CLI
# --T beats a `threads` key in the .toml, so leaving it off would let the .toml
# disagree with the allocation.
{crest} {base}.xyz --rthr 0.5 --T "$threads" --noreftopo {topo} {extra} --input {base}.toml
rc=$?
# Chained deliberately: a crashed search still leaves crest_best.xyz behind, and
# cregen reads it without complaint -- reporting one conformer at 0.000
# kcal/mol and exiting 0 with every coordinate NaN. Failing here makes that
# visible.
if [[ $rc -ne 0 ]]; then
  echo "ERROR: the CREST search exited $rc; not running cregen on its output." >&2
  exit $rc
fi
if [[ ! -s crest_best.xyz ]] || grep -qi nan crest_best.xyz; then
  echo "ERROR: crest_best.xyz is missing, empty, or NaN -- the search did not" >&2
  echo "       produce a usable structure, so cregen would only launder it." >&2
  exit 1
fi
{crest} crest_best.xyz -cregen crest_conformers.xyz -ewin {cfg.get('cregen_ewin', '4')} \\
    -ethr 0.31 -rthr 0.2 {topo}
"""


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__.split('Two safety')[0].strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter)

    p.add_argument('toml_files', nargs='+', help='CREST .toml input file(s)')

    res = p.add_argument_group('resources')
    res.add_argument('-p', type=int, help="threads; overrides a 'threads' key in "
                     f"the .toml (default: the .toml's, else {DEFAULT_THREADS})")
    res.add_argument('-m', type=int, help='memory in GB (default: '
                     f'{DEFAULT_MEM_PER_CORE}x threads, or {TOML_MEM_PER_CORE}x '
                     'when threads comes from the .toml)')
    res.add_argument('-t', default=str(DEFAULT_TIME_H),
                     help='walltime in hours or HH:MM:SS (default: 24)')

    samp = p.add_argument_group('sampling')
    samp.add_argument('--ewin', type=float,
                      help='energy window in kcal/mol for the search. Raise it '
                           '(e.g. 12) to keep more diverse, higher-energy '
                           'conformers -- worth it for NCI and H-bonded complexes.')
    samp.add_argument('--mdlen', type=float,
                      help='metadynamics length in ps; raise for more sampling')
    samp.add_argument('--v4', action='store_true',
                      help='the iMTD-sMTD workflow: more thorough than the default v3')
    samp.add_argument('--notopo', action='store_true',
                      help='disable CREGEN topology AND clash checks. Needed when '
                           'the species is two fragments -- an H in flight, an NCI '
                           'complex -- because the clash check otherwise discards '
                           'every structure and CREGEN dies on the empty ensemble. '
                           'You lose the filter that catches changed bonding, so '
                           'check the surviving topology yourself.')

    out = p.add_argument_group('scheduler and output')
    out.add_argument('--scheduler', choices=['slurm', 'uge', 'auto'], default='auto',
                     help='which directives to write (default: auto)')
    out.add_argument('--dry-run', action='store_true',
                     help='print the script; write nothing, submit nothing')
    out.add_argument('--no-submit', action='store_true',
                     help='write the script but do not submit it')
    return p.parse_args()


def resolve_resources(a, toml_file: str) -> tuple[int, int, str]:
    """(threads, memory GB, where it came from). -p/-m win, then the .toml."""
    from_toml = None if a.p else toml_threads(toml_file)
    if a.p:
        nproc, source = a.p, '-p'
    elif from_toml:
        nproc, source = from_toml, f'{os.path.basename(toml_file)} threads'
    else:
        nproc, source = DEFAULT_THREADS, 'default'

    if a.m:
        mem_gb = a.m
    elif from_toml:
        mem_gb = nproc * TOML_MEM_PER_CORE
    else:
        mem_gb = nproc * DEFAULT_MEM_PER_CORE
    return nproc, mem_gb, source


def main():
    a = parse_args()
    config = load_config()
    scheduler = a.scheduler
    if scheduler == 'auto':
        scheduler = detect_scheduler() or config.get('scheduler') or 'slurm'
    binaries(config)        # fail here, not inside the job
    time_hms = hms(a.t)

    extra = []
    if a.ewin:
        extra.append(f'--ewin {a.ewin}')
    if a.mdlen:
        extra.append(f'--mdlen {a.mdlen}')
    if a.v4:
        extra.append('--v4')
    if a.ewin:
        config = dict(config, cregen_ewin=f'{a.ewin:g}')

    for toml_file in a.toml_files:
        base = os.path.splitext(os.path.basename(toml_file))[0]
        if not (os.path.isfile(f'{base}.toml') and os.path.isfile(f'{base}.xyz')):
            print(f'[skip] need both {base}.toml and {base}.xyz')
            continue

        nproc, mem_gb, source = resolve_resources(a, f'{base}.toml')
        body = build_script(base, nproc, mem_gb * 1024, time_hms, scheduler,
                            config, a.notopo, ' '.join(extra))
        if a.dry_run:
            print(body)
            continue

        print(f'{base}: {nproc} threads ({source}), {mem_gb} GB, {scheduler}')
        os.makedirs('joblogs', exist_ok=True)   # the scheduler opens -o before the job runs
        script = Path(f'{base}_crest.sh')
        script.write_text(body)
        script.chmod(0o755)
        if a.no_submit:
            print(f'wrote {script} (not submitted)')
            continue

        submit = submit_command(scheduler)
        if submit is None:
            sys.exit(f'ERROR: no {SCHEDULERS[scheduler]["submit"]} on PATH. Use '
                     '--no-submit and submit by hand, or run this on a login node.')
        r = subprocess.run([submit, str(script)], capture_output=True, text=True)
        print(r.stdout.strip() if r.returncode == 0
              else f'[error] {base}: {r.stderr.strip()}')


if __name__ == '__main__':
    main()
