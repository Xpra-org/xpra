#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# MSYS2 maintains CPE and PURL references for its packages (`msys2_references` in the PKGBUILDs),
# and publishes them in the SBOMs it uses for its own vulnerability reports:
# https://www.msys2.org/dev/vulnerabilities/
# we add them to our SBOM components so that vulnerability scanners can match them.
#
# Used by `cyclonedx_sbom.py --identifiers msys2_sbom` when generating the SBOM,
# or from the command line to add them to an SBOM generated without them:
# python3 msys2_sbom.py Xpra.json Xpra-with-references.json

import os
import re
import sys
import json
from collections import defaultdict
from collections.abc import Callable
from urllib.request import urlopen

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
    "libgcc": "gcc",
    "libstdc++": "gcc",
    "libwinpthread": "winpthreads",
    "python-cairo": "pycairo",
}

# where we keep the full package version when the component version is the upstream one:
PACKAGE_VERSION_PROPERTY = "xpra:package-version"
# the same project is often recorded under different CPE vendors or product names,
# CycloneDX only has room for one, so add the others the same way that syft does:
EXTRA_CPE_PROPERTY = "syft:cpe23"


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


def get_identifiers(references: dict[str, list[dict]], package_name: str, upstream_version: str) -> tuple[list[str], list[str]]:
    pkgbase = MSYS2_PKGBASE.get(package_name, package_name)
    refs = ()
    for name in (pkgbase, pkgbase.removesuffix("-libs")):
        refs = references.get(f"mingw-w64-{name}") or references.get(name) or ()
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
            # ie: "pkg:pypi/pillow@13.0.0", qualifiers and subpath follow the version
            base = re.match(r"[^?#]*", purl).group(0)
            purls.append(base.split("@", 1)[0] + f"@{upstream_version}" + purl[len(base):])
    return cpes, purls


def load_identifiers() -> Callable[[str, str], tuple[str, list[str], list[str]]]:
    """
    used by `cyclonedx_sbom.py --identifiers msys2_sbom`
    """
    references = load_msys2_references()

    def identify(package_name: str, package_version: str) -> tuple[str, list[str], list[str]]:
        # scanners compare the component version with the upstream versions affected by a vulnerability,
        # and "48.0.1-1" would be a post-release of "48.0.1" for PyPI packages:
        version = get_upstream_version(package_version)
        cpes, purls = get_identifiers(references, package_name, version)
        return version, cpes, purls
    return identify


def add_references(bom: dict, references: dict[str, list[dict]]) -> list[str]:
    """
    add the identifiers to the components of a CycloneDX JSON document which do not have any,
    returns the names of the components we could not find identifiers for
    """
    unidentified = []
    for component in bom.get("components", ()):
        properties = component.setdefault("properties", [])
        if any(prop.get("name") == PACKAGE_VERSION_PROPERTY for prop in properties):
            continue
        purl = component.get("purl", "")
        if component.get("cpe") or (purl and not purl.startswith(("pkg:generic/", "pkg:github/"))):
            continue
        package_version = component.get("version", "")
        version = get_upstream_version(package_version)
        cpes, purls = get_identifiers(references, component["name"], version)
        if not (cpes or purls):
            if version:
                unidentified.append(component["name"])
            continue
        component["version"] = version
        if package_version != version:
            properties.append({"name": PACKAGE_VERSION_PROPERTY, "value": package_version})
        if cpes:
            component["cpe"] = cpes[0]
            properties += [{"name": EXTRA_CPE_PROPERTY, "value": cpe} for cpe in cpes[1:]]
        if purls:
            component["purl"] = purls[0]
    return unidentified


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write(f"usage: {argv[0]} SBOM.json OUTPUT.json\n")
        return 1
    with open(argv[1]) as f:
        bom = json.load(f)
    references = load_msys2_references()
    if not references:
        sys.stderr.write("Error: no MSYS2 references\n")
        return 1
    unidentified = add_references(bom, references)
    if unidentified:
        sys.stderr.write(f"Warning: no CPE or PURL found for {len(unidentified)} packages: {', '.join(unidentified)}\n")
    with open(argv[2], "w") as f:
        json.dump(bom, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
