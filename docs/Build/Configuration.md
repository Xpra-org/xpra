# Configuration code

Configuration support lives in `xpra.config`. Import the module that owns the
operation so that reading option metadata or catching a startup error does not
also discover host defaults or load configuration files.

| Module | Responsibility |
|--------|----------------|
| `xpra.config` | `InitException`, `InitInfo`, `InitExit`, and shared diagnostic hooks |
| `xpra.config.types` | Option types, groups, aliases, URL allow-list, and `XpraConfig` values |
| `xpra.config.validation` | Validate supplied mappings and Landlock option values |
| `xpra.config.defaults` | Discover host settings lazily, assemble defaults, and construct configuration values |
| `xpra.config.io` | Parse text, load/save files, and discover configuration directories |
| `xpra.config.fixup` | Normalize parsed options before client/server initialization |
| `xpra.config.vfb` | Generate virtual-display commands and discover Xorg/Xdummy |
| `xpra.config.paths` | Locate installed documentation and HTML5 resources |
| `xpra.config.info` | Format build/source information |

For example:

```python
from xpra.config import InitException
from xpra.config.types import OPTION_TYPES
from xpra.config.defaults import make_defaults_struct
from xpra.config.io import read_config
```

`get_defaults()` still discovers settings on its first call and caches the
returned dictionary. `dict_to_validated_config()` combines these defaults,
additional defaults, and validated supplied values in that order.
`make_defaults_struct()` also loads the application, system, and user
configuration directories. Within each directory, `xpra.conf` is loaded first,
then the sorted `conf.d/*.conf` files; later values override earlier ones.
The existing `conf_files()` listing order is retained separately.

For tests or tools that already have resolved settings, pass a
`DefaultsContext` to `build_defaults()`. This assembles the default dictionary
without discovering display commands, platform paths, or audio support.
`parse_config_lines()` accepts an iterable of text lines and requires no file.

Redirect configuration warnings/debug output through `xpra.config.warn` and
`xpra.config.debug`. Cache resets belong to
`xpra.config.defaults.GLOBAL_DEFAULTS`. The old `xpra.scripts.config` module
retains compatibility imports for functions, classes, and option metadata;
new code should use their owning modules rather than changing legacy module
globals.

Inspect defaults or individual configuration files with:

```shell
python3 -m xpra.config
python3 -m xpra.config /path/to/xpra.conf
```

The Windows and macOS `Config_info` tools use this entry point. The legacy
`python3 -m xpra.scripts.config` invocation remains available.

The package is part of the common runtime, including minimal builds. Build
changes must retain its selection in `setup.py`, its optional Cython build,
and ownership in the RPM and Debian common-package file lists. Source archives
include these Python modules through `MANIFEST.in`'s existing Python-file rule.
