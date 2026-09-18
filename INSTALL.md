# Installing on a cluster, start to finish

This walks through a first install on UCLA's Hoffman2, which uses the UGE
scheduler (`qsub`). On a Slurm cluster everything is the same except the
monitoring commands, noted at the end.

## What you are installing

*CREST* searches for conformers: it runs a lot of short metadynamics with xtb,
collects the structures, and sorts them into an ensemble. It needs xtb to do
the actual energies, so you install two things, in this order:

1. **xtb, by hand.** You choose the build and where it goes — this installer
   never touches it. Use the build that supports `--gxtb` unless you have a
   reason not to.
2. **CREST**, which this installer downloads for you if you ask it to.

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

## Step 2b — install xtb yourself

**Already have xtb?** Skip the download. Find it (`which xtb`, or look where
you keep programs), run the two checks at the end of this section, and go on to
step 3 with its `bin` directory in hand.

Otherwise, download a release and unpack it where you keep programs:

    mkdir -p ~/project-houk/Programs
    cd ~/project-houk/Programs
    wget https://github.com/grimme-lab/xtb/releases/download/v6.7.1/xtb-6.7.1-linux-x86_64.tar.xz
    tar -xf xtb-6.7.1-linux-x86_64.tar.xz

That is the standard build. The **g-xTB build** is a separate download from the
same project and is the one to use if you will run `--gxtb` calculations; if
you were given a tarball for it, unpack that here instead. `install_crest.sh`
checks which one you ended up with and says so.

Then confirm it works, from that directory:

    ./xtb-6.7.1/bin/xtb --version           # prints a version
    ./xtb-6.7.1/bin/xtb --help | grep gxtb  # prints --gxtb if this is that build

**Remember that `bin` path** — `~/project-houk/Programs/xtb-6.7.1/bin` in this
example. It is the only thing step 4 needs from all of this. The installer
records where xtb is and the job script puts it on `PATH` for you.

Why you install this one by hand and not CREST: xtb comes in builds that differ
in what they can do, and which one you want is a decision about your chemistry,
not about the pipeline.

## Step 3 — check before installing

    ./install_crest.sh --check

Writes nothing, submits nothing. It looks for `qsub`, a working `crest`, a
working `xtb` (and whether that xtb knows `--gxtb`), xtb's parameter directory,
the two tools on your `PATH`, and it runs the test suite.

On a fresh account, expect `FAIL` on both tools, and on the test suite — none
of it exists yet, and step 4 is what creates it. What matters here is whether
**crest and xtb run**. If they do not, point at them directly:

    ./install_crest.sh --crest-bin /path/to/crest --xtb-bin /path/to/xtb/bin

## Step 4 — install

    ./install_crest.sh --prefix ~/crest --install-crest \
                       --xtb-bin ~/project-houk/Programs/xtb-6.7.1/bin \
                       --add-path

1. Downloads CREST 3.0.2 into `~/crest/opt/crest-3.0.2`.
2. Copies `runcrest.py`, `prepcrest.py` and the test suite into `~/crest/bin`.
3. Writes `~/.crest.conf` recording where crest, xtb and its parameters are,
   which scheduler this machine uses, and where scratch lives.
4. Adds `~/crest/bin` to your `PATH` via `~/.bashrc` (or `~/.cshrc` under tcsh).

Everything is a separate flag if you want the pieces apart:

| flag | means |
|---|---|
| `--example` | write `./crest_example/`. It also re-runs the install, which is harmless |
| `--prefix DIR` | everything under one directory |
| `--bindir DIR` | just the tools |
| `--crest-dir DIR` | where CREST itself goes |
| `--install-crest` | download it; leave it off if you already have one |
| `--crest-bin PATH` | a crest you already have, instead of downloading |
| `--crest-tarball F` | install from a local tarball, for a node with no network |
| `--xtb-bin DIR` | the `bin` from step 2b |
| `--shared` | make the install readable by your unix group |

So a group install is
`--prefix /u/project/<group>/crest --install-crest --shared`, and everyone else
needs only that `bin` on their `PATH`.

## Step 5 — reload and check again

    source ~/.bashrc
    ./install_crest.sh --check

Everything should be `ok`, ending with `Passed N/N checks.`

Two things that make it come back short of that:

- **`runcrest.py on PATH is /somewhere/else`** — you already had a copy of the
  tools, and it sits earlier on your `PATH` than the one you just installed.
  That older copy is what will run. Delete it, or install over it with
  `--bindir <that directory>`.
- **`runcrest.py does not run under ...`** — your `python3` is too old (it
  needs 3.7+). On Hoffman2 the bare login `python3` is 3.6.8; fix it with

      module load python/3.9.6

  If that is your situation, put that line in your `~/.bashrc` so you do not
  have to remember it every session. The jobs themselves do not need it — only
  `runcrest.py`, which runs on the login node when you submit.

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
| `xtb does not run` | you have not installed it, or `--xtb-bin` points at the wrong directory. Step 2b |
| `this xtb does not know --gxtb` | you installed a plain xtb build. Install the gxtb one, or put `require_gxtb = no` in your config |
| `no share/xtb beside ...` | xtb cannot find its parameters; point `xtb_path` at the right directory |
| `command not found: runcrest.py` | `PATH` line missing or shell not reloaded — step 5 |
| `ModuleNotFoundError: tomllib` or a syntax error | `python3` is older than 3.7 — `module load python/3.9.6` |
| `destination path 'crest-pipeline' already exists` | you cloned it before; `cd crest-pipeline && git pull` instead |
| `FAIL test_runcrest.sh` before installing | expected on a fresh account; step 4 installs the suite |
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
