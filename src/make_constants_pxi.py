#!/usr/bin/env python

# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
This tool is called by ./setup.py automatically for you
and you should not need to call it directly.
It is used to generate the wimpiggy/lowlevel/constants.pxi file.
"""

import sys

def main(progname, args):
    if len(args) != 2:
        sys.stderr.write("Usage: %s CONSTANT-LIST PXI-OUTPUT\n")
        sys.exit(2)
    (constants_path, pxi_path) = args
    make_constants_pxi(constants_path, pxi_path)

def make_constants_pxi(constants_path, pxi_path):
    constants = []
    for line in open(constants_path):
        data = line.split("#", 1)[0].strip()
        # data can be empty ''...
        if not data:
            continue
        # or a pair like 'cFoo "Foo"'...
        elif len(data.split()) == 2:
            (pyname, cname) = data.split()
            constants.append((pyname, cname))
        # or just a simple token 'Foo'
        else:
            constants.append(data)
    out = open(pxi_path, "w")
    out.write("cdef extern from *:\n")
    ### Apparently you can't use | on enum's?!
    # out.write("    enum MagicNumbers:\n")
    # for const in constants:
    #     if isinstance(const, tuple):
    #         out.write('        %s %s\n' % const)
    #     else:
    #         out.write('        %s\n' % (const,))
    for const in constants:
        if isinstance(const, tuple):
            out.write('    unsigned int %s %s\n' % const)
        else:
            out.write('    unsigned int %s\n' % (const,))

    out.write("const = {\n")
    for const in constants:
        if isinstance(const, tuple):
            pyname = const[0]
        else:
            pyname = const
        out.write('    "%s": %s,\n' % (pyname, pyname))
    out.write("}\n")

if __name__ == "__main__":
    main(sys.argv[0], sys.argv[1:])
