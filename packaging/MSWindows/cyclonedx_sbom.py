#!/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import sys
import json
from collections import defaultdict
from urllib.request import urlopen
from xpra.build_info import packages

from packageurl import PackageURL
from packageurl.contrib import url2purl

from cyclonedx.builder.this import this_component as cdx_lib_component
from cyclonedx.factory.license import LicenseFactory
from cyclonedx.model import Property
from cyclonedx.model.bom import Bom
from cyclonedx.model.component import Component, ComponentType
from cyclonedx.output.json import JsonV1Dot5


# MSYS2 maintains CPE and PURL references for its packages (`msys2_references` in the PKGBUILDs),
# and publishes them in the SBOMs it uses for its own vulnerability reports:
# https://www.msys2.org/dev/vulnerabilities/
# add them to our components so that vulnerability scanners can match them:
MSYS2_SBOM_URLS = os.environ.get("MSYS2_SBOM_URLS", ",".join((
    "https://github.com/msys2/MINGW-packages/releases/download/srcinfo-cache/sbom.vuln.cdx.json",
    "https://github.com/msys2/MSYS2-packages/releases/download/srcinfo-cache/sbom.vuln.cdx.json",
))).split(",")

# packages whose name does not match their MSYS2 base package name,
# (in addition to the "-libs" split packages):
MSYS2_PKGBASE = {
    "atk": "at-spi2-core",
    "boost-libs": "boost",
    "gettext-runtime": "gettext",
    "gobject-introspection-runtime": "gobject-introspection",
    "libwinpthread": "winpthreads",
    "python-cairo": "pycairo",
}


def load_msys2_references() -> dict[str, list[dict]]:
    references = defaultdict(list)
    for url in MSYS2_SBOM_URLS:
        if not url:
            continue
        try:
            with urlopen(url, timeout=60) as response:
                msys2_bom = json.load(response)
        except (OSError, ValueError) as e:
            sys.stderr.write(f"Warning: unable to load the MSYS2 SBOM from {url!r}: {e}\n")
            continue
        for ref in msys2_bom.get("components", ()):
            if not (ref.get("cpe") or ref.get("purl")):
                continue
            for prop in ref.get("properties", ()):
                if prop.get("name") == "msys2:pkgbase":
                    references[prop["value"]].append(ref)
    return references


def get_upstream_version(version: str) -> str:
    # strip the epoch and pkgrel, ie: "1:2.3.4-5" -> "2.3.4"
    return version.split(":", 1)[-1].rsplit("-", 1)[0]


def get_identifiers(package_name: str, upstream_version: str) -> tuple[list[str], list[PackageURL]]:
    pkgbase = MSYS2_PKGBASE.get(package_name, package_name)
    refs = ()
    for name in (pkgbase, pkgbase.removesuffix("-libs")):
        refs = msys2_references.get(f"mingw-w64-{name}") or msys2_references.get(name) or ()
        if refs:
            break
    # the references use the version MSYS2 currently ships, use ours instead:
    cpes = []
    purls = []
    for ref in refs:
        if cpe := ref.get("cpe"):
            # ie: "cpe:2.3:a:gnome:pango:1.58.2:*:*:*:*:*:*:*"
            parts = re.split(r"(?<!\\):", cpe)
            parts[5] = upstream_version
            cpes.append(":".join(parts))
        if purl := ref.get("purl"):
            purls.append(PackageURL.from_string(purl)._replace(version=upstream_version))
    return cpes, purls


msys2_references = load_msys2_references()

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
    # scanners compare the component version with the upstream versions affected by a vulnerability,
    # and "48.0.1-1" would be a post-release of "48.0.1" for PyPI packages:
    version = get_upstream_version(package_version)
    cpes, purls = get_identifiers(package_name, version)
    if msys2_references and version and not (cpes or purls):
        unidentified.append(package_name)
    properties = [Property(name="xpra:package-version", value=package_version)] if package_version != version else []
    component = Component(
        type=ComponentType.LIBRARY,
        name=package_name,
        version=version,
        licenses=licenses,
        purl=purls[0] if purls else url2purl.get_purl(info.get("URL", "")),
        cpe=cpes[0] if cpes else None,
        # the same project is often recorded under different CPE vendors or product names,
        # CycloneDX only has room for one, so add the others the same way that syft does:
        properties=properties + [Property(name="syft:cpe23", value=cpe) for cpe in cpes[1:]],
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

if unidentified:
    sys.stderr.write(f"Warning: no CPE or PURL found for {len(unidentified)} packages: {', '.join(unidentified)}\n")

bom_json = JsonV1Dot5(bom).output_as_string(indent=2)

if len(sys.argv) > 1:
    filename = sys.argv[1]
    with open(filename, "w") as f:
        f.write(bom_json)
else:
    print(bom_json)
