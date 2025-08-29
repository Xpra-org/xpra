# Security Policy

## Supported Versions

Please ensure that you are using a [supported version](https://github.com/Xpra-org/xpra/wiki/Versions).

Distribution packages are usually [outdated and full of vulnerabilities](https://github.com/Xpra-org/xpra/wiki/Distribution-Packages).

For a general overview, please first read [security considerations](./docs/Usage/Security.md) as it pervades the architecture of the software.


## Reporting a Vulnerability

We understand and accept that some researchers prefer full-disclosure, but we would prefer to have a heads up prior to the release of the vulnerability details.

Critical bugs are usually fixed (if reproducible) within hours, rather than days or weeks. Though making a new release does take a little bit longer.
Even more so for vulnerabilities.

Please contact [security@xpra.org](mailto:security@xpra.org)


## Notifications

To receive email notifications of pending security issues in any of the xpra projects,
please send a request to [security@xpra.org](mailto:security@xpra.org)


## Known issues
* [CVE-2021-40839](https://nvd.nist.gov/vuln/detail/CVE-2021-40839) [`rencode` issue](https://www.mail-archive.com/shifter-users@lists.devloop.org.uk/msg02754.html) affected all MS Windows and MacOS binary packages produced before the fix


## False positives
Some vulnerabilities are reported, sometimes automatically,
but cannot be exploited because the code is not actually used:
* [braces" v3.0.2 / "micromatch" v4.0.5 vulnerabilities](https://github.com/Xpra-org/xpra-html5/issues/306)
