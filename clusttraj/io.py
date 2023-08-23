from openbabel import pybel
from openbabel import openbabel
from scipy.spatial.distance import squareform
import os
import sys
import argparse
import numpy as np
import rmsd
import logging
from typing import Callable
from dataclasses import dataclass

try:
    import qml

    has_qml = True
except ImportError:
    has_qml = False


@dataclass
class ClustOptions:
    trajfile: str = None
    min_rmsd: float = None

    n_workers: int = None

    method: str = None
    reorder_alg_name: str = None
    reorder_alg: Callable[
        [np.ndarray, np.ndarray, np.ndarray, np.ndarray], np.ndarray
    ] = None
    out_conf_fmt: str = None

    reorder: bool = None
    exclusions: bool = None
    no_hydrogen: bool = None
    input_distmat: bool = None
    save_confs: bool = None
    plot: bool = None
    opt_order: bool = None

    distmat_name: str = None
    out_clust_name: str = None
    evo_name: str = None
    mds_name: str = None
    dendrogram_name: str = None
    out_conf_name: str = None
    summary_name: str = None

    solute_natoms: int = None

    reorder_excl: np.ndarray = None

    def __str__(self):
        return_str = "\nFull command: " + " ".join(sys.argv)

        # main parameters
        return_str += f"\n\nClusterized from trajectory file: {self.trajfile}\n"
        return_str += f"Method: {self.method}\nRMSD criterion: {self.min_rmsd}\n"
        return_str += f"Ignoring hydrogens?: {self.no_hydrogen}\n"

        # reordering options
        if self.reorder:
            if self.solute_natoms:
                return_str += "\nUsing solute-solvent reordering\n"
                return_str += f"Number of solute atoms: {self.solute_natoms}\n"
            else:
                return_str += "\nReordering all atom at the same time\n"

            return_str += f"Reordering algorithm: {self.reorder_alg_name}\n"

            if self.exclusions:
                exclusions_str = ""
                for val in args.reorder_exclusions:
                    exclusions_str += "%d " % val
                return_str += f"Atoms that weren't considered in the reordering: {exclusions_str.strip()}\n"

        # write file names
        if self.input_distmat:
            return_str += f"\nDistance matrix was read from: {self.distmat_name}\n"
        else:
            return_str += f"\nDistance matrix was written in: {self.distmat_name}\n"

        return_str += f"The classification of each configuration was written in: {self.out_clust_name}\n"
        if self.save_confs:
            return_str += f"\nThe superposed structures for each cluster were saved at: {self.out_conf_name}\n"
        if self.plot:
            return_str += f"\nPlotting the dendrogram to: {self.dendrogram_name}\n"
            return_str += (
                f"Plotting the multidimensional scaling to 2D to: {self.mds_name}\n"
            )
            return_str += f"Plotting the evolution of the classification with the trajectory to: {self.evo_name}\n\n"

        return return_str


def setup_logger():
    logformat = " %(levelname)-8s [%(filename)s:%(lineno)d] <%(funcName)s> {rank %(rank)d/%(size)d} %(message)s"
    date_format = "%(asctime)s"
    formatter = logging.Formatter(fmt=date_format + logformat)
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.setFormatter(formatter)


def check_positive(value):
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError("%s is an invalid positive int value" % value)
    return ivalue


def extant_file(x):
    """
    'Type' for argparse - checks that file exists but does not open.
    From https://stackoverflow.com/a/11541495
    """
    if not os.path.exists(x):
        raise argparse.ArgumentTypeError(f"{x} does not exist")
    return x


def configure_runtime(args_in):
    parser = argparse.ArgumentParser(
        description="Run a clustering analysis on a trajectory based on the minimal RMSD obtained with a Kabsch superposition."
    )

    parser.add_argument(
        "trajectory_file",
        type=extant_file,
        help="path to the trajectory containing the conformations to be classified",
    )
    parser.add_argument(
        "min_rmsd",
        type=float,
        help="value of RMSD used to classify structures as similar",
    )
    parser.add_argument(
        "-f",
        "--force-overwrite",
        dest="force",
        action="store_true",
        help="force overwriting the files",
    )
    parser.add_argument(
        "-np",
        "--nprocesses",
        metavar="NPROCS",
        type=check_positive,
        default=4,
        help="defines the number of processes used to compute the distance matrix and multidimensional representation (default = 4)",
    )
    parser.add_argument(
        "-n",
        "--no-hydrogen",
        action="store_true",
        help="ignore hydrogens when doing the Kabsch superposition and calculating the RMSD",
    )
    parser.add_argument(
        "-p",
        "--plot",
        action="store_true",
        help="enable the multidimensional scaling and dendrogram plot saving the figures in pdf format (filenames use the same basename of the -oc option)",
    )
    parser.add_argument(
        "-m",
        "--method",
        metavar="METHOD",
        default="average",
        help="method used for clustering (see valid methods at https://docs.scipy.org/doc/scipy/reference/generated/scipy.cluster.hierarchy.linkage.html) (default: average)",
    )
    parser.add_argument(
        "-cc",
        "--clusters-configurations",
        metavar="EXTENSION",
        help="save superposed configurations for each cluster in EXTENSION format",
    )
    parser.add_argument(
        "-oc",
        "--outputclusters",
        default="clusters.dat",
        metavar="FILE",
        help="file to store the clusters (default: clusters.dat)",
    )
    parser.add_argument(
        "-e",
        "--reorder",
        action="store_true",
        help="reorder atoms of molecules to lower the RMSD",
    )
    parser.add_argument(
        "-eex",
        "--reorder-exclusions",
        metavar="EXCLUDED ATOMS",
        nargs="+",
        type=check_positive,
        help="list of atoms that are ignored when reordering",
    )
    parser.add_argument(
        "--reorder-alg",
        action="store",
        default="qml",
        metavar="METHOD",
        help="select which reorder algorithm to use; hungarian, brute, distance, qml (default). Warning: brute is VERY slow)",
    )
    parser.add_argument(
        "-ns",
        "--natoms-solute",
        metavar="NATOMS",
        type=check_positive,
        help="number of solute atoms, to ignore these atoms in the reordering process",
    )
    parser.add_argument(
        "-odl",
        "--optimal-ordering",
        action="store_true",
        help="use optimal ordering in linkage (can be slow for large trees, and only useful for dendrogram visualization)",
    )

    io_group = parser.add_mutually_exclusive_group()
    io_group.add_argument(
        "-i",
        "--input",
        type=extant_file,
        metavar="FILE",
        help="file containing input distance matrix in condensed form (.npy format)",
    )
    io_group.add_argument(
        "-od",
        "--outputdistmat",
        metavar="FILE",
        default="distmat.npy",
        help="file to store distance matrix in condensed form (default: distmat.npy)",
    )

    if len(sys.argv) == 0:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args(args_in)

    # setup the logger
    setup_logger()

    # check input consistency
    if args.method not in [
        "single",
        "complete",
        "average",
        "weighted",
        "centroid",
        "median",
        "ward",
    ]:
        parser.error(f"The method you selected with -m ({args.method}) is not valid.")

    if args.reorder_alg not in ["hungarian", "brute", "distance", "qml"]:
        parser.error(
            f"The reorder method you selected with --reorder-method ({args.reorder_alg}) is not valid."
        )

    if (args.reorder_alg == "qml") and (not has_qml):
        parser.error(
            "You must have the development branch of qml installed in order to use it as a reorder method."
        )

    if args.clusters_configurations:
        if args.clusters_configurations not in [
            "acr",
            "adf",
            "adfout",
            "alc",
            "arc",
            "bgf",
            "box",
            "bs",
            "c3d1",
            "c3d2",
            "cac",
            "caccrt",
            "cache",
            "cacint",
            "can",
            "car",
            "ccc",
            "cdx",
            "cdxml",
            "cht",
            "cif",
            "ck",
            "cml",
            "cmlr",
            "com",
            "copy",
            "crk2d",
            "crk3d",
            "csr",
            "cssr",
            "ct",
            "cub",
            "cube",
            "dmol",
            "dx",
            "ent",
            "fa",
            "fasta",
            "fch",
            "fchk",
            "fck",
            "feat",
            "fh",
            "fix",
            "fpt",
            "fract",
            "fs",
            "fsa",
            "g03",
            "g92",
            "g94",
            "g98",
            "gal",
            "gam",
            "gamin",
            "gamout",
            "gau",
            "gjc",
            "gjf",
            "gpr",
            "gr96",
            "gukin",
            "gukout",
            "gzmat",
            "hin",
            "inchi",
            "inp",
            "ins",
            "jin",
            "jout",
            "mcdl",
            "mcif",
            "mdl",
            "ml2",
            "mmcif",
            "mmd",
            "mmod",
            "mol",
            "mol2",
            "molden",
            "molreport",
            "moo",
            "mop",
            "mopcrt",
            "mopin",
            "mopout",
            "mpc",
            "mpd",
            "mpqc",
            "mpqcin",
            "msi",
            "msms",
            "nw",
            "nwo",
            "outmol",
            "pc",
            "pcm",
            "pdb",
            "png",
            "pov",
            "pqr",
            "pqs",
            "prep",
            "qcin",
            "qcout",
            "report",
            "res",
            "rsmi",
            "rxn",
            "sd",
            "sdf",
            "smi",
            "smiles",
            "sy2",
            "t41",
            "tdd",
            "test",
            "therm",
            "tmol",
            "txt",
            "txyz",
            "unixyz",
            "vmol",
            "xed",
            "xml",
            "xyz",
            "yob",
            "zin",
        ]:
            parser.error(
                f"The format you selected to save the clustered superposed configurations ({args.clusters_configurations}) is not valid."
            )

    if args.reorder_exclusions and args.no_hydrogen:
        parser.error(
            "You cannot use --no-hydrogen and reorder exclusions with -eex at the same time"
        )

    if not args.reorder and args.reorder_exclusions:
        logging.warning(
            "The list of atoms to exclude for reordering only makes sense if reordering is enabled. Ignoring the list."
        )

    return parse_args(args)


def parse_args(args):
    """
    Parse all the information from the argument parser, storing
    in the ClustOptions class.

    Define file names and set the pointers to the correct functions.
    """
    options_dict = {}

    basenameout = os.path.splitext(args.outputclusters)[0]

    if len(os.path.splitext(args.outputclusters)[1]) == 0:
        options_dict["out_clust_name"] = args.outputclusters + ".dat"
    else:
        options_dict["out_clust_name"] = args.outputclusters

    if args.natoms_solute and not args.reorder:
        logging.warning(
            "Specifying the number of solute atoms is only useful for the reordering algorithms, ignoring the number of solute atoms."
        )
        options_dict["solute_natoms"] = None
    else:
        options_dict["solute_natoms"] = args.natoms_solute

    if args.reorder_exclusions:
        options_dict["reorder_excl"] = np.asarray(
            [x - 1 for x in args.reorder_exclusions], np.int32
        )
        options_dict["exclusions"] = True
    else:
        options_dict["reorder_excl"] = np.asarray([], np.int32)
        options_dict["exclusions"] = False

    options_dict["reorder_alg_name"] = args.reorder_alg

    if args.reorder_alg == "hungarian":
        options_dict["reorder_alg"] = rmsd.reorder_hungarian
    elif args.reorder_alg == "distance":
        options_dict["reorder_alg"] = rmsd.reorder_distance
    elif args.reorder_alg == "brute":
        options_dict["reorder_alg"] = rmsd.reorder_brute
    elif args.reorder_alg == "qml":
        options_dict["reorder_alg"] = rmsd.reorder_similarity

    if not args.reorder:
        options_dict["reorder_alg"] = None
        options_dict["reorder"] = False
    else:
        options_dict["reorder"] = True

    if not args.input:
        options_dict["input_distmat"] = False

        if os.path.exists(args.outputdistmat) and not args.force:
            raise AssertionError(
                f"File {args.outputdistmat} already exists, specify a new filename with the -od command option or use the -f option. If you are trying to read the distance matrix from a file, use the -i option."
            )
        else:
            options_dict["distmat_name"] = args.outputdistmat
    else:
        options_dict["input_distmat"] = True
        options_dict["distmat_name"] = args.input

    if os.path.exists(args.outputclusters) and not args.force:
        raise AssertionError(
            f"File {args.outputclusters} already exists, specify a new filename with the -oc command option or use the -f option."
        )
    else:
        options_dict["out_clust_name"] = args.outputclusters
        options_dict["summary_name"] = basenameout + ".log"

    if args.clusters_configurations:
        options_dict["save_confs"] = True
        options_dict["out_conf_name"] = basenameout + "_confs"
        options_dict["out_conf_fmt"] = args.clusters_configurations
    else:
        options_dict["save_confs"] = False

    if args.plot:
        options_dict["plot"] = True
        options_dict["evo_name"] = basenameout + "_evo.pdf"
        options_dict["dendrogram_name"] = basenameout + "_dendrogram.pdf"
        options_dict["mds_name"] = basenameout + ".pdf"
    else:
        options_dict["plot"] = False

    options_dict["trajfile"] = args.trajectory_file
    options_dict["min_rmsd"] = args.min_rmsd
    options_dict["method"] = args.method
    options_dict["n_workers"] = args.nprocesses
    options_dict["no_hydrogen"] = args.no_hydrogen
    options_dict["opt_order"] = args.optimal_ordering
    options_dict["solute_natoms"] = args.natoms_solute

    return ClustOptions(**options_dict)


def save_clusters_config(
    trajfile, clusters, distmat, noh, reorder, nsatoms, outbasename, outfmt, reorderexcl
):
    # complete distance matrix
    sqdistmat = squareform(distmat)

    for cnum in range(1, max(clusters) + 1):
        # create object to output the configurations
        outfile = pybel.Outputfile(outfmt, outbasename + "_" + str(cnum) + "." + outfmt)

        # creates mask with True only for the members of cluster number cnum
        mask = np.array([1 if i == cnum else 0 for i in clusters], dtype=bool)

        # gets the member with smallest sum of distances from the submatrix
        idx = np.argmin(sum(sqdistmat[:, mask][mask, :]))

        # get list with the members of this cluster only and store medoid
        sublist = [num for (num, cluster) in enumerate(clusters) if cluster == cnum]
        medoid = sublist[idx]

        # get the medoid coordinates
        for idx, mol in enumerate(
            pybel.readfile(os.path.splitext(trajfile)[1][1:], trajfile)
        ):
            if idx != medoid:
                continue

            # medoid coordinates
            tnatoms = len(mol.atoms)
            q_atoms, q_all = get_mol_info(mol)

            if nsatoms:
                # get the number of non hydrogen atoms in the solute to subtract if needed
                if noh:
                    natoms = len(np.where(q_atoms[:nsatoms] != "H")[0])
                else:
                    natoms = nsatoms

                if noh:
                    not_hydrogens = np.where(q_atoms != "H")
                    Q = np.copy(q_all[not_hydrogens])
                    Qa = np.copy(q_atoms[not_hydrogens])
                else:
                    Q = np.copy(q_all)
                    Qa = np.copy(q_atoms)

                qcenter = rmsd.centroid(Q[:natoms])
            elif noh:
                not_hydrogens = np.where(q_atoms != "H")
                Q = np.copy(q_all[not_hydrogens])
                qcenter = rmsd.centroid(Q)
                Qa = np.copy(q_atoms[not_hydrogens])
            else:
                Q = np.copy(q_all)
                qcenter = rmsd.centroid(Q)
                Qa = np.copy(q_atoms)

            # center the coordinates at the origin
            Q -= qcenter

            # write medoid configuration to file (molstring is a xyz string used to generate de pybel mol)
            molstring = str(tnatoms) + "\n" + mol.title.rstrip() + "\n"
            for i, coords in enumerate(q_all - qcenter):
                molstring += (
                    q_atoms[i]
                    + "\t"
                    + str(coords[0])
                    + "\t"
                    + str(coords[1])
                    + "\t"
                    + str(coords[2])
                    + "\n"
                )
            rmol = pybel.readstring("xyz", molstring)
            outfile.write(rmol)

            break

        # rotate all the cluster members into the medoid and print them to the .xyz file
        for idx, mol in enumerate(
            pybel.readfile(os.path.splitext(trajfile)[1][1:], trajfile)
        ):
            if not mask[idx] or idx == medoid:
                continue

            # config coordinates
            p_atoms, p_all = get_mol_info(mol)

            if nsatoms:
                if noh:
                    not_hydrogens = np.where(p_atoms != "H")
                    P = np.copy(p_all[not_hydrogens])
                    Pa = np.copy(p_atoms[not_hydrogens])
                else:
                    P = np.copy(p_all)
                    Pa = np.copy(p_atoms)

                pcenter = rmsd.centroid(P[:natoms])
            elif noh:
                not_hydrogens = np.where(p_atoms != "H")
                P = np.copy(p_all[not_hydrogens])
                pcenter = rmsd.centroid(P)
                Pa = np.copy(p_atoms[not_hydrogens])
            else:
                P = np.copy(p_all)
                pcenter = rmsd.centroid(P)
                Pa = np.copy(p_atoms)

            # center the coordinates at the origin
            P -= pcenter
            p_all -= pcenter

            # generate rotation to superpose the solute configuration
            if nsatoms:
                # center the coordinates at the solute
                P -= rmsd.centroid(Q[:natoms])

                # try to improve atom matching by performing Kabsch
                # generate a rotation considering only the solute atoms
                U = rmsd.kabsch(P[:natoms], Q[:natoms])

                # rotate the whole system with this rotation
                P = np.dot(P, U)
                p_all = np.dot(p_all, U)

                # reorder solute atoms
                # find the solute atoms that are not excluded
                soluexcl = np.where(reorderexcl < natoms)
                soluteview = np.delete(np.arange(natoms), reorderexcl[soluexcl])
                Pview = P[soluteview]
                Paview = Pa[soluteview]

                # reorder just these atoms
                prr = reorder(Qa[soluteview], Paview, Q[soluteview], Pview)
                Pview = Pview[prr]
                Paview = Paview[prr]

                # build the total molecule reordering just these atoms
                whereins = np.where(
                    np.isin(np.arange(natoms), reorderexcl[soluexcl]) == True
                )
                Psolu = np.insert(
                    Pview,
                    [x - whereins[0].tolist().index(x) for x in whereins[0]],
                    P[reorderexcl[soluexcl]],
                    axis=0,
                )
                Pasolu = np.insert(
                    Paview,
                    [x - whereins[0].tolist().index(x) for x in whereins[0]],
                    Pa[reorderexcl[soluexcl]],
                    axis=0,
                )

                P = np.concatenate((Psolu, P[np.arange(len(P) - natoms) + natoms]))
                Pa = np.concatenate((Pasolu, Pa[np.arange(len(Pa) - natoms) + natoms]))

                # generate a rotation considering only the solute atoms
                U = rmsd.kabsch(P[:natoms], Q[:natoms])

                # rotate the whole system with this rotation
                P = np.dot(P, U)
                p_all = np.dot(p_all, U)

                # consider only the solvent atoms in the reorder (without exclusions)
                solvexcl = np.where(reorderexcl >= natoms)
                solvview = np.delete(np.arange(natoms, len(P)), reorderexcl[solvexcl])
                Pview = P[solvview]
                Paview = Pa[solvview]

                # reorder just these atoms
                prr = reorder(Qa[solvview], Paview, Q[solvview], Pview)
                Pview = Pview[prr]
                Paview = Paview[prr]

                # build the total molecule with the reordered atoms
                whereins = np.where(
                    np.isin(np.arange(natoms, len(P)), reorderexcl[solvexcl]) == True
                )
                Psolv = np.insert(
                    Pview,
                    [x - whereins[0].tolist().index(x) for x in whereins[0]],
                    P[reorderexcl[solvexcl]],
                    axis=0,
                )
                Pasolv = np.insert(
                    Paview,
                    [x - whereins[0].tolist().index(x) for x in whereins[0]],
                    Pa[reorderexcl[solvexcl]],
                    axis=0,
                )

                Pr = np.concatenate((P[:natoms], Psolv))
                Pra = np.concatenate((Pa[:natoms], Pasolv))
            # reorder the atoms if necessary
            elif reorder:
                # try to improve atom matching by performing Kabsch
                # generate a rotation considering only the solute atoms
                U = rmsd.kabsch(P, Q)

                # rotate the whole system with this rotation
                P = np.dot(P, U)
                p_all = np.dot(p_all, U)

                # get the view without the excluded atoms
                view = np.delete(np.arange(len(P)), reorderexcl)
                Pview = P[view]
                Paview = Pa[view]

                prr = reorder(Qa[view], Paview, Q[view], Pview)
                Pview = Pview[prr]
                Paview = Paview[prr]

                # build the total molecule with the reordered atoms
                whereins = np.where(np.isin(np.arange(len(P)), reorderexcl) == True)
                Pr = np.insert(
                    Pview,
                    [x - whereins[0].tolist().index(x) for x in whereins[0]],
                    P[reorderexcl],
                    axis=0,
                )
                Pra = np.insert(
                    Paview,
                    [x - whereins[0].tolist().index(x) for x in whereins[0]],
                    Pa[reorderexcl],
                    axis=0,
                )
            else:
                Pr = P
                Pra = Pa

            # generate rotation matrix
            U = rmsd.kabsch(Pr, Q)

            # rotate whole configuration (considering hydrogens even with noh)
            p_all = np.dot(p_all, U)

            # write rotated configuration to file (molstring is a xyz string used to generate de pybel mol)
            molstring = str(tnatoms) + "\n" + mol.title.rstrip() + "\n"
            for i, coords in enumerate(p_all):
                molstring += (
                    p_atoms[i]
                    + "\t"
                    + str(coords[0])
                    + "\t"
                    + str(coords[1])
                    + "\t"
                    + str(coords[2])
                    + "\n"
                )
            rmol = pybel.readstring("xyz", molstring)
            outfile.write(rmol)

        # closes the file for the cnum cluster
        outfile.close()
