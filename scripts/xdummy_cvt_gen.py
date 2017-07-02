#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import subprocess


def bytestostr(x):
    return str(x)
if sys.version > '3':
    unicode = str           #@ReservedAssignment
    def bytestostr(x):
        if type(x)==bytes:
            return x.decode("latin1")
        return str(x)


def get_status_output(*args, **kwargs):
    kwargs["stdout"] = subprocess.PIPE
    kwargs["stderr"] = subprocess.PIPE
    try:
        p = subprocess.Popen(*args, **kwargs)
    except Exception as e:
        print("error running %s,%s: %s" % (args, kwargs, e))
        return -1, "", ""
    stdout, stderr = p.communicate()
    return p.returncode, stdout, stderr

def get_output_lines(cmd):
    try:
        returncode, stdout, stderr = get_status_output(cmd, stdin=None, shell=False)
        if returncode!=0:
            print("'%s' failed with return code %s" % (cmd, returncode))
            print("stderr: %s" % stderr)
        elif not stdout:
            print("could not get command output")
        else:
            out = stdout.decode('utf-8')
            return out.splitlines()
    except:
        pass
    return  []


def gen_range(minw, maxw, wstep, minh, maxh, hstep):
    max_ratio = 3
    max_hz = 160
    for w in range(minw, maxw, wstep):
        for h in range(minh, maxh, hstep):
            if float(w)/float(h)>max_ratio or float(h)/float(w)>max_ratio:
                continue
            pixel_clock = 300*1000*1000 #300MHz target
            #theoretical pixel_clock = w*h*hz
            #overhead for safety margins (timings):
            margin = 25
            hz = pixel_clock // (w*h*(100+margin)//100)
            hz = min(max_hz, hz)
            if hz>100:
                hz = (hz//10)*10
            elif hz>50:
                hz = (hz//5)*5
            cmd = ["cvt", str(w), str(h), str(hz)]
            lines = get_output_lines(cmd)
            for line in lines:
                if line.startswith("Modeline"):
                    parts = line.split(" ")
                    parts = [x for x in parts if len(x)>0]
                    parts[0] = "  Modeline"
                    parts[1] = ('"%ix%i@%i"' % (w, h, hz)).ljust(15)
                    parts[2] = parts[2].rjust(8)
                    for i in range(3, len(parts)):
                        parts[i] = parts[i].rjust(5)
                    print(" ".join(parts))

def main():
    #lower resolutions (up to 4096x2048) with a 64 pixel step:
    gen_range(640, 4096, 64, 640, 2048, 64)
    #higher resolutions with 128 pixel step:
    gen_range(4096, 8192, 128, 2048, 4096, 128)


if __name__ == "__main__":
    main()
