# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path

from xpra.os_util import OSX, POSIX, shellsub, getuid, getgid
from xpra.platform.dotxpra import osexpand, norm_makepath
from xpra.scripts.config import InitException


def add_cleanup(fn):
    from xpra.scripts.server import add_cleanup
    add_cleanup(fn)

def sh_quotemeta(s):
    return "'" + s.replace("'", "'\\''") + "'"

def xpra_runner_shell_script(xpra_file, starting_dir, socket_dir):
    script = []
    script.append("#!/bin/sh\n")
    for var, value in os.environ.items():
        # these aren't used by xpra, and some should not be exposed
        # as they are either irrelevant or simply do not match
        # the new environment used by xpra
        # TODO: use a whitelist
        if var in ["XDG_SESSION_COOKIE", "LS_COLORS", "DISPLAY"]:
            continue
        #XPRA_SOCKET_DIR is a special case, it is handled below
        if var=="XPRA_SOCKET_DIR":
            continue
        if var.startswith("BASH_FUNC"):
            #some versions of bash will apparently generate functions
            #that cannot be reloaded using this script
            continue
        # :-separated envvars that people might change while their server is
        # going:
        if var in ("PATH", "LD_LIBRARY_PATH", "PYTHONPATH"):
            #prevent those paths from accumulating the same values multiple times,
            #only keep the first one:
            pval = value.split(os.pathsep)      #ie: ["/usr/bin", "/usr/local/bin", "/usr/bin"]
            seen = set()
            value = os.pathsep.join(x for x in pval if not (x in seen or seen.add(x)))
            script.append("%s=%s:\"$%s\"; export %s\n"
                          % (var, sh_quotemeta(value), var, var))
        else:
            script.append("%s=%s; export %s\n"
                          % (var, sh_quotemeta(value), var))
    #XPRA_SOCKET_DIR is a special case, we want to honour it
    #when it is specified, but the client may override it:
    if socket_dir:
        script.append('if [ -z "${XPRA_SOCKET_DIR}" ]; then\n');
        script.append('    XPRA_SOCKET_DIR=%s; export XPRA_SOCKET_DIR\n' % sh_quotemeta(os.path.expanduser(socket_dir)))
        script.append('fi\n');
    # We ignore failures in cd'ing, b/c it's entirely possible that we were
    # started from some temporary directory and all paths are absolute.
    script.append("cd %s\n" % sh_quotemeta(starting_dir))
    if OSX:
        #OSX contortions:
        #The executable is the python interpreter,
        #which is execed by a shell script, which we have to find..
        sexec = sys.executable
        bini = sexec.rfind("Resources/bin/")
        if bini>0:
            sexec = os.path.join(sexec[:bini], "Resources", "MacOS", "Xpra")
        script.append("_XPRA_SCRIPT=%s\n" % (sh_quotemeta(sexec),))
        script.append("""
if which "$_XPRA_SCRIPT" > /dev/null; then
    # Happypath:
    exec "$_XPRA_SCRIPT" "$@"
else
    # Hope for the best:
    exec Xpra "$@"
fi
""")
    else:
        script.append("_XPRA_PYTHON=%s\n" % (sh_quotemeta(sys.executable),))
        script.append("_XPRA_SCRIPT=%s\n" % (sh_quotemeta(xpra_file),))
        script.append("""
if which "$_XPRA_PYTHON" > /dev/null && [ -e "$_XPRA_SCRIPT" ]; then
    # Happypath:
    exec "$_XPRA_PYTHON" "$_XPRA_SCRIPT" "$@"
else
    cat >&2 <<END
    Could not find one or both of '$_XPRA_PYTHON' and '$_XPRA_SCRIPT'
    Perhaps your environment has changed since the xpra server was started?
    I'll just try executing 'xpra' with current PATH, and hope...
END
    exec xpra "$@"
fi
""")
    return "".join(script)

def write_runner_shell_scripts(contents, overwrite=True):
    # This used to be given a display-specific name, but now we give it a
    # single fixed name and if multiple servers are started then the last one
    # will clobber the rest.  This isn't great, but the tradeoff is that it
    # makes it possible to use bare 'ssh:hostname' display names and
    # autodiscover the proper numeric display name when only one xpra server
    # is running on the remote host.  Might need to revisit this later if
    # people run into problems or autodiscovery turns out to be less useful
    # than expected.
    from xpra.log import Logger
    log = Logger("server")
    from xpra.platform.paths import get_script_bin_dirs
    for d in get_script_bin_dirs():
        scriptdir = osexpand(d)
        if not os.path.exists(scriptdir):
            try:
                os.mkdir(scriptdir, 0o700)
            except Exception as e:
                log.warn("Warning: failed to write script file in '%s':", scriptdir)
                log.warn(" %s", e)
                if scriptdir.startswith("/var/run/user") or scriptdir.startswith("/run/user"):
                    log.warn(" ($XDG_RUNTIME_DIR has not been created?)")
                continue
        scriptpath = os.path.join(scriptdir, "run-xpra")
        if os.path.exists(scriptpath) and not overwrite:
            continue
        # Write out a shell-script so that we can start our proxy in a clean
        # environment:
        try:
            with open(scriptpath, "w") as scriptfile:
                # Unix is a little silly sometimes:
                umask = os.umask(0)
                os.umask(umask)
                os.fchmod(scriptfile.fileno(), 0o700 & ~umask)
                scriptfile.write(contents)
        except Exception as e:
            log.error("Error: failed to write script file '%s':", scriptpath)
            log.error(" %s\n", e)


def find_log_dir(username="", uid=0, gid=0):
    from xpra.platform.paths import get_default_log_dirs
    errs  = []
    for x in get_default_log_dirs():
        v = osexpand(x, username, uid, gid)
        if not os.path.exists(v):
            if getuid()==0 and uid!=0:
                continue
            try:
                os.mkdir(v, 0o700)
            except Exception as e:
                errs.append((v, e))
                continue
        return v
    for d, e in errs:
        sys.stderr.write("Error: cannot create log directory '%s':" % d)
        sys.stderr.write(" %s\n" % e)
    return None


def open_log_file(logpath):
    """ renames the existing log file if it exists,
        then opens it for writing.
    """
    if os.path.exists(logpath):
        try:
            os.rename(logpath, logpath + ".old")
        except:
            pass
    try:
        return os.open(logpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    except OSError as e:
        raise InitException("cannot open log file '%s': %s" % (logpath, e))

def select_log_file(log_dir, log_file, display_name):
    """ returns the log file path we should be using given the parameters,
        this may return a temporary logpath if display_name is not available.
    """
    if log_file:
        if os.path.isabs(log_file):
            logpath = log_file
        else:
            logpath = os.path.join(log_dir, log_file)
        v = shellsub(logpath, {"DISPLAY" : display_name})
        if display_name or v==logpath:
            #we have 'display_name', or we just don't need it:
            return v
    if display_name:
        logpath = norm_makepath(log_dir, display_name) + ".log"
    else:
        logpath = os.path.join(log_dir, "tmp_%d.log" % os.getpid())
    return logpath

def redirect_std_to_log(logfd):
    from xpra.os_util import close_all_fds
    # save current stdout/stderr to be able to print info
    # before exiting the non-deamon process
    # and closing those file descriptors definitively
    old_fd_stdout = os.dup(1)
    old_fd_stderr = os.dup(2)
    close_all_fds(exceptions=[logfd, old_fd_stdout, old_fd_stderr])
    fd0 = os.open("/dev/null", os.O_RDONLY)
    if fd0 != 0:
        os.dup2(fd0, 0)
        os.close(fd0)
    # reopen STDIO files
    stdout = os.fdopen(old_fd_stdout, "w", 1)
    stderr = os.fdopen(old_fd_stderr, "w", 1)
    # replace standard stdout/stderr by the log file
    os.dup2(logfd, 1)
    os.dup2(logfd, 2)
    os.close(logfd)
    # Make these line-buffered:
    sys.stdout = os.fdopen(1, "w", 1)
    sys.stderr = os.fdopen(2, "w", 1)
    return stdout, stderr


def daemonize():
    os.chdir("/")
    if os.fork():
        os._exit(0)
    os.setsid()
    if os.fork():
        os._exit(0)


def write_pidfile(pidfile, uid, gid):
    from xpra.log import Logger
    log = Logger("server")
    pidstr = str(os.getpid())
    try:
        with open(pidfile, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write("%s\n" % pidstr)
            try:
                inode = os.fstat(f.fileno()).st_ino
            except:
                inode = -1
            if POSIX and uid!=getuid() or gid!=getgid():
                try:
                    os.fchown(f.fileno(), uid, gid)
                except:
                    pass
        log.info("wrote pid %s to '%s'", pidstr, pidfile)
        def cleanuppidfile():
            #verify this is the right file!
            log("cleanuppidfile: inode=%i", inode)
            if inode>0:
                try:
                    i = os.stat(pidfile).st_ino
                    log("cleanuppidfile: current inode=%i", i)
                    if i!=inode:
                        return
                except:
                    pass
            try:
                os.unlink(pidfile)
            except:
                pass
        add_cleanup(cleanuppidfile)
    except Exception as e:
        log.error("Error: failed to write pid %i to pidfile '%s':", os.getpid(), pidfile)
        log.error(" %s", e)
