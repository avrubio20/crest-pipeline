# CREST conformer-search pipeline

Conformer ensembles from a structure, as a cluster job, on Slurm or UGE.

    prepcrest.py mol.xyz        build mol.toml, interactively
    runcrest.py  mol.toml       submit the search
    ls crest_conformers.xyz     the ensemble, when it lands

These are wrappers around [CREST](https://github.com/crest-lab/crest) 3.x and
xtb, which they do not install — clusters usually have both, and the installer
finds them.

**New here? Read [INSTALL.md](INSTALL.md).**

    ./install_crest.sh --prefix ~/crest --add-path

## Layout

    install_crest.sh  find crest and xtb, put the tools on an account
    runcrest.py       write and submit the job (Slurm or UGE)
    prepcrest.py      build a CREST 3.x TOML by answering questions
    test_runcrest.sh  15 checks, seconds, no scheduler needed
    examples/         butanol: a small, fast conformer search

**One copy of each tool, not one per machine.** `runcrest.py` detects the
scheduler and writes `#SBATCH` or `#$` accordingly; `--scheduler` overrides it.

## What the job does

Runs in node-local scratch and copies back the ensemble (`crest_best.xyz`,
`crest_conformers.xyz`, `crest_rotamers.xyz`, logs). Trajectories and inputs
stay behind. Scratch is deleted on success and **kept on failure**, and USR1
five minutes before the walltime kill triggers a copy-back so a timed-out
search still returns what it had.

Three things it does that are easy to get wrong by hand:

- **`OPENBLAS_CORETYPE=Haswell`.** CREST 3.0.2 statically links OpenBLAS with
  DYNAMIC_ARCH; on newer nodes it picks an AVX-512 kernel whose eigensolver
  corrupts memory. That is the GFN0 "double free" crash and the GFN2 trial-MD
  "did not converge" failure, both of them. Standalone xtb is unaffected.
- **cregen does not run on a crashed search.** A crash still leaves
  `crest_best.xyz` behind, and cregen reads it happily — reporting one
  conformer at 0.000 kcal/mol, "terminated normally", exit 0, every coordinate
  NaN. The exit code and the structure are both checked first.
- **A NaN ensemble is never copied back**, so a failed run cannot overwrite a
  good ensemble from a previous one.

## Config

`install_crest.sh` writes `~/.crest.conf`, and the tools read it:

| key | means |
|---|---|
| `bindir` | where the tools are |
| `crest` | the crest binary |
| `xtb_bin` | directory holding xtb |
| `xtb_path` | xtb's parameter directory (`XTBPATH`) |
| `scratch` | fast temporary space for the job |
| `scheduler` | `uge` or `slurm` |
| `uge_pe` | UGE parallel environment (default `shared`) |
| `uge_resources` | UGE node policy (default `arch=intel*`) |
| `uge_project` | UGE project to bill, if your site wants `-P` |

`CREST_CONF`, `CREST_BIN` override it for one run.

## Before changing anything

    bash test_runcrest.sh
