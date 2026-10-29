#!/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Export the SBOM data recorded in `xpra.build_info` as a CycloneDX JSON document:
# python3 cyclonedx_sbom.py [--identifiers MODULE] [OUTPUT.json]
# The identifiers module adds the CPE and PURL identifiers vulnerability scanners need,
# it must provide a `load_identifiers()` function returning a callable:
# `identify(package_name, package_version) -> (version, cpes, purls)`
# ie: `msys2_sbom` for MS Windows, `jhbuild_sbom` for MacOS.

import re
import sys
from importlib import import_module
from xpra.build_info import packages

from packageurl import PackageURL
from packageurl.contrib import url2purl

from cyclonedx.builder.this import this_component as cdx_lib_component
from cyclonedx.factory.license import LicenseFactory
from cyclonedx.model import Property
from cyclonedx.model.bom import Bom
from cyclonedx.model.component import Component, ComponentType
from cyclonedx.output.json import JsonV1Dot5


# where we keep the full package version when the component version is the upstream one:
PACKAGE_VERSION_PROPERTY = "xpra:package-version"
# the same project is often recorded under different CPE vendors or product names,
# CycloneDX only has room for one, so add the others the same way that syft does:
EXTRA_CPE_PROPERTY = "syft:cpe23"


def no_identifiers(package_name: str, package_version: str) -> tuple[str, list[str], list[str]]:
    return package_version, [], []


args = sys.argv[1:]
identify = no_identifiers
if args[:1] == ["--identifiers"] and len(args) >= 2:
    identify = import_module(args[1]).load_identifiers()
    args = args[2:]

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
unidentified = []
for package_name, info in packages.items():
    license_names = []
    licenses = [
        lc_factory.make_from_string(license_name)
        for license_name in [info.get("Licenses", "")]
        if license_name
    ]
    package_version = info.get("Version", "")
    version, cpes, purls = identify(package_name, package_version)
    purl = PackageURL.from_string(purls[0]) if purls else url2purl.get_purl(info.get("URL", ""))
    # scanners can match PyPI and NuGet packages without a CPE:
    if identify is not no_identifiers and version and not (cpes or purls or (purl and purl.type in ("pypi", "nuget"))):
        unidentified.append(package_name)
    properties = [Property(name=PACKAGE_VERSION_PROPERTY, value=package_version)] if package_version != version else []
    component = Component(
        type=ComponentType.LIBRARY,
        name=package_name,
        version=version,
        licenses=licenses,
        purl=purl,
        cpe=cpes[0] if cpes else None,
        properties=properties + [Property(name=EXTRA_CPE_PROPERTY, value=cpe) for cpe in cpes[1:]],
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


# meta packages without any files, which we resolve to the packages they depend on:
META_PACKAGES = {
    "cc-libs": ("libgcc", "libstdc++"),
    "gcc-libs": ("libgcc", "libstdc++"),
}


def expand_deps(deps: list[str]) -> list[str]:
    expanded = []
    for dep in deps:
        # strip the version constraint, ie: "mingw-w64-ucrt-x86_64-libgcc=16.2.0-6"
        dep = re.split(r"[<>=]", dep, 1)[0]
        for meta, replacements in META_PACKAGES.items():
            if dep.endswith(f"-{meta}"):
                prefix = dep[:-len(meta)]
                expanded += [prefix + replacement for replacement in replacements]
                break
        else:
            expanded.append(dep)
    return expanded


# now resolve the intra component dependencies:
for package_name, deps in dependencies.items():
    component = components[package_name]
    dep_components = []
    for dep in expand_deps(deps):
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
                # optional dependencies, none of the libraries we ship link against them:
                "c-ares", "gdbm", "libltdl", "libb2",
                # pcre2 tools use this, but we don't ship them:
                "wineditline",
                # python-fido2 talks to the devices directly:
                "libfido2",
                # removed from light builds:
                "libavif",
            )
            ):
                continue
            sys.stderr.write(f"Warning: {dep!r} not found, dependency of {package_name}\n")
    if dep_components:
        bom.register_dependency(component, dep_components)

if unidentified:
    sys.stderr.write(f"Warning: no CPE or PURL found for {len(unidentified)} packages: {', '.join(unidentified)}\n")

bom_json = JsonV1Dot5(bom).output_as_string(indent=2)

if args:
    filename = args[0]
    with open(filename, "w") as f:
        f.write(bom_json)
else:
    print(bom_json)
