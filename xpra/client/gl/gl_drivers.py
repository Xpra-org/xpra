#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#These chipsets will use OpenGL,
#there will not be any warnings, even if the vendor is greylisted:
WHITELIST = {
    "renderer"  : ["Haswell", "Skylake", "Kabylake", "Cannonlake",
                   "Whiskeylake", "Amberlake", "Cascadelake", "Cometlake",
                   "Icelake", "Cooperlake"],
    }

#Chipsets from these vendors will trigger warnings,
#but OpenGL will still be enabled:
GREYLIST = {
    "vendor"    : ["Intel", ]
    }

#Versions older than this will trigger warnings:
VERSION_REQ = {
   "nouveau" : [3, 0],      #older versions have issues
   }

#These chipsets will be disabled by default:
BLACKLIST = {
    "renderer" :
        [
            "SVGA3D",
            "Software Rasterizer",
            "Mesa DRI Intel(R) Ivybridge Desktop",
            "Mesa DRI Intel(R) Haswell Mobile",
            "Intel(R) UHD Graphics 620",
        ],
    "vendor"    : [
        #"VMware, Inc.",
        #"Humper",
        #to disable nvidia, uncomment this:
        #"NVIDIA Corporation",
        ]
    }


#for testing:
#GREYLIST["vendor"].append("NVIDIA Corporation")
#WHITELIST["renderer"] = ["GeForce GTX 760/PCIe/SSE2"]
#frequent crashes on OSX with GT 650M: (see ticket #808)
#if OSX:
#    GREYLIST.setdefault("vendor", []).append("NVIDIA Corporation")


class OpenGLFatalError(ImportError):
    pass
