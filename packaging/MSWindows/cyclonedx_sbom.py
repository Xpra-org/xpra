#!/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from xpra.build_info import packages

from packageurl.contrib import url2purl

from cyclonedx.builder.this import this_component as cdx_lib_component
from cyclonedx.factory.license import LicenseFactory
from cyclonedx.model.bom import Bom
from cyclonedx.model.component import Component, ComponentType
from cyclonedx.output.json import JsonV1Dot5


lc_factory = LicenseFactory()

bom = Bom()
bom.metadata.tools.components.add(cdx_lib_component())
bom.metadata.tools.components.add(Component(
    name='my-own-SBOM-generator',
    type=ComponentType.APPLICATION,
))

bom.metadata.component = root_component = Component(
    name='Xpra',
    type=ComponentType.APPLICATION,
    licenses=[lc_factory.make_from_string('GPL2+')],
    bom_ref='Xpra',
)

# cache components so we can more easily add dependencies later:
components = {}
# resolve full mingw64 prefixed package names to short version:
names = {}
dependencies = {}
for package_name, info in packages.items():
    license_names = []
    licenses = [
        lc_factory.make_from_string(license_name)
        for license_name in [info.get("Licenses", "")]
    ]
    component = Component(
        type=ComponentType.LIBRARY,
        name=package_name,
        version=info.get("Version", ""),
        licenses=licenses,
        purl=url2purl.get_purl(info.get("URL", "")),
    )
    bom.components.add(component)
    components[package_name] = component
    names[info.get("Name", package_name)] = package_name
    provides = info.get("Provides", ())
    for provided in provides:
        if provided not in names:
            names[provided] = package_name
    if not info.get("Required By"):
        bom.register_dependency(root_component, [component])
    deps = info.get("Depends On")
    if deps:
        dependencies[package_name] = deps


# now resolve the intra component dependencies:
for package_name, deps in dependencies.items():
    component = components[package_name]
    dep_components = []
    for dep in deps:
        dep_package_name = names.get(dep, dep)
        dep_component = components.get(dep_package_name)
        if dep_component:
            dep_components.append(dep_component)
        else:
            if package_name.find("gst") >= 0:
                continue
            if any(dep.endswith(f"-{suffix}") for suffix in (
                # only needed at build time:
                "cc", "python-build", "python-installer", "python-packaging",
                # gtk dependencies we don't need:
                "gtk-update-icon-cache", "shared-mime-info", "json-glib",
                "adwaita-icon-theme",
                # python dependencies we don't want:
                "tcl", "tk", "headers", "tzdata",
                # python works fine without `mpdec` so perhaps the current builds of Python
                # do not yet use the unbundled mpdec library and the MSYS2 package dependencies are therefore wrong?
                # in any case, it will become a hard dependency in python 3.13: /mingw64/bin/libmpdec-4.dll
                # at which point this workaround can be removed:
                "mpdecimal",
                # webp tools can use this, but we don't ship them:
                "giflib",
                # cairo, why?
                "lzo2",
                # could this be due to outdated dependencies?
                # paramiko and pyu2f work just fine without it:
                "python-six",
                # libcurl may use them, instead we only rely on the OS:
                "ca-certificates",
                # we skip the gnome bits of glib-networking:
                "gsettings-desktop-schemas",
                # libproxy wants this package, but we don't:
                "duktape",
                # ncurses works just fine without it:
                "libsystre",
                # sqlite tools use this, but we don't ship them:
                "readline",
            )
            ):
                continue
            sys.stderr.write(f"Warning: {dep!r} not found, dependency of {package_name}\n")
    if dep_components:
        bom.register_dependency(component, dep_components)

json = JsonV1Dot5(bom).output_as_string(indent=2)

if len(sys.argv) > 1:
    filename = sys.argv[1]
    with open(filename, "w") as f:
        f.write(json)
else:
    print(json)
