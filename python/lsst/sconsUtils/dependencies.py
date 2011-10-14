import os.path
import collections
import imp
import sys
import SCons.Script
from SCons.Script.SConscript import SConsEnvironment

from . import installation
from . import state

def configure(packageName, versionString=None, eupsProduct=None, eupsProductPath=None):
    """Recursively configure a package using ups/.cfg files."""
    if eupsProduct is None:
        eupsProduct = packageName
    state.env['eupsProduct'] = eupsProduct
    state.env['packageName'] = packageName
    #
    # Setup installation directories and variables
    #
    SCons.Script.Help(state.opts.GenerateHelpText(state.env))
    state.env.installing = filter(lambda t: t == "install", SCons.Script.BUILD_TARGETS) 
    state.env.declaring = filter(lambda t: t == "declare" or t == "current", SCons.Script.BUILD_TARGETS)
    prefix = installation.setPrefix(state.env, versionString, eupsProductPath)
    state.env['prefix'] = prefix
    state.env["libDir"] = "%s/lib" % prefix
    state.env["pythonDir"] = "%s/python" % prefix
    if state.env.installing:
        SCons.progress_display("Installing into %s" % prefix)
    #
    # Process dependencies
    #
    state.log.traceback = state.env.GetOption("traceback")
    state.log.verbose = state.env.GetOption("verbose")
    packages = PackageTree(packageName)
    state.log.flush() # if we've already hit a fatal error, die now.
    state.env.libs = {"main":[], "python":[], "test":[]}
    state.env.doxygen = {"tags":[], "includes":[]}
    state.env['CPPPATH'] = []
    state.env['LIBPATH'] = []
    state.env['XCPPPATH'] = []
    if not state.env.GetOption("clean") and not state.env.GetOption("help"):
        packages.configure(state.env, check=state.env.GetOption("checkDependencies"))
        for target in state.env.libs:
            state.log.info("Libraries in target '%s': %s" % (target, state.env.libs[target]))
    state.env.dependencies = packages
    state.log.flush()

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

class Configuration(object):
    """Base class for defining how to configure an LSST sconsUtils package.

    An ups/*.cfg file should contain an instance of this class called
    "config".  Most LSST packages will be able to use this class directly
    instead of subclassing it.

    The only important method is configure(), which modifies an SCons
    environment to use the package.  If a subclass overrides configure,
    it may not need to call the base class __init__(), whose only
    purpose is to define a number of instance variables used by configure().
    """

    @staticmethod
    def parseFilename(cfgFile):
        """Parse the name of a .cfg, returning the package name and root directory."""
        dir, file = os.path.split(cfgFile)
        name, ext = os.path.splitext(file)
        return name, os.path.abspath(os.path.join(dir, ".."))

    def __init__(self, cfgFile, headers=(), libs=None, hasSwigFiles=True,
                 hasDoxygenInclude=False, hasDoxygenTag=True):
        """Initialize the configuration object.

        @param cfgFile  The name of the calling .cfg file, usually just passed in with the special
                        variable __file__.  This will be parsed to extract the package name and root.
        @param headers  A list of headers provided by the package, to be used in autoconf-style tests.
        @param libs     A list or dictionary of libraries provided by the package.  If a dictionary
                        is provided, libs["main"] should contain a list of regular libraries provided
                        by the library.  Other keys are "python" and "test", which refer to libraries
                        that are only linked against compiled Python modules and unit tests, respectively.
                        If a list is provided, the list is used as "main".  These are used both for
                        autoconf-style tests and to support env.getLib(...), which recursively computes
                        the libraries a package must be linked with.
        @param hasSwigFiles        If True, the package provides SWIG interface files in "<root>/python".
        @param hasDoxygenInclude   If True, the package provides a Doxygen include file with the
                                   name "<root>/doc/<name>.inc".
        @param hasDoxygenTag       If True, the package generates a Doxygen TAG file.
        """
        self.name, self.root = self.parseFilename(cfgFile)
        self.paths = {
            # Sequence of include path for headers provided by this package
            "CPPPATH": [os.path.join(self.root, "include")],
            # Sequence of library path for libraries provided by this package
            "LIBPATH": [os.path.join(self.root, "lib")],
            # Sequence of SWIG include paths for .i files provided by this package
            "SWIGPATH": ([os.path.join(self.root, "python")]
                         if hasSwigFiles else [])
            }
        self.doxygen = {
            # Doxygen tag files generated by this package
            "tags": ([os.path.join(self.root, "doc", "%s.tag" % self.name)]
                     if hasDoxygenTag else []),
            # Doxygen include files to include in the configuration of dependent products
            "includes": ([os.path.join(self.root, "doc", "%s.inc" % self.name)]
                         if hasDoxygenInclude else [])
            }
        if libs is None:
            self.libs = {
                # Normal libraries provided by this package
                "main": [self.name],
                # Libraries provided that should only be linked with Python modules
                "python":[],
                # Libraries provided that should only be linked with unit test code
                "test":[],
                }
        elif "main" in libs:
            self.libs = libs
        else:
            self.libs = {"main": libs, "python": [], "test": []}
        self.provides = {
            "headers": tuple(headers),
            "libs": tuple(self.libs["main"])
            }

    def configure(self, conf, packages, check=False, build=True):
        """
        Update an SCons environment to make use of the package.

        Arguments:
        @param conf      An SCons Configure context.  The SCons Environment conf.env should be updated
                         by the configure function.
        @param packages  A dictionary containing the configuration modules of all dependencies (or None if
                         the dependency was optional and was not found).  The <module>.config.configure(...)
                         method will have already been called on all dependencies.
        @param check     If True, perform autoconf-style tests to verify that key components are in
                         fact in place.
        @param build     If True, this is the package currently being built, and packages in
                         "buildRequired" and "buildOptional" dependencies will also be present in
                         the packages dict.
        """
        assert(not (check and build))
        conf.env.PrependUnique(**self.paths)
        state.log.info("Configuring package '%s'." % self.name)
        conf.env.doxygen["includes"].extend(self.doxygen["includes"])
        if not build:
            conf.env.doxygen["tags"].extend(self.doxygen["tags"])
        for target in self.libs:
            if target not in conf.env.libs:
                conf.env.libs[target] = lib[target].copy()
                state.log.info("Adding '%s' libraries to target '%s'." % (self.libs[target], target))
            else:
                for lib in self.libs[target]:
                    if lib not in conf.env.libs[target]:
                        conf.env.libs[target].append(lib)
                        state.log.info("Adding '%s' library to target '%s'." % (lib, target))
        if check:
            for header in self.provides["headers"]:
                if not conf.CheckCXXHeader(header): return False
            for lib in self.libs["main"]:
                if not conf.CheckLib(lib, autoadd=False, language="C++"): return False
        return True

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

class ExternalConfiguration(Configuration):
    """Configuration subclass that doesn't assume, the package uses SWIG or Doxygen,
    and tells SCons not to consider header files this package provides as dependencies.

    This means things won't rebuild automatically if you change which version of a package
    is setup, but SCons won't waste time looking for changes in it every time you build.
    """

    def __init__(self, cfgFile, headers=(), libs=None):
        """Initialize the configuration object.

        @param cfgFile  The name of the calling .cfg file, usually just passed in with the special
                        variable __file__.  This will be parsed to extract the package name and root.
        @param headers  A list of headers provided by the package, to be used in autoconf-style tests.
        @param libs     A list or dictionary of libraries provided by the package.  If a dictionary
                        is provided, libs["main"] should contain a list of regular libraries provided
                        by the library.  Other keys are "python" and "test", which refer to libraries
                        that are only linked against compiled Python modules and unit tests, respectively.
                        If a list is provided, the list is used as "main".  These are used both for
                        autoconf-style tests and to support env.getLib(...), which recursively computes
                        the libraries a package must be linked with.
        """
        Configuration.__init__(self, cfgFile, headers, libs, hasSwigFiles=False,
                               hasDoxygenTag=False, hasDoxygenInclude=False)
        # XCPPPATHS is like CPPPATHS, but we add it to CCFLAGS manually after 
        self.paths["XCPPPATH"] = self.paths["CPPPATH"]
        del self.paths["CPPPATH"]

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

class PackageTree(object):
    """A class for loading and managing the dependency tree of a package, as defined by its
    configuration module (.cfg) file.

    This tree isn't actually stored as a tree; it's flattened into an ordered dictionary
    as it is recursively loaded.
    """

    def __init__(self, primaryName):
        """Recursively load *.cfg files for packageName and all its dependencies.

        @param primaryName      The name of the primary package being built.

        After __init__, self.primary will be set to the configuration module for the primary package,
        and self.packages will be an OrderedDict of dependencies (excluding self.primary), ordered
        such that configuration can proceed in iteration order.
        """
        self.upsDirs = state.env.upsDirs
        self.packages = collections.OrderedDict()
        self.primary = self._tryImport(primaryName)
        if self.primary is None: fail("Failed to load primary package configuration.")
        for dependency in self.primary.dependencies.get("required", ()):
            if not self._recurse(dependency): state.log.fail("Failed to load required dependencies.")
        for dependency in self.primary.dependencies.get("buildRequired", ()):
            if not self._recurse(dependency): state.log.fail("Failed to load required build dependencies.")
        for dependency in self.primary.dependencies.get("optional", ()):
            self._recurse(dependency)
        for dependency in self.primary.dependencies.get("buildOptional", ()):
            self._recurse(dependency)

    name = property(lambda self: self.primary.config.name)

    def configure(self, env, check=False):
        """Configure the entire dependency tree in order. and return an updated environment."""
        conf = env.Configure()
        for name, module in self.packages.iteritems():
            if module is None:
                state.log.info("Skipping missing optional package %s." % name)
                continue
            if not module.config.configure(conf, packages=self.packages, check=check, build=False):
                state.log.fail("%s was found but did not pass configuration checks." % name)
        self.primary.config.configure(conf, packages=self.packages, check=False, build=True)
        env.AppendUnique(SWIGPATH=env["CPPPATH"])
        xccflags = [env["INCPREFIX"] + i + env["INCSUFFIX"] for i in env["XCPPPATH"]]
        env.Append(CCFLAGS=xccflags, SWIGFLAGS=xccflags)
        env = conf.Finish()
        return env

    def __contains__(self, name):
        return name == self.name or name in self.packages

    has_key = __contains__

    def __getitem__(self, name):
        if name == self.name:
            return self.primary
        else:
            return self.packages[name]

    def get(self, name, default=None):
        if name == self.name:
            return self.primary
        else:
            return self.packages.get(name)

    def keys(self):
        k = self.packages.keys()
        k.append(self.name)
        return k

    def _tryImport(self, name):
        """Search for and import an individual configuration module from file."""
        for path in self.upsDirs:
            filename = os.path.join(path, name + ".cfg")
            if os.path.exists(filename):
                state.log.info("Using configuration for package '%s' at '%s'." % (name, filename))
                module = imp.load_source(name + "_cfg", filename)
                if not hasattr(module, "dependencies") or not isinstance(module.dependencies, dict):
                    state.log.warn("Configuration module for package '%s' lacks a dependencies dict." % name)
                    return
                if not hasattr(module, "config") or not isinstance(module.config, Configuration):
                    state.log.warn("Configuration module for package '%s' lacks a config object." % name)
                    return
                return module
        state.log.warn("Failed to import configuration for package '%s'." % name)

    def _recurse(self, name):
        """Recursively load a dependency."""
        if name in self.packages:
            return self.packages[name] is not None
        module = self._tryImport(name)
        if module is None:
            self.packages[name] = None
            return False
        for dependency in module.dependencies.get("required", ()):
            if not self._recurse(dependency):
                # We can't configure this package because a required dependency wasn't found.
                # But this package might itself be optional, so we don't die yet.
                self.packages[name] = None
                state.log.warn("Could not load all dependencies for package '%s'." % name)
                return False
        for dependency in module.dependencies.get("optional", ()):
            self._recurse(dependency)
        # This comes last to ensure the ordering puts all dependencies first.
        self.packages[name] = module
        return True

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def getLibs(env, targets="main"):
    """Get the libraries the package should be linked with.

    Arguments:
       targets --- A string containing whitespace-delimited targets.  Standard
                   targets are "main", "python", and "test".  Default is "main".
                   A special virtual target "self" can be provided, returning
                   the results of targets="main" with the eups_target library
                   removed.

    Typically, main libraries will be linked with LIBS=getLibs("self"),
    Python modules will be linked with LIBS=getLibs("main python") and
    C++-coded test programs will be linked with LIBS=getLibs("main test")
    """
    libs = []
    removeSelf = False
    for target in targets.split():
        if target == "self":
            target = "main"
            removeSelf = True
        for lib in env.libs[target]:
            if lib not in libs:
                libs.append(lib)
    if removeSelf:
        try:
            libs.remove(env["eupsProduct"])
        except ValueError:
            pass
    return libs

SConsEnvironment.getLibs = getLibs