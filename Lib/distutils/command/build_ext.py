"""distutils.command.build_ext

Implements the Distutils 'build_ext' command, for building extension
modules (currently limited to C extensions, should accommodate C++
extensions ASAP)."""

# created 1999/08/09, Greg Ward

__revision__ = "$Id$"

import sys, os, string, re
from types import *
from distutils.core import Command
from distutils.errors import *
from distutils.sysconfig import customize_compiler
from distutils.dep_util import newer_group
from distutils.extension import Extension

# An extension name is just a dot-separated list of Python NAMEs (ie.
# the same as a fully-qualified module name).
extension_name_re = re.compile \
    (r'^[a-zA-Z_][a-zA-Z_0-9]*(\.[a-zA-Z_][a-zA-Z_0-9]*)*$')


def show_compilers ():
    from distutils.ccompiler import show_compilers
    show_compilers()


class build_ext (Command):
    
    description = "build C/C++ extensions (compile/link to build directory)"

    # XXX thoughts on how to deal with complex command-line options like
    # these, i.e. how to make it so fancy_getopt can suck them off the
    # command line and make it look like setup.py defined the appropriate
    # lists of tuples of what-have-you.
    #   - each command needs a callback to process its command-line options
    #   - Command.__init__() needs access to its share of the whole
    #     command line (must ultimately come from
    #     Distribution.parse_command_line())
    #   - it then calls the current command class' option-parsing
    #     callback to deal with weird options like -D, which have to
    #     parse the option text and churn out some custom data
    #     structure
    #   - that data structure (in this case, a list of 2-tuples)
    #     will then be present in the command object by the time
    #     we get to finalize_options() (i.e. the constructor
    #     takes care of both command-line and client options
    #     in between initialize_options() and finalize_options())

    sep_by = " (separated by '%s')" % os.pathsep
    user_options = [
        ('build-lib=', 'b',
         "directory for compiled extension modules"),
        ('build-temp=', 't',
         "directory for temporary files (build by-products)"),
        ('inplace', 'i',
         "ignore build-lib and put compiled extensions into the source " +
         "directory alongside your pure Python modules"),
        ('include-dirs=', 'I',
         "list of directories to search for header files" + sep_by),
        ('define=', 'D',
         "C preprocessor macros to define"),
        ('undef=', 'U',
         "C preprocessor macros to undefine"),
        ('libraries=', 'l',
         "external C libraries to link with"),
        ('library-dirs=', 'L',
         "directories to search for external C libraries" + sep_by),
        ('rpath=', 'R',
         "directories to search for shared C libraries at runtime"),
        ('link-objects=', 'O',
         "extra explicit link objects to include in the link"),
        ('debug', 'g',
         "compile/link with debugging information"),
        ('force', 'f',
         "forcibly build everything (ignore file timestamps)"),
        ('compiler=', 'c',
         "specify the compiler type"),
        ('swig-cpp', None,
         "make SWIG create C++ files (default is C)"),
        ]

    help_options = [
        ('help-compiler', None,
         "list available compilers", show_compilers),
        ]

    def initialize_options (self):
        self.extensions = None
        self.build_lib = None
        self.build_temp = None
        self.inplace = 0
        self.package = None

        self.include_dirs = None
        self.define = None
        self.undef = None
        self.libraries = None
        self.library_dirs = None
        self.rpath = None
        self.link_objects = None
        self.debug = None
        self.force = None
        self.compiler = None
        self.swig_cpp = None


    def finalize_options (self):
        from distutils import sysconfig

        self.set_undefined_options ('build',
                                    ('build_lib', 'build_lib'),
                                    ('build_temp', 'build_temp'),
                                    ('compiler', 'compiler'),
                                    ('debug', 'debug'),
                                    ('force', 'force'))

        if self.package is None:
            self.package = self.distribution.ext_package

        self.extensions = self.distribution.ext_modules
        

        # Make sure Python's include directories (for Python.h, config.h,
        # etc.) are in the include search path.
        py_include = sysconfig.get_python_inc()
        plat_py_include = sysconfig.get_python_inc(plat_specific=1)
        if self.include_dirs is None:
            self.include_dirs = self.distribution.include_dirs or []
        if type (self.include_dirs) is StringType:
            self.include_dirs = string.split (self.include_dirs,
                                              os.pathsep)

        # Put the Python "system" include dir at the end, so that
        # any local include dirs take precedence.
        self.include_dirs.append (py_include)
        if plat_py_include != py_include:
            self.include_dirs.append (plat_py_include)

        if type (self.libraries) is StringType:
            self.libraries = [self.libraries]

        # Life is easier if we're not forever checking for None, so
        # simplify these options to empty lists if unset
        if self.libraries is None:
            self.libraries = []
        if self.library_dirs is None:
            self.library_dirs = []
        if self.rpath is None:
            self.rpath = []

        # for extensions under windows use different directories
        # for Release and Debug builds.
        # also Python's library directory must be appended to library_dirs
        if os.name == 'nt':
            self.library_dirs.append (os.path.join(sys.exec_prefix, 'libs'))
            self.implib_dir = self.build_temp
            if self.debug:
                self.build_temp = os.path.join (self.build_temp, "Debug")
            else:
                self.build_temp = os.path.join (self.build_temp, "Release")
    # finalize_options ()
    

    def run (self):

        from distutils.ccompiler import new_compiler

        # 'self.extensions', as supplied by setup.py, is a list of
        # Extension instances.  See the documentation for Extension (in
        # distutils.extension) for details.
        # 
        # For backwards compatibility with Distutils 0.8.2 and earlier, we
        # also allow the 'extensions' list to be a list of tuples:
        #    (ext_name, build_info)
        # where build_info is a dictionary containing everything that
        # Extension instances do except the name, with a few things being
        # differently named.  We convert these 2-tuples to Extension
        # instances as needed.

        if not self.extensions:
            return

        # If we were asked to build any C/C++ libraries, make sure that the
        # directory where we put them is in the library search path for
        # linking extensions.
        if self.distribution.has_c_libraries():
            build_clib = self.get_finalized_command ('build_clib')
            self.libraries.extend (build_clib.get_library_names() or [])
            self.library_dirs.append (build_clib.build_clib)

        # Setup the CCompiler object that we'll use to do all the
        # compiling and linking
        self.compiler = new_compiler (compiler=self.compiler,
                                      verbose=self.verbose,
                                      dry_run=self.dry_run,
                                      force=self.force)
        customize_compiler(self.compiler)

        # And make sure that any compile/link-related options (which might
        # come from the command-line or from the setup script) are set in
        # that CCompiler object -- that way, they automatically apply to
        # all compiling and linking done here.
        if self.include_dirs is not None:
            self.compiler.set_include_dirs (self.include_dirs)
        if self.define is not None:
            # 'define' option is a list of (name,value) tuples
            for (name,value) in self.define:
                self.compiler.define_macro (name, value)
        if self.undef is not None:
            for macro in self.undef:
                self.compiler.undefine_macro (macro)
        if self.libraries is not None:
            self.compiler.set_libraries (self.libraries)
        if self.library_dirs is not None:
            self.compiler.set_library_dirs (self.library_dirs)
        if self.rpath is not None:
            self.compiler.set_runtime_library_dirs (self.rpath)
        if self.link_objects is not None:
            self.compiler.set_link_objects (self.link_objects)

        # Now actually compile and link everything.
        self.build_extensions ()

    # run ()


    def check_extensions_list (self, extensions):
        """Ensure that the list of extensions (presumably provided as a
        command option 'extensions') is valid, i.e. it is a list of
        Extension objects.  We also support the old-style list of 2-tuples,
        where the tuples are (ext_name, build_info), which are converted to
        Extension instances here.

        Raise DistutilsSetupError if the structure is invalid anywhere;
        just returns otherwise.
        """
        if type(extensions) is not ListType:
            raise DistutilsSetupError, \
                  "'ext_modules' option must be a list of Extension instances"
        
        for i in range(len(extensions)):
            ext = extensions[i]
            if isinstance(ext, Extension):
                continue                # OK! (assume type-checking done
                                        # by Extension constructor)

            (ext_name, build_info) = ext
            self.warn(("old-style (ext_name, build_info) tuple found in "
                       "ext_modules for extension '%s'" 
                       "-- please convert to Extension instance" % ext_name))
            if type(ext) is not TupleType and len(ext) != 2:
                raise DistutilsSetupError, \
                      ("each element of 'ext_modules' option must be an "
                       "Extension instance or 2-tuple")

            if not (type(ext_name) is StringType and
                    extension_name_re.match(ext_name)):
                raise DistutilsSetupError, \
                      ("first element of each tuple in 'ext_modules' "
                       "must be the extension name (a string)")

            if type(build_info) is not DictionaryType:
                raise DistutilsSetupError, \
                      ("second element of each tuple in 'ext_modules' "
                       "must be a dictionary (build info)")

            # OK, the (ext_name, build_info) dict is type-safe: convert it
            # to an Extension instance.
            ext = Extension(ext_name, build_info['sources'])

            # Easy stuff: one-to-one mapping from dict elements to
            # instance attributes.
            for key in ('include_dirs',
                        'library_dirs',
                        'libraries',
                        'extra_objects',
                        'extra_compile_args',
                        'extra_link_args'):
                val = build_info.get(key)
                if val is not None:
                    setattr(ext, key, val)

            # Medium-easy stuff: same syntax/semantics, different names.
            ext.runtime_library_dirs = build_info.get('rpath')
            if build_info.has_key('def_file'):
                self.warn("'def_file' element of build info dict "
                          "no longer supported")

            # Non-trivial stuff: 'macros' split into 'define_macros'
            # and 'undef_macros'.
            macros = build_info.get('macros')
            if macros:
                ext.define_macros = []
                ext.undef_macros = []
                for macro in macros:
                    if not (type(macro) is TupleType and
                            1 <= len(macro) <= 2):
                        raise DistutilsSetupError, \
                              ("'macros' element of build info dict "
                               "must be 1- or 2-tuple")
                    if len(macro) == 1:
                        ext.undef_macros.append(macro[0])
                    elif len(macro) == 2:
                        ext.define_macros.append(macro)

            extensions[i] = ext

        # for extensions

    # check_extensions_list ()


    def get_source_files (self):
        self.check_extensions_list(self.extensions)
        filenames = []

        # Wouldn't it be neat if we knew the names of header files too...
        for ext in self.extensions:
            filenames.extend (ext.sources)

        return filenames


    def get_outputs (self):

        # Sanity check the 'extensions' list -- can't assume this is being
        # done in the same run as a 'build_extensions()' call (in fact, we
        # can probably assume that it *isn't*!).
        self.check_extensions_list (self.extensions)

        # And build the list of output (built) filenames.  Note that this
        # ignores the 'inplace' flag, and assumes everything goes in the
        # "build" tree.
        outputs = []
        for ext in self.extensions:
            fullname = self.get_ext_fullname (ext.name)
            outputs.append (os.path.join (self.build_lib,
                                          self.get_ext_filename(fullname)))
        return outputs

    # get_outputs ()


    def build_extensions (self):

        # First, sanity-check the 'extensions' list
        self.check_extensions_list (self.extensions)

        for ext in self.extensions:
            sources = ext.sources
            if sources is None or type (sources) not in (ListType, TupleType):
                raise DistutilsSetupError, \
                      ("in 'ext_modules' option (extension '%s'), " +
                       "'sources' must be present and must be " +
                       "a list of source filenames") % ext.name
            sources = list (sources)

            fullname = self.get_ext_fullname (ext.name)
            if self.inplace:
                # ignore build-lib -- put the compiled extension into
                # the source tree along with pure Python modules

                modpath = string.split (fullname, '.')
                package = string.join (modpath[0:-1], '.')
                base = modpath[-1]

                build_py = self.get_finalized_command ('build_py')
                package_dir = build_py.get_package_dir (package)
                ext_filename = os.path.join (package_dir,
                                             self.get_ext_filename(base))
            else:
                ext_filename = os.path.join (self.build_lib,
                                             self.get_ext_filename(fullname))

            if not (self.force or newer_group(sources, ext_filename, 'newer')):
                self.announce ("skipping '%s' extension (up-to-date)" %
                               ext.name)
                continue # 'for' loop over all extensions
            else:
                self.announce ("building '%s' extension" % ext.name)

            # First, scan the sources for SWIG definition files (.i), run
            # SWIG on 'em to create .c files, and modify the sources list
            # accordingly.
            sources = self.swig_sources(sources)

            # Next, compile the source code to object files.

            # XXX not honouring 'define_macros' or 'undef_macros' -- the
            # CCompiler API needs to change to accommodate this, and I
            # want to do one thing at a time!

            # Two possible sources for extra compiler arguments:
            #   - 'extra_compile_args' in Extension object
            #   - CFLAGS environment variable (not particularly
            #     elegant, but people seem to expect it and I
            #     guess it's useful)
            # The environment variable should take precedence, and
            # any sensible compiler will give precedence to later
            # command line args.  Hence we combine them in order:
            extra_args = ext.extra_compile_args or []

            # XXX and if we support CFLAGS, why not CC (compiler
            # executable), CPPFLAGS (pre-processor options), and LDFLAGS
            # (linker options) too?
            # XXX should we use shlex to properly parse CFLAGS?

            if os.environ.has_key('CFLAGS'):
                extra_args.extend(string.split(os.environ['CFLAGS']))
                
            objects = self.compiler.compile (sources,
                                             output_dir=self.build_temp,
                                             #macros=macros,
                                             include_dirs=ext.include_dirs,
                                             debug=self.debug,
                                             extra_postargs=extra_args)

            # Now link the object files together into a "shared object" --
            # of course, first we have to figure out all the other things
            # that go into the mix.
            if ext.extra_objects:
                objects.extend (ext.extra_objects)
            extra_args = ext.extra_link_args or []


            self.compiler.link_shared_object (
                objects, ext_filename, 
                libraries=self.get_libraries(ext),
                library_dirs=ext.library_dirs,
                runtime_library_dirs=ext.runtime_library_dirs,
                extra_postargs=extra_args,
                export_symbols=self.get_export_symbols(ext), 
                debug=self.debug,
                build_temp=self.build_temp)

    # build_extensions ()


    def swig_sources (self, sources):

        """Walk the list of source files in 'sources', looking for SWIG
        interface (.i) files.  Run SWIG on all that are found, and
        return a modified 'sources' list with SWIG source files replaced
        by the generated C (or C++) files.
        """

        new_sources = []
        swig_sources = []
        swig_targets = {}

        # XXX this drops generated C/C++ files into the source tree, which
        # is fine for developers who want to distribute the generated
        # source -- but there should be an option to put SWIG output in
        # the temp dir.

        if self.swig_cpp:
            target_ext = '.cpp'
        else:
            target_ext = '.c'

        for source in sources:
            (base, ext) = os.path.splitext(source)
            if ext == ".i":             # SWIG interface file
                new_sources.append(base + target_ext)
                swig_sources.append(source)
                swig_targets[source] = new_sources[-1]
            else:
                new_sources.append(source)

        if not swig_sources:
            return new_sources

        swig = self.find_swig()
        swig_cmd = [swig, "-python", "-dnone", "-ISWIG"]
        if self.swig_cpp:
            swig_cmd.append ("-c++")

        for source in swig_sources:
            target = swig_targets[source]
            self.announce ("swigging %s to %s" % (source, target))
            self.spawn(swig_cmd + ["-o", target, source])

        return new_sources

    # swig_sources ()

    def find_swig (self):
        """Return the name of the SWIG executable.  On Unix, this is
        just "swig" -- it should be in the PATH.  Tries a bit harder on
        Windows.
        """

        if os.name == "posix":
            return "swig"
        elif os.name == "nt":

            # Look for SWIG in its standard installation directory on
            # Windows (or so I presume!).  If we find it there, great;
            # if not, act like Unix and assume it's in the PATH.
            for vers in ("1.3", "1.2", "1.1"):
                fn = os.path.join("c:\\swig%s" % vers, "swig.exe")
                if os.path.isfile (fn):
                    return fn
            else:
                return "swig.exe"

        else:
            raise DistutilsPlatformError, \
                  ("I don't know how to find (much less run) SWIG "
                   "on platform '%s'") % os.name

    # find_swig ()
    
    # -- Name generators -----------------------------------------------
    # (extension names, filenames, whatever)

    def get_ext_fullname (self, ext_name):
        if self.package is None:
            return ext_name
        else:
            return self.package + '.' + ext_name

    def get_ext_filename (self, ext_name):
        """Convert the name of an extension (eg. "foo.bar") into the name
        of the file from which it will be loaded (eg. "foo/bar.so", or
        "foo\bar.pyd").
        """

        from distutils.sysconfig import get_config_var
        ext_path = string.split (ext_name, '.')
        # extensions in debug_mode are named 'module_d.pyd' under windows
        so_ext = get_config_var('SO')
        if os.name == 'nt' and self.debug:
            return apply (os.path.join, ext_path) + '_d' + so_ext
        return apply (os.path.join, ext_path) + so_ext

    def get_ext_libname (self, ext_name):
        # create a filename for the (unneeded) lib-file.
        # extensions in debug_mode are named 'module_d.pyd' under windows
        ext_path = string.split (ext_name, '.')
        if os.name == 'nt' and self.debug:
            return apply (os.path.join, ext_path) + '_d.lib'
        return apply (os.path.join, ext_path) + '.lib'


    def get_export_symbols (self, ext):
        """Return the list of symbols that a shared extension has to
        export.  This either uses 'ext.export_symbols' or, if it's not
        provided, "init" + module_name.  Only relevant on Windows, where
        the .pyd file (DLL) must export the module "init" function.
        """

        initfunc_name = "init" + string.split(ext.name,'.')[-1]
        if initfunc_name not in ext.export_symbols:
            ext.export_symbols.append(initfunc_name)
        return ext.export_symbols

    def get_libraries (self, ext):
        """Return the list of libraries to link against when building a
        shared extension.  On most platforms, this is just 'ext.libraries';
        on Windows, we add the Python library (eg. python20.dll).
        """
        # The python library is always needed on Windows.  For MSVC, this
        # is redundant, since the library is mentioned in a pragma in
        # config.h that MSVC groks.  The other Windows compilers all seem
        # to need it mentioned explicitly, though, so that's what we do.
        if sys.platform == "win32": 
            pythonlib = ("python%d%d" %
                 (sys.hexversion >> 24, (sys.hexversion >> 16) & 0xff))
            # don't extend ext.libraries, it may be shared with other
            # extensions, it is a reference to the original list
            return ext.libraries + [pythonlib]
        else:
            return ext.libraries

# class build_ext
