#!/usr/bin/env python3
"""
prepcrest.py — interactive builder for CREST 3.x TOML input files.
  prepcrest.py            fully interactive
  prepcrest.py file.xyz   skip the input-file prompt, use file.xyz
Pairs with runcrest.py.

Everything CREST-specific in here (solvent names, constraint types, atom
counts per constraint) was verified against crest 3.0.2 with --dry and with
throwaway single-points; see _selfcheck() at the bottom.
"""
import readline
import os
import sys

# Atomic numbers for the electron-parity guard (H through Lr).
_SYMBOLS = (
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co "
    "Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb "
    "Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re "
    "Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es "
    "Fm Md No Lr"
).split()
ATOMIC_NUMBERS = {sym: z for z, sym in enumerate(_SYMBOLS, start=1)}


def _warn(msg):
    """Report a real problem on stderr. Re-prompts just use print()."""
    print(msg, file=sys.stderr)


def read_symbols(xyz_path):
    """Element symbols from an .xyz, in file order. None on failure."""
    try:
        with open(xyz_path) as fh:
            n = int(fh.readline().split()[0])
            fh.readline()  # comment line
            syms = []
            for _ in range(n):
                # Strip trailing label digits ("Fe1" -> "Fe"). No first-letter
                # fallback: that used to read Fe as F and break the parity guard.
                sym = fh.readline().split()[0].rstrip("0123456789_").capitalize()
                ATOMIC_NUMBERS[sym]  # KeyError on anything we can't count
                syms.append(sym)
        if len(syms) != n:
            raise ValueError(f"header says {n} atoms, found {len(syms)}")
        return syms
    except (OSError, KeyError, ValueError, IndexError) as e:
        _warn(f"[note] Could not parse {xyz_path} ({e}); "
              "skipping the electron-parity and atom-index checks.")
        return None


def count_electrons(symbols):
    """Neutral electron count for a list of element symbols."""
    return sum(ATOMIC_NUMBERS[s] for s in symbols)


# ALPB solvent names accepted by crest 3.0.2 / tblite. Every name here was
# checked by running a single-point and confirming the energy actually shifts
# off the gas-phase value: an unrecognized name is SILENTLY ignored by CREST
# (it prints "Solvent: <name>", reports SUCCESS, and runs in vacuum). That is
# why wet octanol must be spelled "woctanol" -- "Octanol (wet)" was in this
# list for a while and quietly produced gas-phase numbers.
valid_solvents = [
    "Acetone", "Acetonitrile", "Aniline", "Benzaldehyde", "Benzene", "CH2Cl2",
    "CHCl3", "CS2", "Dioxane", "DMF", "DMSO", "Ether", "Ethylacetate",
    "Furane", "Hexadecane", "Hexane", "Methanol", "Nitromethane", "Octanol",
    "woctanol", "Phenol", "Toluene", "THF", "Water"
]

# Constraint types, and how many atoms each one takes. Verified against
# crest 3.0.2: "distance" and "freeze" are rejected as constraint *types*
# ("unrecognized ARGUMENT"), and a [[calculation.constraint]] block with no
# type at all parses but is silently ignored -- so "freeze" is handled
# separately below via the [calculation] freeze key, which CREST does accept.
CONSTRAINT_ATOM_COUNT = {"bond": 2, "angle": 3, "dihedral": 4}
allowed_constraint_types = list(CONSTRAINT_ATOM_COUNT) + ["freeze"]

# Allowed CREST runtypes. "nci-mtd" is the TOML equivalent of the --nci flag
# (NCI-MTD sampling + an auto-generated ellipsoid wall potential).
allowed_runtypes = ["imtd-gc", "nci-mtd"]

# Enable tab-completion for general input
readline.parse_and_bind("tab: complete")
readline.set_completer_delims(" \t\n;")


def _list_completer(options):
    def completer(text, state):
        hits = [t for t in options if t.startswith(text)]
        return hits[state] if state < len(hits) else None
    return completer


def display_solvents_in_columns(solvents, num_columns=3):
    """Display solvents in a compact, column-based format."""
    max_length = max(len(solvent) for solvent in solvents) + 2  # alignment padding
    for i in range(0, len(solvents), num_columns):
        row = solvents[i:i + num_columns]
        print("".join(solvent.ljust(max_length) for solvent in row))


def create_toml_file(cli_input=None):
    # Function to autofill file names in the current directory
    def file_completer(text, state):
        files = [f for f in os.listdir('.') if f.startswith(text)]
        return files[state] if state < len(files) else None

    readline.set_completer(file_completer)

    # Validate a candidate .xyz path; return an error string, or None if OK.
    def _xyz_error(name):
        if not name.endswith(".xyz"):
            return "Error: The input file name must end with '.xyz'."
        if not os.path.isfile(name):
            return f"Error: File '{name}' does not exist."
        return None

    # Get the input file name: use the command-line argument if one was given and
    # valid (skips the prompt); otherwise ask interactively as before.
    input_name = None
    if cli_input:
        err = _xyz_error(cli_input.strip())
        if err:
            print(err + " Falling back to prompt.")
        else:
            input_name = cli_input.strip()
            print(f"Using input file: {input_name}")
    while input_name is None:
        candidate = input("Enter the input file name (e.g., molecule.xyz): ").strip()
        err = _xyz_error(candidate)
        if err:
            print(err + " Please try again.")
            continue
        input_name = candidate

    # Strip the extension once, from the right, and reuse it for both the TOML
    # and the elog name. A plain .replace() would also hit ".xyz" occurring
    # earlier in the path.
    stem = input_name.rsplit(".xyz", 1)[0]
    toml_file_name = stem + ".toml"

    symbols = read_symbols(input_name)
    natoms = len(symbols) if symbols else None

    # Get the runtype, validate against the allowed list (default: imtd-gc).
    default_runtype = "imtd-gc"
    readline.set_completer(_list_completer(allowed_runtypes))
    while True:
        runtype = input(
            f"Enter the runtype ({', '.join(allowed_runtypes)}; default: {default_runtype}): "
        ).strip().lower() or default_runtype
        if runtype in allowed_runtypes:
            break
        print(f"Error: '{runtype}' is not a valid runtype. "
              f"Please choose from: {', '.join(allowed_runtypes)}.")
    readline.set_completer(file_completer)

    # Default values
    default_method = "gfn2"
    default_uhf = 0
    default_chrg = 0

    # Method is free-text (CREST accepts gfn2, gfn2//gfnff, gfnff, ...), so an
    # empty answer just takes the default rather than being re-prompted.
    method = input(f"Enter the method (default: {default_method}): ").strip() or default_method

    # Get the UHF value: an integer, and non-negative (uhf counts unpaired
    # electrons, so it cannot be negative).
    while True:
        try:
            uhf = int(input(f"Enter the UHF value (default: {default_uhf}): ").strip()
                      or str(default_uhf))
        except ValueError:
            print("Error: UHF value must be an integer. Please try again.")
            continue
        if uhf < 0:
            print("Error: uhf is the number of unpaired electrons and cannot be "
                  "negative (0 singlet, 1 doublet, 2 triplet). Please try again.")
            continue
        break

    # Get the charge value, validate as integer
    while True:
        try:
            chrg = int(input(f"Enter the charge (default: {default_chrg}): ").strip()
                       or str(default_chrg))
            break
        except ValueError:
            print("Error: Charge value must be an integer. Please try again.")

    # Electron-parity guard: n_electrons and uhf must share parity, else CREST crashes.
    if symbols:
        n_elec = count_electrons(symbols) - chrg
        if (n_elec - uhf) % 2 != 0:
            # uhf is the number of UNPAIRED electrons (2S = mult - 1), not the
            # multiplicity, so it must match the parity of n_elec.
            suggested = uhf - 1 if uhf > 0 else uhf + 1
            parity = "odd" if n_elec % 2 else "even"
            print(f"\n[WARNING] {n_elec} electrons (charge {chrg:+d}) with uhf={uhf} is an "
                  f"impossible spin state — parity mismatch.")
            print(f"          An {parity}-electron system needs an {parity} uhf "
                  f"(uhf = unpaired electrons: 0 singlet, 1 doublet, 2 triplet).")
            ans = input(f"          Set uhf = {suggested} instead? [Y/n]: ").strip().lower()
            if ans in ("", "y", "yes"):
                uhf = suggested
                print(f"          -> uhf set to {uhf}.")
            else:
                print(f"          -> keeping uhf = {uhf} (CREST will likely crash).")

    # Ask for threads; if no input is provided, the threads line is omitted.
    threads = None
    threads_input = input("Enter the number of threads (press Enter to skip): ").strip()
    if threads_input:
        try:
            threads = int(threads_input)
            if threads < 1:
                print("Threads must be >= 1. Skipping threads.")
                threads = None
        except ValueError:
            print("Invalid input for threads. Skipping threads.")
            threads = None

    # Ask if the user wants to use a solvation model
    alpb = None
    use_model = input("Do you want to use a solvation model? (y/n): ").strip().lower()
    if use_model in ("y", "yes"):
        print("Available solvents ('woctanol' is wet octanol):")
        display_solvents_in_columns(valid_solvents, num_columns=3)
        readline.set_completer(_list_completer(valid_solvents))
        while True:
            solvation_choice = input("Enter a solvent: ").strip()
            # Exact match only. CREST silently runs gas-phase on an unknown
            # solvent name, so a typo here would never surface at runtime.
            if solvation_choice in valid_solvents:
                alpb = solvation_choice
                break
            print(f"Error: '{solvation_choice}' is not a valid solvent. "
                  "Please choose from the list.")
        readline.set_completer(file_completer)
    else:
        print("No solvation model will be used.")

    # Ask if the user wants to add constraints. Collected before anything is
    # written, because frozen atoms belong in the [calculation] block.
    constraints = []   # list of (fc, type, [atoms])
    freeze_atoms = []
    add_constraints = input("Would you like to add constraints? (y/n): ").strip().lower()
    if add_constraints in ("y", "yes"):
        while True:
            try:
                num_constraints = int(input("How many constraints will you add? ").strip())
            except ValueError:
                print("Error: Please enter a valid integer for the number of constraints.")
                continue
            if num_constraints < 1:
                print("Error: Please enter a positive number of constraints.")
                continue
            break

        for i in range(1, num_constraints + 1):
            print(f"\nConstraint {i}:")
            # Constraint type first: it sets how many atoms are expected.
            readline.set_completer(_list_completer(allowed_constraint_types))
            while True:
                constraint_type = input(
                    f"type of constraint ({', '.join(allowed_constraint_types)}): "
                ).strip().lower()
                if constraint_type == "atoms":
                    # Old spelling of this option. It used to emit a typeless
                    # [[calculation.constraint]] block, which CREST parses and
                    # then ignores; "freeze" is the behavior that was meant.
                    print("  ('atoms' is now spelled 'freeze' — using freeze.)")
                    constraint_type = "freeze"
                if constraint_type in allowed_constraint_types:
                    break
                print(f"Error: '{constraint_type}' is not a valid constraint type. "
                      f"Please enter one of: {', '.join(allowed_constraint_types)}.")
            readline.set_completer(file_completer)

            # Force constant: only meaningful for the restraint types. CREST
            # takes no fc for frozen atoms.
            fc = None
            if constraint_type != "freeze":
                while True:
                    fc_input = input("force constant (default 0.8): ").strip()
                    if fc_input == "":
                        fc = 0.8
                        break
                    try:
                        fc = float(fc_input)
                        break
                    except ValueError:
                        print("Invalid input for force constant. Please enter a numeric value.")

            # Atoms: 1-based indices, space separated. Validated for count and
            # for range -- CREST accepts out-of-range indices (even 0 and
            # negatives) without complaint, so a typo would otherwise pass
            # straight into the run.
            want = CONSTRAINT_ATOM_COUNT.get(constraint_type)
            prompt = "atoms (separated by spaces"
            prompt += f", {want} expected): " if want else "): "
            while True:
                try:
                    atoms_list = [int(a) for a in input(prompt).split()]
                except ValueError:
                    print("Invalid atom input. Please enter integers separated by spaces.")
                    continue
                if not atoms_list:
                    print("Error: no atoms provided.")
                    continue
                if want and len(atoms_list) != want:
                    print(f"Error: a {constraint_type} constraint takes exactly {want} "
                          f"atoms, got {len(atoms_list)}. CREST would abort on this.")
                    continue
                bad = [a for a in atoms_list if a < 1 or (natoms and a > natoms)]
                if bad:
                    limit = f"1-{natoms}" if natoms else "1 or greater"
                    print(f"Error: atom index/indices {bad} out of range ({limit}). "
                          "CREST does not check this, so it would run with a bad "
                          "constraint. Please try again.")
                    continue
                if len(set(atoms_list)) != len(atoms_list):
                    print("Error: repeated atom index in one constraint. Please try again.")
                    continue
                break

            if constraint_type == "freeze":
                freeze_atoms.extend(atoms_list)
            else:
                constraints.append((fc, constraint_type, atoms_list))

    # Assemble the TOML.
    toml_content = f'input = "{input_name}"\n'
    toml_content += f'runtype = "{runtype}"\n'
    if threads is not None:
        toml_content += f"threads = {threads}\n"
    toml_content += "\n"
    toml_content += "[calculation]\n"
    toml_content += f'elog = "{stem}.log"\n'
    if freeze_atoms:
        frozen = sorted(set(freeze_atoms))
        toml_content += f'freeze = [{",".join(str(a) for a in frozen)}]\n'
    toml_content += "\n"
    toml_content += "[[calculation.level]]\n"
    toml_content += f'method = "{method}"\n'
    toml_content += f"uhf = {uhf}\n"
    toml_content += f"chrg = {chrg}\n"
    if alpb:
        toml_content += f'alpb = "{alpb}"\n'
    for fc, ctype, atoms_list in constraints:
        toml_content += "\n[[calculation.constraint]]\n"
        toml_content += f"fc = {fc}\n"
        toml_content += f'type = "{ctype}"\n'
        toml_content += f'atoms = [{",".join(str(a) for a in atoms_list)}]\n'

    # Don't clobber an existing input file without being asked to.
    if os.path.exists(toml_file_name):
        ans = input(f"{toml_file_name} already exists. Overwrite? [y/N]: ").strip().lower()
        if ans not in ("y", "yes"):
            print("Aborted; nothing written.")
            return
    with open(toml_file_name, "w") as f:
        f.write(toml_content)

    print(f"TOML file created successfully: {toml_file_name}")


def _selfcheck():
    """Run: python3 -c 'import prepcrest; prepcrest._selfcheck()'"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".xyz", delete=False) as fh:
        fh.write("3\ncomment\nFe 0 0 0\nH1 0 0 1\nCl 0 0 2\n")
        path = fh.name
    try:
        syms = read_symbols(path)
        assert syms == ["Fe", "H", "Cl"], syms
        # 26 (Fe, not F=9) + 1 (H1 label stripped) + 17
        assert count_electrons(syms) == 44, count_electrons(syms)
    finally:
        os.unlink(path)

    assert ATOMIC_NUMBERS["Fe"] == 26 and ATOMIC_NUMBERS["U"] == 92

    # Parity: uhf must match the parity of the electron count, and the
    # suggestion must land on a state that is actually reachable.
    def suggest(n_elec, uhf):
        assert (n_elec - uhf) % 2 != 0, "only called on a mismatch"
        return uhf - 1 if uhf > 0 else uhf + 1
    assert (355 - 1) % 2 == 0                 # the Fe-heme MHAT TS: doublet is fine
    assert suggest(354, 1) == 0               # even electrons -> singlet, not triplet
    assert suggest(355, 0) == 1               # odd electrons -> doublet

    # CREST-verified facts this script depends on.
    assert CONSTRAINT_ATOM_COUNT == {"bond": 2, "angle": 3, "dihedral": 4}
    assert "distance" not in allowed_constraint_types   # rejected by crest 3.0.2
    assert "atoms" not in allowed_constraint_types      # rejected as a type
    assert "Octanol (wet)" not in valid_solvents        # silently runs gas-phase
    assert "woctanol" in valid_solvents
    print("prepcrest selfcheck OK")


if __name__ == "__main__":
    cli_xyz = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        create_toml_file(cli_xyz)
    except (EOFError, KeyboardInterrupt):
        # Ctrl-C / Ctrl-D at a prompt: quit quietly instead of dumping a traceback.
        print("\nAborted; nothing written.")
        sys.exit(130)
