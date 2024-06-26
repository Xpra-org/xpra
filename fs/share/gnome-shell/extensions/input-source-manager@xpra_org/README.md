# Input Source Manager (ISM) Extension for GNOME Shell

The GNOME Shell has restricted D-Bus interface access to some of its
private APIs since [v41.0](https://gitlab.gnome.org/GNOME/gnome-shell/-/commit/a628bbc4)
including the `org.gnome.Shell.Eval` method which was used by Xpra for
updating the client platform selected input source.
Therefore, this extension is implemented in order to expose the listing
and setting of input sources through a D-Bus interface.
Two methods are exposed by the provided D-Bus interface:

  1. List: provides the `.inputSources` list,
  2. Activate: takes a numeric index which must exist in the `.inputSources`
  and tries to activate it.

## CLI Verification

If the extension is installed and enabled, above methods may be tested
from CLI using the `gdbus` program as follows:

```
# List available input sources
gdbus call --session --dest org.gnome.Shell --object-path /org/xpra/InputSourceManager --method xpra_org.InputSourceManager.List
# Activate the first available input source (with index 0)
gdbus call --session --dest org.gnome.Shell --object-path /org/xpra/InputSourceManager --method xpra_org.InputSourceManager.Activate 0
```

## Enabling

The `input-source-manager@xpra_org` GNOME Shell extension must be
installed and enabled if it is desired to update the platform keyboard
layout when the `next_keyboard_layout` is called.
In recent GNOME versions which ship the `gnome-extensions` program, this
extension may be enabled by running the following command.

```
/usr/bin/gnome-extensions enable input-source-manager@xpra_org
```

Alternatively, it may be enabled manually by searching for
the `Extensions` (by pressing the `Super` key) and finding that
extension in the filtered list.
