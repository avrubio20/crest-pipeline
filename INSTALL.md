# Installing on a cluster, start to finish

This walks through a first install on UCLA's Hoffman2, which uses the UGE
scheduler (`qsub`). On a Slurm cluster everything is the same except the
monitoring commands, noted at the end.

## What you are installing

*CREST* searches for conformers: it runs a lot of short metadynamics with xtb,
collects the structures, and sorts them into an ensemble. It and xtb are
already on most clusters — this does not download them.

*These scripts* are the layer around it: building the input file, writing the
submission script, running in scratch and bringing the right files back.

## Step 1 — log in

    ssh <your-user>@hoffman2.idre.ucla.edu

**Stay logged in and type at the prompt.** Running commands through
`ssh host 'command'` gives you a stripped-down shell where modules and
schedulers often are not found.

## Step 2 — get the code

    git clone https://github.com/avrubio20/crest-pipeline.git
    cd crest-pipeline

## Step 3 — check before installing

    ./install_crest.sh --check

Writes nothing, submits nothing. It looks for `qsub`, a working `crest`, a
working `xtb` (and whether that xtb knows `--gxtb`), xtb's parameter directory,
the two tools on your `PATH`, and it runs the test suite.

On a fresh account the tools will fail — that is step 4. What matters here is
whether **crest and xtb run**. If they do not, load the module that provides
them, or point at them directly:

    ./install_crest.sh --crest-bin /path/to/crest --xtb-bin /path/to/xtb/bin

## Step 4 — install

    ./install_crest.sh --prefix ~/crest --add-path

1. Copies `runcrest.py`, `prepcrest.py` and the test suite into `~/crest/bin`.
2. Writes `~/.crest.conf` recording where crest, xtb and its parameters are,
   which scheduler this machine uses, and where scratch lives.
3. Adds `~/crest/bin` to your `PATH` via `~/.bashrc` (or `~/.cshrc` under tcsh).

Put it anywhere you can write: `--prefix /u/project/<group>/crest --shared`
installs once for a whole group, and everyone else needs only that `bin` on
their `PATH`.

## Step 5 — reload and check again

    source ~/.bashrc
    ./install_crest.sh --check

Everything should be `ok`, ending with `Passed N/N checks.`

## Step 6 — a real search, on the included example

    ./install_crest.sh --example
    cd crest_example
    runcrest.py butanol.toml

That submits. Butanol is small and has few rotatable bonds, so it finishes
quickly. Watch it with `qstat -u $USER`, and when it is gone:

    ls crest_conformers.xyz crest_best.xyz
    head -1 crest_conformers.xyz          # atom count of the first structure

`crest_conformers.xyz` is the ensemble, lowest energy first;
`crest_best.xyz` is that lowest structure on its own.

If it fails, the job log in `joblogs/` names the reason, and scratch is kept —
the log prints the path.

## Step 7 — your own molecule

    prepcrest.py mol.xyz

This asks questions — method, charge, multiplicity, solvent, any constraints —
and writes `mol.toml` beside your `mol.xyz`. Then:

    runcrest.py mol.toml

Useful options, all with sensible defaults:

| flag | means |
|---|---|
| `-p` | threads. Default: the `threads` key in the .toml |
| `-m` | memory in GB. Default: 2 GB per thread from the .toml, 4 GB with `-p` |
| `-t` | walltime, hours or HH:MM:SS (default 24) |
| `--ewin 12` | keep higher-energy conformers — worth it for NCI and H-bonded complexes |
| `--v4` | the more thorough iMTD-sMTD workflow |
| `--notopo` | for two-fragment species: an H in flight, an NCI complex |
| `--dry-run` | print the job script, submit nothing |

**When you need `--notopo`:** if your species is really two fragments, CREGEN's
clash check discards every structure and then dies reading the empty ensemble
it just wrote. `--notopo` turns that check off. You lose the filter that
catches structures whose bonding changed during the search, so check the
surviving topology yourself.

## When something goes wrong

| what you see | what it means |
|---|---|
| `crest does not run` | not on PATH and not where the installer looks — pass `--crest-bin` |
| `xtb does not run` | same, `--xtb-bin` — and CREST is useless without it |
| `no share/xtb beside ...` | xtb cannot find its parameters; point `xtb_path` at the right directory |
| `command not found: runcrest.py` | `PATH` line missing or shell not reloaded — step 5 |
| `[skip] need both X.toml and X.xyz` | they must sit together in the directory you submit from |
| `the CREST search exited N` | the search itself failed; scratch is kept, and the log says where |
| `crest_best.xyz is missing, empty, or NaN` | the search produced nothing usable. Often the OpenBLAS issue on a node type CREST mishandles, or a bad starting structure |

## On a Slurm cluster instead

Everything is the same except `qstat -u $USER` becomes `squeue -u $USER`, and
`qsub` becomes `sbatch`. `runcrest.py` works out which to write by itself.

## Uninstalling

    rm -rf ~/crest        # or whatever you gave --prefix
    rm -f ~/.crest.conf

and delete the `PATH` line from `~/.bashrc`. crest and xtb themselves were
never touched — they were already on the machine.
