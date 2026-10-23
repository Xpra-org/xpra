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

`xpra.scripts.ssh_args` owns command splitting, backend-specific argument and
proxy-command construction, and mode-based agent-forwarding decisions. It accepts
the selected command, explicit forwarding policy and resolved key paths. The
adapter selects the backend, reads `XPRA_SSH_AGENT`, resolves key paths and looks
up the user UUID only when forwarding is enabled. Proxy construction retains its
existing mutation of the supplied SSH command list. The adapter supplies the
path-resolving argument builder when constructing proxy commands.

The resolving adapter in `xpra.scripts.parsing` owns session-name lookup,
credential fallbacks, password-file reads, proxy discovery, TLS configuration,
and transport availability checks. Keep these operations lazy and preserve their
order: credentials can update the options object before a later address error.
Socket-directory and command-line lists retain their existing references.

Launcher URLs parsed by `parse_URL()` use `attach-urls` and the configuration
URL allowlist. Direct connection queries use the separate
`XPRA_PARSING_STRICT` policy. Preserve both policies when adding an address form.

Both helper modules are included alongside `xpra.scripts.parsing` in `setup.py`.
The existing scripts Cython scan includes them, and RPM/Debian ownership of the
scripts directory covers their Python and compiled forms. Frozen builds must
include the same modules even when optional transports are disabled.

Run the grammar and adapter tests with:

```shell
PYTHONPATH=.:tests/unittests python3 -m unittest \
    unit.scripts.connection_test unit.scripts.connection_adapter_test \
    unit.scripts.ssh_args_test unit.scripts.parse_display_name_test \
    unit.scripts.parsing_test unit.net.ssh_test
```
