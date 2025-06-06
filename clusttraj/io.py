"""Input parsing, output information and a class to store the options for
clustering."""

from openbabel import pybel
from openbabel import openbabel
from scipy.spatial.distance import squareform
import os
import sys
import argparse
import numpy as np
import rmsd
import logging
import importlib.util
from typing import Callable, List, Union
from dataclasses import dataclass
from .utils import get_mol_info

if importlib.util.find_spec("qmllib"):
    has_qml = True
else:
    has_qml = False

header_string = r"""
        __           __  __               _ 
  _____/ /_  _______/ /_/ /__________ _  (_)
 / ___/ / / / / ___/ __/ __/ ___/ __ `/ / / 
/ /__/ / /_/ (__  ) /_/ /_/ /  / /_/ / / /  
\___/_/\__,_/____/\__/\__/_/   \__,_/_/ /   
                                   /___/    

A solvent-informed tool for clustering trajectories.

Rafael Bicudo Ribeiro and Henrique Musseli Cezar

If you use this package, please cite:

Ribeiro, R. B. & Cezar, H. M. clusttraj: A Solvent-Informed Clustering Tool for Molecular Modeling.
Preprint at https://doi.org/10.48550/ARXIV.2504.14978 (2025)
"""


@dataclass
class ClustOptions:
    """Class to store the options for clustering."""

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
    reorder_solvent_only: bool = None
    exclusions: bool = None
    no_hydrogen: bool = None
    input_distmat: bool = None
    save_confs: bool = None
    plot: bool = None
    opt_order: bool = None
    overwrite: bool = None
    final_kabsch: bool = None
    silhouette_score: bool = None
    metrics: bool = None
    distmat_name: str = None
    out_clust_name: str = None
    evo_name: str = None
    mds_name: str = None
    dendrogram_name: str = None
    out_conf_name: str = None
    summary_name: str = None
    solute_natoms: int = None
    weight_solute: float = None
    reorder_excl: np.ndarray = None
    optimal_cut: np.ndarray = None
    verbose: bool = None

    def update(self, new: dict) -> None:
        """Update the instance with new values.

        Args:
            new (dict): A dictionary containing the new values to update.

        Returns:
            None
        """
        for key, value in new.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def __str__(self) -> str:
        """Return a string representation of the ClustOptions object.

        Returns:
            str: The string representation of the ClustOptions object.
        """
        return_str = header_string
        return_str += "\nFull command: " + " ".join(sys.argv)

        # main parameters
        return_str += f"\n\nClusterized from trajectory file: {self.trajfile}\n"
        return_str += f"Method: {self.method}\n"
        if self.silhouette_score:
            return_str += "\nUsing silhouette score\n"
            if isinstance(self.optimal_cut, (np.ndarray, list)):
                scut = self.optimal_cut[0]
            elif isinstance(self.optimal_cut, (float, np.float32, np.float64)):
                scut = self.optimal_cut
            else:
                raise ValueError("optimal_cut must be a float or np.ndarray")
            return_str += f"RMSD criterion found by silhouette: {scut}\n"
        else:
            return_str += f"RMSD criterion: {self.min_rmsd}\n"
        return_str += f"Ignoring hydrogens?: {self.no_hydrogen}\n"

        # reordering options
        if self.reorder:
            if self.solute_natoms:
                return_str += "\nUsing solute-solvent adjustment/reordering\n"
                if self.final_kabsch:
                    return_str += "Using final Kabsch rotation before computing RMSD\n"
                return_str += f"Number of solute atoms: {self.solute_natoms}\n"
                if self.weight_solute:
                    return_str += f"Weight of the solute atoms: {self.weight_solute}\n"
                else:
                    return_str += "Unweighted RMSD according to solute/solvent.\n"
                if self.reorder_solvent_only:
                    return_str += "Reordering only solvent atoms\n"
            else:
                return_str += "\nReordering all atom at the same time\n"

            return_str += f"Reordering algorithm: {self.reorder_alg_name}\n"

            if self.exclusions:
                exclusions_str = ""
                for val in self.reorder_excl:
                    exclusions_str += "%d " % val
                return_str += f"Atoms that weren't considered in the reordering: {exclusions_str.strip()}\n"

        # write file names
        if self.input_distmat:
            return_str += f"\nRMSD matrix was read from: {self.distmat_name}\n"
        else:
            return_str += f"\nRMSD matrix was written in: {self.distmat_name}\n"

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


class Logger:
    """Logger class."""

    logformat = "%(asctime)s %(levelname)-8s [%(filename)s:%(lineno)d] <%(funcName)s> %(message)s"
    formatter = logging.Formatter(fmt=logformat)
    logger = logging.getLogger(__name__)

    @classmethod
    def setup(cls, logfile: str) -> None:
        """Set up the logger.

        Args:
            logfile (str): The path to the log file.

        Returns:
            None
        """
        cls.logger.setLevel(logging.INFO)
        cls.fh = logging.FileHandler(logfile)
        cls.fh.setLevel(logging.DEBUG)
        cls.fh.setFormatter(cls.formatter)
        cls.ch = logging.StreamHandler()
        cls.ch.setStream(sys.stdout)
        cls.ch.setLevel(logging.INFO)
        cls.ch.setFormatter(cls.formatter)
        cls.logger.addHandler(cls.fh)
        cls.logger.addHandler(cls.ch)
        cls.logger.info(header_string)


def check_positive(value: str) -> int:
    """Check if the given value is a positive integer.

    Args:
        value (str): The value to be checked.

    Raises:
        argparse.ArgumentTypeError: If the value is not a positive integer.

    Returns:
        int: The converted positive integer value.
    """
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError("%s is an invalid positive int value" % value)
    return ivalue


def extant_file(x: str) -> str:
    """Check if a file exists.

    Args:
        x (str): The file path to check.

    Raises:
        argparse.ArgumentTypeError: If the file does not exist.

    Returns:
        str: The input file path if it exists.
    """
    if not os.path.exists(x):
        raise argparse.ArgumentTypeError(f"{x} does not exist")
    return x


def configure_runtime(args_in: List[str]) -> ClustOptions:
    """Configure the runtime based on command line arguments.

    Args:
        args_in (List[str]): The command line arguments.

    Returns:
        argparse.Namespace: The parsed command line arguments.
    """
    parser = argparse.ArgumentParser(
        prog="clusttraj",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=header_string,
    )

    parser.add_argument(
        "trajectory_file",
        type=extant_file,
        help="path to the trajectory containing the conformations to be classified",
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
        help="defines the number of processes used to compute the RMSD matrix and multidimensional representation (default = 4)",
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
        "-rs",
        "--reorder-solvent-only",
        action="store_true",
        help="reorder only the solvent atoms",
    )
    parser.add_argument(
        "--reorder-alg",
        action="store",
        default="hungarian",
        metavar="METHOD",
        help="select which reorder algorithm to use; hungarian (default), intertia-hungarian, brute, distance, qml. Warning: brute is VERY slow",
    )
    parser.add_argument(
        "-ns",
        "--natoms-solute",
        metavar="NATOMS",
        type=check_positive,
        help="number of solute atoms, to ignore these atoms in the reordering process",
    )
    parser.add_argument(
        "-ws",
        "--weight-solute",
        metavar="WEIGHT SOLUTE",
        type=float,
        help="weight of the solute atoms in the RMSD calculation",
    )
    parser.add_argument(
        "-odl",
        "--optimal-ordering",
        action="store_true",
        help="use optimal ordering in linkage (can be slow for large trees, and only useful for dendrogram visualization)",
    )
    parser.add_argument(
        "--final-kabsch",
        action="store_true",
        help="force a final Kabsch rotation before the RMSD computation (effect only when using -ns and -e)",
    )
    parser.add_argument(
        "--log",
        type=str,
        metavar="FILE",
        default="clusttraj.log",
        help="log file (default: clusttraj.log)",
    )
    parser.add_argument(
        "--metrics",
        action="store_true",
        help="compute metrics to evaluate the clustering procedure quality.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="increase verbosity, printing the timings for each part of the program.",
    )

    rmsd_criterion = parser.add_mutually_exclusive_group(required=True)

    rmsd_criterion.add_argument(
        "-ss",
        "--silhouette-score",
        action="store_true",
        help="use the silhouette to determine the criterion to classify structures",
    )
    rmsd_criterion.add_argument(
        "-rmsd",
        "--min-rmsd",
        type=float,
        help="value of RMSD used to classify structures as similar",
    )

    io_group = parser.add_mutually_exclusive_group()
    io_group.add_argument(
        "-i",
        "--input",
        type=extant_file,
        metavar="FILE",
        help="file containing input RMSD matrix in condensed form (.npy format)",
    )
    io_group.add_argument(
        "-od",
        "--outputdistmat",
        metavar="FILE",
        default="distmat.npy",
        help="file to store RMSD matrix in condensed form (default: distmat.npy)",
    )

    if len(sys.argv) == 0:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args(args_in)

    # setup the logger
    Logger.setup(args.log)

    # check input consistency
    if os.path.splitext(args.trajectory_file)[1][1:] not in pybel.informats.keys():
        parser.error(
            f"The trajectory file format ({os.path.splitext(args.trajectory_file)[1][1:]}) is not supported."
        )

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

    if args.reorder_alg not in [
        "inertia-hungarian",
        "hungarian",
        "brute",
        "distance",
        "qml",
    ]:
        parser.error(
            f"The reorder method you selected with --reorder-method ({args.reorder_alg}) is not valid."
        )

    if (args.reorder_alg == "qml") and (not has_qml):
        parser.error(
            "You must have the optional dependency `qmllib` installed in order to use it as a reorder method."
        )

    if args.clusters_configurations:
        if args.clusters_configurations not in pybel.outformats.keys():
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

    if args.reorder_solvent_only and not args.natoms_solute:
        parser.error(
            "You must specify the number of solute atoms with -ns to use the -rs option."
        )

    if args.weight_solute and not args.natoms_solute:
        parser.error(
            "You must specify the number of solute atoms with -ns to use the -ws option."
        )

    if args.weight_solute:
        if args.weight_solute < 0.0 or args.weight_solute > 1.0:
            parser.error("The weight of the solute atoms must be between 0 and 1.")

    return parse_args(args)


def parse_args(args: argparse.Namespace) -> ClustOptions:
    """Parse all the information from the argument parser, storing in the
    ClustOptions class.

    Define file names and set the pointers to the correct functions.

    Args:
        args (Namespace): The arguments parsed from the argument parser.

    Returns:
        ClustOptions: An instance of the ClustOptions class with the parsed options.
    """
    basenameout = os.path.splitext(args.outputclusters)[0]

    options_dict = {
        "solute_natoms": args.natoms_solute,
        "weight_solute": args.weight_solute,
        "reorder_excl": (
            np.asarray([x - 1 for x in args.reorder_exclusions], np.int32)
            if args.reorder_exclusions
            else np.asarray([], np.int32)
        ),
        "exclusions": bool(args.reorder_exclusions),
        "reorder_alg_name": args.reorder_alg,
        "reorder_alg": None,
        "reorder_solvent_only": bool(args.reorder_solvent_only),
        "reorder": bool(args.reorder),
        "input_distmat": bool(args.input),
        "distmat_name": args.outputdistmat if not args.input else args.input,
        "out_clust_name": args.outputclusters,
        "summary_name": basenameout + ".out",
        "save_confs": bool(args.clusters_configurations),
        "out_conf_name": (
            basenameout + "_confs" if args.clusters_configurations else None
        ),
        "out_conf_fmt": (
            args.clusters_configurations if args.clusters_configurations else None
        ),
        "plot": bool(args.plot),
        "evo_name": basenameout + "_evo.pdf" if args.plot else None,
        "dendrogram_name": basenameout + "_dendrogram.pdf" if args.plot else None,
        "mds_name": basenameout + "_mds.pdf" if args.plot else None,
        "trajfile": args.trajectory_file,
        "min_rmsd": args.min_rmsd,
        "method": args.method,
        "n_workers": args.nprocesses,
        "no_hydrogen": args.no_hydrogen,
        "opt_order": args.optimal_ordering,
        "overwrite": args.force,
        "final_kabsch": args.final_kabsch,
        "silhouette_score": args.silhouette_score,
        "metrics": args.metrics,
        "verbose": args.verbose,
    }

    if args.reorder:
        if args.reorder_alg == "hungarian":
            options_dict["reorder_alg"] = rmsd.reorder_hungarian
        elif args.reorder_alg == "distance":
            options_dict["reorder_alg"] = rmsd.reorder_distance
        elif args.reorder_alg == "brute":
            options_dict["reorder_alg"] = rmsd.reorder_brute
        elif args.reorder_alg == "qml":
            options_dict["reorder_alg"] = rmsd.reorder_similarity

    if not args.input and os.path.exists(args.outputdistmat) and not args.force:
        raise FileExistsError(
            f"File {args.outputdistmat} already exists, specify a new filename with the -od command option or use the -f option. If you are trying to read the RMSD matrix from a file, use the -i option."
        )

    if os.path.exists(args.outputclusters) and not args.force:
        raise FileExistsError(
            f"File {args.outputclusters} already exists, specify a new filename with the -oc command option or use the -f option."
        )

    return ClustOptions(**options_dict)


def save_clusters_config(
    trajfile: str,
    clusters: np.ndarray,
    distmat: np.ndarray,
    noh: bool,
    reorder: Union[
        Callable[[np.ndarray, np.ndarray, np.ndarray, np.ndarray], np.ndarray], None
    ],
    reorder_solvent_only: bool,
    nsatoms: int,
    weight_solute: float,
    outbasename: str,
    outfmt: str,
    reorderexcl: np.ndarray,
    final_kabsch: bool,
    overwrite: bool,
) -> None:
    """Save best superpositioned configurations for each cluster. First
    configuration is the medoid.

    Args:
        trajfile: The trajectory file path.
        clusters: An array containing cluster labels.
        distmat: The RMSD matrix.
        noh: Flag indicating whether to exclude hydrogen atoms.
        reorder (Union[Callable[[np.ndarray, np.ndarray, np.ndarray, np.ndarray], np.ndarray], None]):
            A function to reorder the atoms, if necessary.
        nsatoms: The number of atoms in the solute.
        outbasename: The base name for the output files.
        outfmt: The output file format.
        reorderexcl: An array of atom indices to exclude during reordering.
        final_kabsch: Flag indicating whether to perform a final Kabsch rotation.
        overwrite: Flag indicating whether to overwrite existing output files.

    Returns:
        None
    """
    # complete RMSD matrix
    sqdistmat = squareform(distmat)

    for cnum in range(1, max(clusters) + 1):
        # create object to output the configurations
        outfile = pybel.Outputfile(
            outfmt, outbasename + "_" + str(cnum) + "." + outfmt, overwrite=overwrite
        )

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

            # get the number of non hydrogen atoms in the solute to subtract if needed
            natoms = nsatoms
            if noh:
                natoms = len(np.where(q_atoms[:nsatoms] != 1)[0])

            if nsatoms:
                if noh:
                    not_hydrogens = np.where(q_atoms != 1)
                    Q = np.copy(q_all[not_hydrogens])
                    Qa = np.copy(q_atoms[not_hydrogens])
                else:
                    Q = np.copy(q_all)
                    Qa = np.copy(q_atoms)

                qcenter = rmsd.centroid(Q[:natoms])
            elif noh:
                not_hydrogens = np.where(q_atoms != 1)
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
                    openbabel.GetSymbol(int(q_atoms[i]))
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
                    not_hydrogens = np.where(p_atoms != 1)
                    P = np.copy(p_all[not_hydrogens])
                    Pa = np.copy(p_atoms[not_hydrogens])
                else:
                    P = np.copy(p_all)
                    Pa = np.copy(p_atoms)

                pcenter = rmsd.centroid(P[:natoms])
            elif noh:
                not_hydrogens = np.where(p_atoms != 1)
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
                if reorder and not reorder_solvent_only:
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
                    # whereins = np.where(
                    #     np.isin(np.arange(natoms), reorderexcl[soluexcl]) is True
                    # )
                    whereins = np.where(
                        np.atleast_1d(np.isin(np.arange(natoms), reorderexcl))
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
                    Pa = np.concatenate(
                        (Pasolu, Pa[np.arange(len(Pa) - natoms) + natoms])
                    )

                    # generate a rotation considering only the solute atoms
                    U = rmsd.kabsch(P[:natoms], Q[:natoms])

                    # rotate the whole system with this rotation
                    P = np.dot(P, U)
                    p_all = np.dot(p_all, U)

            else:
                # Kabsch rotation
                U = rmsd.kabsch(P, Q)
                P = np.dot(P, U)
                p_all = np.dot(p_all, U)

            # reorder the solvent atoms separately
            if reorder:
                # if the solute is specified, reorder just the solvent atoms in this step
                if nsatoms:
                    exclusions = np.unique(
                        np.concatenate((np.arange(natoms), reorderexcl))
                    )
                else:
                    exclusions = reorderexcl

                # get the view without the excluded atoms
                view = np.delete(np.arange(len(P)), exclusions)
                Pview = P[view]
                Paview = Pa[view]

                prr = reorder(Qa[view], Paview, Q[view], Pview)
                Pview = Pview[prr]

                # build the total molecule with the reordered atoms
                whereins = np.where(
                    np.atleast_1d(np.isin(np.arange(len(P)), exclusions))
                )
                Pr = np.insert(
                    Pview,
                    [x - whereins[0].tolist().index(x) for x in whereins[0]],
                    P[exclusions],
                    axis=0,
                )
            else:
                Pr = P

            # compute the weights
            if weight_solute and final_kabsch:
                W = np.zeros(Pr.shape[0])
                W[:natoms] = weight_solute / natoms
                W[natoms:] = (1.0 - weight_solute) / (Pr.shape[0] - natoms)

                R, T, _ = rmsd.kabsch_weighted(Q, Pr, W)
                p_all = np.dot(p_all, R.T) + T

            elif nsatoms and reorder and final_kabsch:
                # rotate whole configuration (considering hydrogens even with noh)
                U = rmsd.kabsch(Pr, Q)
                p_all = np.dot(p_all, U)

            # write rotated configuration to file (molstring is a xyz string used to generate de pybel mol)
            molstring = str(tnatoms) + "\n" + mol.title.rstrip() + "\n"
            for i, coords in enumerate(p_all):
                molstring += (
                    openbabel.GetSymbol(int(p_atoms[i]))
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


# type: ignore
