# Info

<div class="docs-section-heading" markdown="1">

## Overview

</div>

The Info subsystem provides diagnostic information about an Xpra session.

<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

Information can be requested in two ways:

* with a one-shot connection: a `hello` with `request: "info"`, optionally with
  `subsystems`, which the server answers with a `hello` containing the information
  instead of its capabilities, then closes the connection (this is what `xpra info` does);
* from an established session:

  ```text
  C->S ["info-request", [client_uuid], window_ids, categories, subsystems?]
  S->C ["info-response", information]
  ```

  The server currently ignores `client_uuids`, `window_ids` and `categories`: send
  your own `uuid`, an empty list and an empty list. `subsystems` (optional) limits
  the response to the subsystems named.

Both are refused when the server's `info` socket option is disabled: the answer then
only contains an `error` string.

<div class="docs-section-heading" markdown="1">

## Contents

</div>

The information is a nested map, intended for display and debugging: its contents
change between versions and depend on the subsystems loaded, so clients MUST NOT
rely on any particular key. It is usually shown flattened, with dotted keys
(`display.size=...`). Integer keys are used for indexed items, such as window ids
or monitor numbers. Servers started with `XPRA_FULL_INFO=0` only include the
detailed sections (environment, threads, build details) for authenticated or local
connections.

The main top-level keys are:

| Key | Contents |
|---|---|
| `server`, `build`, `platform`, `sys`, `python`, `process` | Server type and version, build options, operating system, process statistics |
| `subsystems` | The list of subsystems loaded |
| `network` | Listening sockets, connection options, compressors and encoders |
| `display`, `randr`, `drm`, `icc` | Display server and monitor configuration |
| `windows`, `window` | One entry per window, keyed by window id, with its metadata and encoding statistics |
| `encoding`, `encodings`, `video` | Picture encodings and video codecs available |
| `keyboard`, `pointer`, `cursor`, `clipboard` | Input device state, keymap, clipboard owner and statistics |
| `clients` | The connected clients, and for each one its capabilities and connection statistics |
| `audio`, `webcam`, `file`, `printer`, `mmap`, `bandwidth`, `ping` | Feature state |
| `command`, `menu` | Commands started, and the start menu entries offered to clients |
| `threads` | Thread names and stacks |
| `env` | The server's environment |
