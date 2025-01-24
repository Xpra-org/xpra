#!/usr/bin/env python3

# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import shlex
import sys
import glob
import shutil

from xpra.os_util import WIN32
from xpra.util.io import get_status_output
from xpra.util.str_fn import sorted_nicely


def get_nvcc_version(command: str) -> tuple[int, ...]:
    if not os.path.exists(command):
        return None
    code, out, _ = get_status_output([command, "--version"])
    if code != 0:
        return None
    vpos = out.rfind(", V")
    if vpos > 0:
        version = out[vpos + 3:].split("\n")[0]
        version_str = f" version {version}"
    else:
        version = "0"
        version_str = " unknown version!"
    print(f"found CUDA compiler {command!r} : {version_str}")
    return tuple(int(x) for x in version.split("."))


def get_nvcc() -> [str, tuple[int, ...]]:
    path_options = os.environ.get("PATH", "").split(os.path.pathsep)
    if WIN32:
        nvcc_exe = "nvcc.exe"
        CUDA_DIR = os.environ.get("CUDA_DIR", "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA")
        path_options += ["./cuda/bin/"] + list(reversed(sorted_nicely(glob.glob(f"{CUDA_DIR}\\*\\bin"))))
    else:
        nvcc_exe = "nvcc"
        path_options += ["/usr/local/cuda/bin", "/opt/cuda/bin"]
        path_options += list(reversed(sorted_nicely(glob.glob("/usr/local/cuda*/bin"))))
        path_options += list(reversed(sorted_nicely(glob.glob("/opt/cuda*/bin"))))
    options = [os.path.join(x, nvcc_exe) for x in path_options]
    # prefer the one we find on the $PATH, if any:
    v = shutil.which(nvcc_exe)
    if v and (v not in options):
        options.insert(0, v)
    nvcc_versions = {}
    for filename in options:
        vnum = get_nvcc_version(filename)
        if vnum:
            nvcc_versions[vnum] = filename
    if not nvcc_versions:
        print("unable to find nvcc")
        sys.exit(1)
    # choose the most recent one:
    nvcc_version, nvcc = list(reversed(sorted(nvcc_versions.items())))[0]
    if len(nvcc_versions) > 1:
        print(f" using version {nvcc_version} from {nvcc}")
    return nvcc, nvcc_version


def get_gcc_version() -> tuple[int, ...]:
    CC = os.environ.get("CC", "gcc")
    if CC.find("clang") >= 0:
        return (0,)
    exit_code, _, err = get_status_output([CC, "-v"])
    if exit_code != 0:
        return (0,)
    V_LINE = "gcc version "
    gcc_version = []
    for line in err.splitlines():
        if not line.startswith(V_LINE):
            continue
        v_str = line[len(V_LINE):].strip().split(" ")[0]
        for p in v_str.split("."):
            try:
                gcc_version.append(int(p))
            except ValueError:
                break
        break
    return tuple(gcc_version)


def get_nvcc_args(nvcc: str, nvcc_version=(0, 0)) -> list[str]:
    if nvcc_version < (11, 6):
        raise RuntimeError(f"nvcc version {nvcc_version} is too old, minimum is 11.6")
    nvcc_cmd = [
        nvcc,
        "-fatbin",
        "-std=c++14",
        "-arch=all",
        "-Wno-deprecated-gpu-targets",
        "-Xnvlink",
        "-ignore-host-info",
        "--allow-unsupported-compiler",
    ]
    if get_gcc_version() >= (14, 0):
        clangpp = shutil.which("clang++")
        if not clangpp:
            print("clang++ not found, compilation may fail")
        else:
            nvcc_cmd.append(f"-ccbin={clangpp}")
    return nvcc_cmd


def main(args) -> int:
    nvcc, nvcc_version = get_nvcc()
    nvcc_args = get_nvcc_args(nvcc, nvcc_version)
    if len(args) == 1:
        kernels = (
            "XRGB_to_NV12", "XRGB_to_YUV444", "BGRX_to_NV12", "BGRX_to_YUV444",
            "BGRX_to_RGB", "RGBX_to_RGB", "RGBA_to_RGBAP", "BGRA_to_RGBAP",
        )
    else:
        kernels = args[1:]
    nvcc_commands = []
    print("compiling CUDA kernels with:")
    print(" " + " ".join(f"{x!r}" for x in nvcc_args))
    for kernel in kernels:
        cuda_src = f"fs/share/xpra/cuda/{kernel}.cu"
        cuda_bin = f"fs/share/xpra/cuda/{kernel}.fatbin"
        kbuild_cmd = nvcc_args + ["-c", cuda_src, "-o", cuda_bin]
        print(f"* {kernel}")
        nvcc_commands.append(kbuild_cmd)
    # parallel build:
    nvcc_errors = []

    def nvcc_compile(nvcc_cmd: list[str]) -> None:
        c, stdout, stderr = get_status_output(nvcc_cmd)
        if c != 0:
            nvcc_errors.append(c)
            print(f"Error: failed to compile CUDA kernel {kernel}")
            print(" using command:")
            print(f" {shlex.join(nvcc_cmd)}")
            print(stdout or "")
            print(stderr or "")

    nvcc_threads = []
    for cmd in nvcc_commands:
        from threading import Thread
        t = Thread(target=nvcc_compile, args=(cmd,))
        t.start()
        nvcc_threads.append(t)
    for t in nvcc_threads:
        if nvcc_errors:
            sys.exit(1)
        t.join()
    return len(nvcc_errors)


if __name__ == "__main__":
    r = main(sys.argv)
    sys.exit(r)
