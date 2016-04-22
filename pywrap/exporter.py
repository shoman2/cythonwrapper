import os
import warnings
from . import templates
from .templates import render
from .type_conversion import create_type_converter
from .utils import indent_block, from_camel_case


class CythonDeclarationExporter:
    """Export AST to Cython declaration file (.pxd).

    This class implements the visitor pattern.
    """
    def __init__(self, includes, config):
        self.includes = includes
        self.config = config
        self.output = ""
        self.ctors = []
        self.methods = []
        self.arguments = []
        self.fields = []

    def visit_ast(self, ast):
        pass

    def visit_enum(self, enum):
        self.output += render("enum_decl", **enum.__dict__)

    def visit_typedef(self, typedef):
        self.output += templates.typedef_decl % typedef.__dict__

    def visit_class(self, clazz):
        class_decl = {}
        class_decl.update(clazz.__dict__)
        class_decl["fields"] = self.fields
        class_decl["ctors"] = self.ctors
        class_decl["methods"] = self.methods
        class_decl["empty_body"] = (len(self.fields) + len(self.methods) +
                                    len(self.ctors) == 0)

        self.output += render("class_decl", **class_decl)

        self.fields = []
        self.ctors = []
        self.methods = []

    def visit_field(self, field):
        self.fields.append(templates.field_decl % field.__dict__)

    def visit_constructor(self, ctor):
        const_dict = {"args": ", ".join(self.arguments)}
        const_dict.update(ctor.__dict__)
        const_str = templates.constructor_decl % const_dict
        self.ctors.append(const_str)
        self.arguments = []

    def visit_method(self, method):
        method_dict = {"args": ", ".join(self.arguments)}
        method_dict.update(method.__dict__)
        method_dict["name"] = replace_operator_decl(method_dict["name"],
                                                    self.config)
        method_str = templates.method_decl % method_dict
        self.methods.append(method_str)
        self.arguments = []

    def visit_function(self, function):
        function_dict = {"args": ", ".join(self.arguments)}
        function_dict.update(function.__dict__)
        function_str = templates.function_decl % function_dict
        self.output += function_str
        self.arguments = []

    def visit_param(self, param):
        self.arguments.append(templates.arg_decl % param.__dict__)

    def export(self):
        return self.output


def replace_operator_decl(method_name, config):
    if method_name in config.call_operators:
        return "%s \"%s\"" % (config.call_operators[method_name], method_name)
    else:
        return method_name


class CythonImplementationExporter:
    """Export AST to Cython implementation file (.pyx).

    This class implements the visitor pattern.
    """
    def __init__(self, includes, type_info, config):
        self.includes = includes
        self.type_info = type_info
        self.config = config
        self.output = ""
        self.ctors = []
        self.methods = []
        self.fields = []

    def visit_ast(self, ast):
        pass

    def visit_enum(self, enum):
        self.output += render("enum", **enum.__dict__)

    def visit_typedef(self, typedef):
        pass

    def visit_class(self, clazz):
        if len(self.ctors) > 1:
            msg = ("Class '%s' has more than one constructor. This is not "
                   "compatible to Python. The last constructor will overwrite "
                   "all others." % clazz.name)
            warnings.warn(msg)
        elif len(self.ctors) == 0:
            self.ctors.append(templates.ctor_default_def % clazz.__dict__)

        class_def = {}
        class_def.update(clazz.__dict__)
        class_def["fields"] = self.fields
        class_def["ctors"] = self.ctors
        class_def["methods"] = self.methods

        self.output += render("class", **class_def)

        self.fields = []
        self.ctors = []
        self.methods = []

    def visit_field(self, field):
        try:
            setter_def = SetterDefinition(
                field, self.includes, self.type_info, self.config).make()
            getter_def = GetterDefinition(
                field, self.includes, self.type_info, self.config).make()
            self.fields.append({
                "name": from_camel_case(field.name),
                "getter": indent_block(getter_def, 1),
                "setter": indent_block(setter_def, 1)
            })
        except NotImplementedError as e:
            warnings.warn(e.message + " Ignoring field '%s'" % field.name)

    def visit_constructor(self, ctor):
        try:
            constructor_def = ConstructorDefinition(
                ctor.class_name, ctor.arguments, self.includes,
                self.type_info, self.config).make()
            self.ctors.append(indent_block(constructor_def, 1))
        except NotImplementedError as e:
            warnings.warn(e.message + " Ignoring method '%s'" % ctor.name)

    def visit_method(self, method):
        try:
            method_def = MethodDefinition(
                method.class_name, method.name, method.arguments, self.includes,
                method.result_type, self.type_info, self.config).make()
            self.methods.append(indent_block(method_def, 1))
        except NotImplementedError as e:
            warnings.warn(e.message + " Ignoring method '%s'" % method.name)

    def visit_function(self, function):
        try:
            self.output += os.linesep * 2 + FunctionDefinition(
                function.name, function.arguments, self.includes,
                function.result_type, self.type_info,
                self.config).make() + os.linesep
        except NotImplementedError as e:
            warnings.warn(e.message + " Ignoring function '%s'" % function.name)

    def visit_param(self, param):
        pass

    def export(self):
        return self.output


class FunctionDefinition(object):
    def __init__(self, name, arguments, includes, result_type, type_info,
                 config):
        self.name = name
        self.arguments = arguments
        self.includes = includes
        self.initial_args = []
        self.result_type = result_type
        self.type_info = type_info
        self.config = config
        self.output_is_copy = True
        self._create_type_converters()

    def _create_type_converters(self):
        skip = 0
        self.type_converters = []
        for i, arg in enumerate(self.arguments):
            if skip > 0:
                skip -= 1
                continue
            type_converter = create_type_converter(
                arg.tipe, arg.name, self.type_info, self.config,
                (self.arguments, i))
            type_converter.add_includes(self.includes)
            self.type_converters.append(type_converter)
            skip = type_converter.n_cpp_args() - 1
        self.output_type_converter = create_type_converter(
            self.result_type, None, self.type_info, self.config)
        self.output_type_converter.add_includes(self.includes)

    def make(self):
        function = {}
        function.update(self._signature())
        function["input_conversions"], call_args = self._input_type_conversions(
            self.includes)
        function["call"] = self._call_cpp_function(call_args)
        function["return_output"] = self.output_type_converter.return_output(
            self.output_is_copy)
        return render("function", **function)

    def _signature(self):
        function_name = from_camel_case(self.config.operators.get(
            self.name, self.name))
        return {"def_prefix": self._def_prefix(function_name),
                "args": ", ".join(self._cython_signature_args()),
                "name": function_name}

    def _def_prefix(self, function_name):
        special_method = (function_name.startswith("__") and
                          function_name.endswith("__"))
        if special_method:
            return "def"
        else:
            return "cpdef"

    def _cython_signature_args(self):
        cython_signature_args = []
        cython_signature_args.extend(self.initial_args)
        for type_converter in self.type_converters:
            arg = type_converter.python_type_decl()
            cython_signature_args.append(arg)
        return cython_signature_args

    def _input_type_conversions(self, includes):
        conversions = []
        call_args = []
        for type_converter in self.type_converters:
            conversions.append(type_converter.python_to_cpp())
            call_args.extend(type_converter.cpp_call_args())
        return conversions, call_args

    def _call_cpp_function(self, call_args):
        cpp_type_decl = self.output_type_converter.cpp_type_decl()
        call = templates.fun_call % {"name": self.name,
                                     "args": ", ".join(call_args)}
        return catch_result(cpp_type_decl, call)


class ConstructorDefinition(FunctionDefinition):
    def __init__(self, class_name, arguments, includes, type_info, config):
        super(ConstructorDefinition, self).__init__(
            "__init__", arguments, includes, result_type=None,
            type_info=type_info, config=config)
        self.initial_args = ["%s self" % class_name]
        self.class_name = class_name

    def _call_cpp_function(self, call_args):
        return templates.ctor_call % {"class_name": self.class_name,
                                      "args": ", ".join(call_args)}


class MethodDefinition(FunctionDefinition):
    def __init__(self, class_name, name, arguments, includes, result_type,
                 type_info, config):
        super(MethodDefinition, self).__init__(
            name, arguments, includes, result_type, type_info, config)
        self.initial_args = ["%s self" % class_name]

    def _call_cpp_function(self, call_args):
        cpp_type_decl = self.output_type_converter.cpp_type_decl()
        call = templates.method_call % {
            "name": self.config.call_operators.get(self.name, self.name),
            "args": ", ".join(call_args)}
        return catch_result(cpp_type_decl, call)


class SetterDefinition(MethodDefinition):
    def __init__(self, field, includes, type_info, config):
        name = "set_%s" % field.name
        super(SetterDefinition, self).__init__(
            field.class_name, name, [field], includes, "void", type_info,
            config)
        self.field_name = field.name

    def _call_cpp_function(self, call_args):
        assert len(call_args) == 1
        return templates.setter_call % {"name": self.field_name,
                                        "call_arg": call_args[0]}


class GetterDefinition(MethodDefinition):
    def __init__(self, field, includes, type_info, config):
        name = "get_%s" % field.name
        super(GetterDefinition, self).__init__(
            field.class_name, name, [], includes, field.tipe, type_info, config)
        self.output_is_copy = False
        self.field_name = field.name

    def _call_cpp_function(self, call_args):
        assert len(call_args) == 0
        cpp_type_decl = self.output_type_converter.cpp_type_decl()
        call = templates.getter_call % {"name": self.field_name}
        return catch_result(cpp_type_decl, call)


def catch_result(result_type_decl, call):
    if result_type_decl == "":
        return call
    else:
        return templates.catch_result % {"cpp_type_decl": result_type_decl,
                                         "call": call}
