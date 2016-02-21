def is_basic_type(typename):
    # TODO This is not a complete list of the fundamental types. The reason is
    # that I don't know if they all will be converted correctly between Python
    # and C++ by Cython. See http://en.cppreference.com/w/cpp/language/types
    # for a complete list.
    return typename in ["int", "unsigned int", "long", "unsigned long",
                        "float", "double"]


def is_type_with_automatic_conversion(typename):
    # TODO add more types from this list:
    # http://docs.cython.org/src/userguide/wrapping_CPlusPlus.html#standard-library
    return is_basic_type(typename) or typename in ["bool", "string"]


def typename(tname):
    """Get cython type from C++ type."""
    # TODO does not work with std::vector<namespace::type>
    cython_tname = tname
    cython_tname = _remove_const_modifier(cython_tname)
    cython_tname = _remove_reference_modifier(cython_tname)
    cython_tname = _remove_namespace(cython_tname)
    cython_tname = _replace_angle_brackets(cython_tname)
    return cython_tname


def _remove_const_modifier(tname):
    return tname.replace("const ", "")


def _remove_reference_modifier(tname):
    return tname.replace(" &", "")


def _remove_namespace(tname):
    return tname.split("::")[-1]


def _replace_angle_brackets(tname):
    return tname.replace("<", "[").replace(">", "]")


def cython_define_basic_inputarg(cython_tname, cython_argname, python_argname):
    return "cdef %s %s = %s" % (cython_tname, cython_argname, python_argname)


def cython_define_nparray1d_inputarg(cython_tname, cython_argname,
                                     python_argname):
    return (
"""cdef np.ndarray[double, ndim=1] {array_argname} = np.asarray({python_argname})
cdef {cython_tname} {cython_argname} = &{array_argname}[0]
""".format(cython_tname=cython_tname, cython_argname=cython_argname,
           python_argname=python_argname,
           array_argname=python_argname + "_array"))
