import os
try:
    from Cython.Build import cythonize
except:
    raise Exception("Install 'cython'.")
from . import defaultconfig as config
from .parser import parse
from .exporter import CythonDeclarationExporter, CythonImplementationExporter


def write_cython_wrapper(filenames, modulename=None, target=".", verbose=0):
    if not os.path.exists(target):
        os.makedirs(target)

    results, cython_files = make_cython_wrapper(
        filenames, modulename, target, verbose)
    write_files(results, target)
    cython(cython_files, target)


def write_files(files, target="."):
    for filename, content in files.items():
        outputfile = os.path.join(target, filename)
        open(outputfile, "w").write(content)


def cython(cython_files, target="."):
    for cython_file in cython_files:
        inputfile = os.path.join(target, cython_file)
        #cythonize(inputfile, cplus=True)
        os.system("cython --cplus %s" % inputfile)


def make_cython_wrapper(filenames, modulename=None, target=".", verbose=0):
    """Make Cython wrapper for C++ files.

    Parameters
    ----------
    filenames : list or string
        C++ files

    modulename : string, optional (default: name of the only header)
        Name of the module

    target : string, optional (default: ".")
        Target directory

    verbose : int, optional (default: 0)
        Verbosity level

    Returns
    -------
    results : dict
        Mapping from filename to generated file content

    files_to_cythonize : list
        Files that we have to convert with Cython
    """
    if isinstance(filenames, str):
        filenames = [filenames]
    if len(filenames) == 1 and modulename is None:
        modulename = _derive_module_name_from(filenames[0])
    if modulename is None:
        raise ValueError("Please give a module name when there are multiple "
                         "C++ files that you want to wrap.")

    asts = _parse_files(filenames, verbose)
    classes = _collect_classes(asts)
    typedefs = _collect_typedefs(asts)

    results = {}
    ext_results, files_to_cythonize = _generate_extension(
        modulename, asts, classes, typedefs, verbose)
    results.update(ext_results)

    decl_results = _generate_declarations(asts, verbose)
    results.update(decl_results)

    results["setup.py"] = _make_setup(filenames, modulename, target)

    return results, files_to_cythonize


def _derive_module_name_from(filename):
    filename = filename.split(os.sep)[-1]
    return filename.split(".")[0]


def _parse_files(filenames, verbose):
    asts = []
    for filename in filenames:
        is_header = file_ending(filename) in config.cpp_header_endings

        if is_header:  # Clang does not really parse headers
            parsable_file = filename + ".cc"
            with open(parsable_file, "w") as f:
                f.write(open(filename, "r").read())
        else:
            parsable_file = filename

        asts.append(parse(filename, parsable_file, verbose))

        if is_header:
            os.remove(parsable_file)

    return asts


def file_ending(filename):
    return filename.split(".")[-1]


def _collect_classes(asts):
    types = [clazz.name for ast in asts for clazz in ast.classes]
    types.extend([clazz.name for ast in asts for clazz in ast.structs])
    return types


def _collect_typedefs(asts):
    return {typedef.tipe: typedef.underlying_type for ast in asts
            for typedef in ast.typedefs}


def _generate_extension(modulename, asts, classes, typedefs, verbose):
    results = {}
    files_to_cythonize = []
    extension = ""
    for ast in asts:
        cie = CythonImplementationExporter(classes, typedefs)
        ast.accept(cie)
        extension += cie.export()
    pyx_filename = modulename + "." + config.pyx_file_ending
    results[pyx_filename] = extension
    files_to_cythonize.append(pyx_filename)
    if verbose >= 2:
        print("= %s =" % pyx_filename)
        print(extension)
    return results, files_to_cythonize


def _generate_declarations(asts, verbose):
    results = {}
    declarations = ""
    for ast in asts:
        cde = CythonDeclarationExporter()
        ast.accept(cde)
        declarations += cde.export()
    pxd_filename = "_declarations." + config.pxd_file_ending
    results[pxd_filename] = declarations
    if verbose >= 2:
        print("= %s =" % pxd_filename)
        print(declarations)
    return results


def _make_setup(filenames, modulename, target):
    sourcedir = os.path.relpath(".", start=target)
    header_relpaths = [os.path.relpath(filename, start=target)
                       for filename in filenames]
    extension = {
        "filename": ", ".join(header_relpaths),
        "module": modulename,
        "sourcedir": sourcedir
    }
    return config.setup_py % extension
