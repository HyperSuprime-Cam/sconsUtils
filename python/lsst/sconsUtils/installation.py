#
# Note that this file is called SConsUtils.py not SCons.py so as to allow us to import SCons
#
import os.path
import glob
import re
import sys

import SCons.Script
from SCons.Script.SConscript import SConsEnvironment

from .vcs import svn
from .vcs import hg

from . import state
from .utils import memberOf

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def makeProductPath(env, pathFormat):
    """return a path to use as the installation directory for a product
    @param pathFormat     the format string to process 
    @param env            the scons environment
    @param versionString  the versionString passed to MakeEnv
    """
    pathFormat = re.sub(r"%(\w)", r"%(\1)s", pathFormat)
    
    eupsPath = os.environ['PWD']
    if env.has_key('eupsProduct') and env['eupsPath']:
        eupsPath = env['eupsPath']

    return pathFormat % { "P": eupsPath,
                          "f": env['eupsFlavor'],
                          "p": env['eupsProduct'],
                          "v": env['version'],
                          "c": os.environ['PWD'] }
    
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def getVersion(env, versionString):
    """Set a version ID from env, or
    a cvs or svn ID string (dollar name dollar or dollar HeadURL dollar)"""

    version = "unknown"

    if env.has_key('version'):
        version = env['version']
        if env.has_key('baseversion') and \
                not version.startswith(env['baseversion']):
            utils.log.warn("Explicit version %s is incompatible with baseversion %s"
                           % (version, env['baseversion']))
    elif not versionString:
        version = "unknown"
    elif re.search(r"^[$]Name:\s+", versionString):
        # CVS.  Extract the tagname
        version = re.search(r"^[$]Name:\s+([^ $]*)", versionString).group(1)
        if version == "":
            version = "cvs"
    elif re.search(r"^[$]HeadURL:\s+", versionString):
        # SVN.  Guess the tagname from the last part of the directory
        HeadURL = re.search(r"^[$]HeadURL:\s+(.*)", versionString).group(1)
        HeadURL = os.path.split(HeadURL)[0]
        if env.installing or env.declaring:
            try:
                version = svn.guessVersionName(HeadURL)
            except RuntimeError as err:
                if env['force']:
                    version = "unknown"
                else:
                    state.log.fail(
                        "%s\nFound problem with svn revision number; update or specify force=True to proceed"
                        % err
                        )
            if env.has_key('baseversion'):
                version = env['baseversion'] + "+" + version
    elif versionString.lower() in ("hg", "mercurial"):
        # Mercurial (hg).
        try:
            version = hg.guessVersionName()
        except RuntimeError as err:
            if env['force']:
                version = "unknown"
            else:
                state.log.fail(
                    "%s\nFound problem with hg version; update or specify force=True to proceed" % e
                    )
    state.log.flush()
    env["version"] = version
    return version

def setPrefix(env, versionString, eupsProductPath=None):
    """Set a prefix based on the EUPS_PATH, the product name, and a versionString from cvs or svn."""
    if eupsProductPath:
        getVersion(env, versionString)
        eupsPrefix = makeProductPath(env, eupsProductPath)
    elif env.has_key('eupsPath') and env['eupsPath']:
        eupsPrefix = env['eupsPath']
	flavor = env['eupsFlavor']
	if not re.search("/" + flavor + "$", eupsPrefix):
	    eupsPrefix = os.path.join(eupsPrefix, flavor)
        prodPath = env['eupsProduct']
        if env.has_key('eupsProductPath') and env['eupsProductPath']:
            prodPath = env['eupsProductPath']
        eupsPrefix = os.path.join(eupsPrefix, prodPath, getVersion(env, versionString))
    else:
        eupsPrefix = None
    if env.has_key('prefix'):
        if getVersion(env, versionString) != "unknown" and eupsPrefix and eupsPrefix != env['prefix']:
            print >> sys.stderr, "Ignoring prefix %s from EUPS_PATH" % eupsPrefix
        return makeProductPath(env, env['prefix'])
    elif env.has_key('eupsPath') and env['eupsPath']:
        prefix = eupsPrefix
    else:
        prefix = "/usr/local"
    return prefix

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

@memberOf(SConsEnvironment)
def Declare(self, products=None):
    """Create current and declare targets for products.  products
    may be a list of (product, version) tuples.  If product is None
    it's taken to be self['eupsProduct']; if version is None it's
    taken to be self['version'].
    
    We'll add Declare to class Environment"""

    if "undeclare" in SCons.Script.COMMAND_LINE_TARGETS and not self.GetOption("silent"):
        state.log.warn("'scons undeclare' is deprecated; please use 'scons declare -c' instead")
    if \
           "declare" in SCons.Script.COMMAND_LINE_TARGETS or \
           "undeclare" in SCons.Script.COMMAND_LINE_TARGETS or \
           ("install" in SCons.Script.COMMAND_LINE_TARGETS and self.GetOption("clean")) or \
           "current" in SCons.Script.COMMAND_LINE_TARGETS:
        current = []; declare = []; undeclare = []

        if not products:
            products = [None]

        for prod in products:
            if not prod or isinstance(prod, str):   # i.e. no version
                product = prod

                if self.has_key('version'):
                    version = self['version']
                else:
                    version = None
            else:
                product, version = prod

            if not product:
                product = self['eupsProduct']

            if "EUPS_DIR" in os.environ.keys():
                self['ENV']['PATH'] += os.pathsep + "%s/bin" % (os.environ["EUPS_DIR"])

                if "undeclare" in SCons.Script.COMMAND_LINE_TARGETS or self.GetOption("clean"):
                    if version:
                        command = "eups undeclare --flavor %s %s %s" % \
                                  (self['eupsFlavor'], product, version)
                        if ("current" in SCons.Script.COMMAND_LINE_TARGETS 
                            and not "declare" in SCons.Script.COMMAND_LINE_TARGETS):
                            command += " --current"
                            
                        if self.GetOption("clean"):
                            self.Execute(command)
                        else:
                            undeclare += [command]
                    else:
                        state.log.warn("I don't know your version; not undeclaring to eups")
                else:
                    command = "eups declare --force --flavor %s --root %s" % \
                              (self['eupsFlavor'], self['prefix'])

                    if self.has_key('eupsPath'):
                        command += " -Z %s" % self['eupsPath']
                        
                    if version:
                        command += " %s %s" % (product, version)

                    current += [command + " --current"]
                    declare += [command]

        if current:
            self.Command("current", "", action=current)
        if declare:
            if "current" in SCons.Script.COMMAND_LINE_TARGETS:
                self.Command("declare", "", action="") # current will declare it for us
            else:
                self.Command("declare", "", action=declare)
        if undeclare:
            self.Command("undeclare", "", action=undeclare)

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

@memberOf(SConsEnvironment)
def InstallDir(self, prefix, dir, ignoreRegex=r"(~$|\.pyc$|\.os?$)", recursive=True):
    """
    Install the directory dir into prefix, (along with all its descendents if recursive is True).
    Omit files and directories that match ignoreRegex

    Unless force is true, this routine won't do anything unless you specified an "install" target
    """

    if not self.installing:
        return

    targets = []
    for dirpath, dirnames, filenames in os.walk(dir):
        if not recursive:
            dirnames[:] = []
        else:
            dirnames[:] = [d for d in dirnames if d != ".svn"] # ignore .svn tree
        #
        # List of possible files to install
        #
        for f in filenames:
            if re.search(ignoreRegex, f):
                continue

            targets += self.Install(os.path.join(prefix, dirpath), os.path.join(dirpath, f))

    return targets

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

@memberOf(SConsEnvironment)
def InstallEups(env, dest, files=[], presetup=""):
    """Install a ups directory, setting absolute versions as appropriate
    (unless you're installing from the trunk, in which case no versions
    are expanded).  Any build/table files present in "./ups" are automatically
    added to files.
    
    If presetup is provided, it's expected to be a dictionary with keys
    product names and values the version that should be installed into
    the table files, overriding eups expandtable's usual behaviour. E.g.
    env.InstallEups(os.path.join(env['prefix'], "ups"), presetup={"sconsUtils" : env['version']})
    """

    if not env.installing:
        return

    if env.GetOption("clean"):
        print >> sys.stderr, "Removing", dest
        shutil.rmtree(dest, ignore_errors=True)
    else:
        presetupStr = []
        for p in presetup:
            presetupStr += ["--product %s=%s" % (p, presetup[p])]
        presetup = " ".join(presetupStr)

        env = env.Clone(ENV = os.environ)
        #
        # Add any build/table files to the desired files
        #
        files = [str(f) for f in files] # in case the user used Glob not glob.glob
        files += glob.glob(os.path.join("ups", "*.build")) + glob.glob(os.path.join("ups","*.table"))
        files = list(set(files))        # remove duplicates

        buildFiles = filter(lambda f: re.search(r"\.build$", f), files)
        build_obj = env.Install(dest, buildFiles)
        
        tableFiles = filter(lambda f: re.search(r"\.table$", f), files)
        table_obj = env.Install(dest, tableFiles)

        miscFiles = filter(lambda f: not re.search(r"\.(build|table)$", f), files)
        misc_obj = env.Install(dest, miscFiles)

        for i in build_obj:
            env.AlwaysBuild(i)

            cmd = "eups expandbuild -i --version %s %s" % (env['version'], str(i))
            env.AddPostAction(i, Action("%s" %(cmd), cmd, ENV = os.environ))

        for i in table_obj:
            env.AlwaysBuild(i)

            cmd = "eups expandtable -i -W '^(?!LOCAL:)' " # version doesn't start "LOCAL:"
            if presetup:
                cmd += presetup + " "
            cmd += str(i)

            env.AddPostAction(i, Action("%s" %(cmd), cmd, ENV = os.environ))

    return dest

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

@memberOf(SConsEnvironment)
def InstallLSST(self, prefix, dirs, ignoreRegex=None):
    """Install directories in the usual LSST way, handling "doc" and "ups" specially"""
    
    for d in dirs:
        if d == "ups":
            t = self.InstallEups(os.path.join(prefix, "ups"))
        else:
            t = self.InstallDir(prefix, d, ignoreRegex=ignoreRegex)

        self.Alias("install", t)
            
    self.Clean("install", prefix)