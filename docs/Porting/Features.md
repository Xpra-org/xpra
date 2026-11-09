# Features

Every feature below is optional: it is only enabled when the client advertises it in its
`hello`, and the server simply leaves out what it does not support. This page lists what
each feature involves and where it is specified.

| Feature | Client capability | Packets | Specification |
|---|---|---|---|
| Windows | `window`, `metadata.supported` | `window-*` | [window](../Subsystems/Window.md) |
| Picture encodings | `encoding` | `window-draw`, `window-ack`, `encoding-*` | [encoding](../Subsystems/Encoding.md) |
| Display configuration | `display` | `display-*` | [display](../Subsystems/Display.md) |
| Keyboard | `keyboard`, `keymap`, `modifiers`, `key_repeat` | `keyboard-*` | [keyboard](../Subsystems/Keyboard.md) |
| Pointer | `pointer` | `pointer-*` | [pointer](../Subsystems/Pointer.md) |
| XInput2 devices | | `pointer-devices` | [pointer](../Subsystems/Pointer.md#input-devices) |
| Desktop settings | `gsettings` | `gsettings-update` | [gsettings](../Subsystems/GSettings.md) |
| Cursors | `cursor` | `cursor-*` | [cursor](../Subsystems/Cursor.md) |
| Window focus | | `window-focus`, `window-raise`, `window-restack` | [window focus](../Subsystems/Window-Focus.md) |
| Bell | `bell` | `window-bell` | [window](../Subsystems/Window.md#constants) |
| System tray icons | `system_tray` | `window-create` with `tray` metadata | [tray](../Subsystems/Tray.md) |
| Clipboard | `clipboard` | `clipboard-*` | [clipboard](../Subsystems/Clipboard.md) |
| Notifications | `notification` | `notification-*` | [notification](../Subsystems/Notification.md) |
| Audio | `audio` | `audio-*` | [audio](../Subsystems/Audio.md) |
| File transfers | `file` | `file-*` | [file](../Subsystems/File.md) |
| Printing | `printer` | `printer-*`, `file-send` | [file](../Subsystems/File.md), [printing](../Features/Printing.md) |
| Webcam | `webcam` | `webcam-*` | [webcam](../Subsystems/Webcam.md) |
| Shared memory | `mmap` | `window-draw` with `mmap` | [mmap](../Subsystems/MMAP.md) |
| Bandwidth control | `bandwidth`, `connection-data` | `bandwidth-*` | [bandwidth](../Subsystems/Bandwidth.md) |
| Ping and latency | `ping` | `ping`, `ping-echo` | [ping](../Subsystems/Ping.md) |
| Server events | `events` | `events` | [protocol](../Network/Protocol.md#71-core-status-and-control) |
| Commands and start menu | `command` | `command-*` | [command](../Subsystems/Command.md) |
| Remote logging | | `logging-*` | [logging](../Subsystems/Logging.md) |
| Session information | | `info-request`, `info-response` | [info](../Subsystems/Info.md) |
| Session sharing | `share`, `steal`, `lock` | `sharing-*` | [handshake](Handshake.md#sharing-a-session) |

The one-shot requests (`info`, `version`, `id`, `screenshot`, `command`, `run`, `exec`,
`print`, `detach`, `exit`, `stop`) use a `hello` with a `request` key instead of a session,
see [connection profiles](../Network/Protocol.md#54-connection-profiles).

<div class="docs-section-heading" markdown="1">

## Not specified yet

</div>

These exist in the reference implementation but are not specified well enough to be
implemented from the documentation alone:

* the optional AES encryption layer, see [AES](../Network/AES.md): use TLS, SSH or QUIC instead;
* the contents of `info-response`, which are diagnostic and change between versions;
* the recording profile (`keyboard-record`, `clipboard-record`), only used by xpra's
  own recording client, see the [protocol](../Network/Protocol.md#813-recording-profile).
