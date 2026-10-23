# Connection parsing

Connection parsing separates address grammar from host configuration and
transport discovery. The public `parse_display_name()` entry point remains in
`xpra.scripts.parsing` and returns the existing connection descriptor dictionary.

`xpra.scripts.connection` owns address normalization, host/port and path/query
grammar, socket and named-pipe fields, and Hyper-V service identifiers. Platform
flags, platform constants, defaults and query policy are supplied explicitly.
These helpers do not discover sessions, read password files, or load optional
transport backends. Path option separators are processed before percent decoding
session names; path options precede query options.

The resolving adapter in `xpra.scripts.parsing` owns session-name lookup,
credential fallbacks, password-file reads, proxy discovery, TLS configuration,
and transport availability checks. Keep these operations lazy and preserve their
order: credentials can update the options object before a later address error.
Socket-directory and command-line lists retain their existing references.

Launcher URLs parsed by `parse_URL()` use `attach-urls` and the configuration
URL allowlist. Direct connection queries use the separate
`XPRA_PARSING_STRICT` policy. Preserve both policies when adding an address form.

The grammar module is included alongside `xpra.scripts.parsing` in `setup.py`.
The existing scripts Cython scan includes it, and RPM/Debian ownership of the
scripts directory covers its Python and compiled forms. Frozen builds must
include the same module even when optional transports are disabled.

Run the grammar and adapter tests with:

```shell
PYTHONPATH=.:tests/unittests python3 -m unittest \
    unit.scripts.connection_test unit.scripts.connection_adapter_test \
    unit.scripts.parse_display_name_test unit.scripts.parsing_test
```
