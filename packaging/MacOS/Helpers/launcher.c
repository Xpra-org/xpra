/*
 * This file is part of Xpra.
 * Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option,
 * any later version. See the file COPYING for details.
 *
 * Minimal embedded-Python launcher for the macOS .app bundle.
 *
 * The bundle's Contents/MacOS/Xpra (and Contents/Helpers/<name>) must be a
 * real Mach-O binary so that NSBundle.mainBundle() resolves to the .app and
 * is_app_bundle() returns True. A shell script that exec's Python does not
 * satisfy this: by the time Python runs, _NSGetExecutablePath returns the
 * Python interpreter path inside Frameworks/, not Contents/MacOS/.
 *
 * This launcher does the minimum required to start Python:
 *   - resolve own path, locate Contents/
 *   - export XPRA_BUNDLE_CONTENTS, PYTHONHOME, PYTHONPATH, PYTHONDONTWRITEBYTECODE
 *   - look up the entry module from argv[0] basename
 *   - call Py_BytesMain
 *
 * Everything else (GTK / GStreamer / typelib / locale env, debug-file handling)
 * is intentionally handled in xpra/platform/darwin/__init__.py so the launcher
 * stays a thin shim.
 */

#include <Python.h>
#include <libgen.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/param.h>
#include <unistd.h>

static char *find_contents_dir(const char *exe_path) {
    /* Walk parents of exe_path and return the first one named "Contents". */
    char *path = strdup(exe_path);
    char *result = NULL;
    while (path) {
        char *slash = strrchr(path, '/');
        if (!slash || slash == path) break;
        *slash = '\0';
        const char *last = strrchr(path, '/');
        if (!last) break;
        if (strcmp(last + 1, "Contents") == 0) {
            result = strdup(path);
            break;
        }
    }
    free(path);
    return result;
}

static int read_module_file(const char *path, char *out, size_t out_size) {
    FILE *fp = fopen(path, "r");
    if (!fp) return -1;
    if (!fgets(out, (int)out_size, fp)) {
        fclose(fp);
        return -1;
    }
    fclose(fp);
    size_t len = strlen(out);
    while (len > 0 && (out[len-1] == '\n' || out[len-1] == '\r' ||
                       out[len-1] == ' '  || out[len-1] == '\t')) {
        out[--len] = '\0';
    }
    return len > 0 ? 0 : -1;
}

int main(int argc, char **argv) {
    char raw_exe[PATH_MAX];
    uint32_t raw_size = sizeof(raw_exe);
    if (_NSGetExecutablePath(raw_exe, &raw_size) != 0) {
        fprintf(stderr, "launcher: executable path buffer too small\n");
        return 1;
    }
    /* dyld resolves @rpath at load time using the LC_RPATH baked into this
     * binary (@executable_path/../Frameworks). All bundled dylibs use either
     * @rpath or @loader_path references, so library resolution works without
     * setting DYLD_LIBRARY_PATH. The sign-app.sh step applies hardened
     * runtime (--options runtime), under which DYLD_* env vars are silently
     * stripped anyway, so any setenv()-based shim would be a no-op. */
    char exe_path[PATH_MAX];
    if (!realpath(raw_exe, exe_path)) {
        /* realpath would resolve symlinks/hardlinks back to the original
         * inode's "canonical" path, which loses the helper name. Fall back
         * to the raw invocation path. */
        strncpy(exe_path, raw_exe, sizeof(exe_path) - 1);
        exe_path[sizeof(exe_path) - 1] = '\0';
    }
    /* For hardlinks the canonical path collapses all aliases to a single
     * name, so always prefer the un-resolved invocation path for the
     * helper name (the kernel reports the actual filename used to launch). */
    char *invocation = strdup(raw_exe);
    char *helper_name = basename(invocation);

    char *contents = find_contents_dir(raw_exe);
    if (!contents) {
        fprintf(stderr, "launcher: cannot locate Contents/ above %s\n", raw_exe);
        return 1;
    }

    char buf[PATH_MAX * 4];
    setenv("XPRA_BUNDLE_CONTENTS", contents, 1);
    snprintf(buf, sizeof(buf), "%s/Resources", contents);
    setenv("PYTHONHOME", buf, 1);
    /* Override libgio's compiled-in jhbuild module directory before Python
     * imports GIO. Host modules can fail hardened runtime library validation. */
    snprintf(buf, sizeof(buf), "%s/Resources/lib/gio/modules", contents);
    setenv("GIO_MODULE_DIR", buf, 1);
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
    /* Block user site-packages: a stray PYTHONUSERBASE in the user's shell
     * (e.g. jhbuild) would otherwise add a site-packages dir whose modules
     * link against the host GLib stack and clash with the bundled one. */
    setenv("PYTHONNOUSERSITE", "1", 1);

    char bundle_lib[PATH_MAX];
    snprintf(bundle_lib, sizeof(bundle_lib), "%s/Resources/lib", contents);
    snprintf(buf, sizeof(buf),
        "%s:%s/python/lib-dynload:%s/python/site-packages.zip:%s/python",
        bundle_lib, bundle_lib, bundle_lib, bundle_lib);
    setenv("PYTHONPATH", buf, 1);

    char module[256];
    char modfile[PATH_MAX];
    snprintf(modfile, sizeof(modfile),
             "%s/Resources/share/xpra/helpers/%s", contents, helper_name);
    if (read_module_file(modfile, module, sizeof(module)) != 0) {
        fprintf(stderr, "launcher: cannot read entry module from %s\n", modfile);
        return 1;
    }

    /* Python -c invocation. xpra.scripts.main.main(script_file, cmdline)
     * takes two args; every other module takes a single argv list. */
    char code[PATH_MAX + 512];
    snprintf(code, sizeof(code),
        "import sys;sys.argv[0]='%s';"
        "from %s import main;"
        "sys.exit(main(sys.argv))",
        exe_path, module);

    int new_argc = argc + 2;
    char **new_argv = calloc((size_t)new_argc + 1, sizeof(char *));
    new_argv[0] = helper_name;
    new_argv[1] = "-c";
    new_argv[2] = code;
    for (int i = 1; i < argc; i++) {
        new_argv[i + 2] = argv[i];
    }

    int rc = Py_BytesMain(new_argc, new_argv);

    free(new_argv);
    free(contents);
    free(invocation);
    return rc;
}
