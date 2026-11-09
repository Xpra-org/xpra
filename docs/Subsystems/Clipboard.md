# Clipboard

For usage related information, see [clipboard feature](../Features/Clipboard.md).


<div class="docs-section-heading" markdown="1">

## Implementations

</div>

The prefix for all packets and capabilities is `clipboard`.

| Component         | Link                                                                                                               |
|-------------------|--------------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/clipboard.py) |
| client connection | [xpra.server.source.clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/clipboard.py)       |
| server            | [xpra.server.subsystem.clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/clipboard.py) |


<div class="docs-section-heading" markdown="1">

## Platforms

</div>

[xpra.clipboard](https://github.com/Xpra-org/xpra/tree/master/xpra/clipboard/) contains the platform independent base class
used by all the backends.
It contains common features such as basic configuration, scheduling, filtering, etc.

| Platform | Link                                                                                                             |
|----------|------------------------------------------------------------------------------------------------------------------|
| `x11`    | [xpra.x11.gtk_x11.clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/gtk/clipboard.py)         |
| `win32`  | [xpra.platform.win32.clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/win32/clipboard.py)   |
| `MacOS`  | [xpra.platform.darwin.clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/darwin/clipboard.py) |
| others   | [xpra.gtk_common.gtk_clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/gtk/clipboard.py)              |



<div class="docs-section-heading" markdown="1">

## Capabilities

</div>

The client and server should expose the following capabilities in their `hello` packet
using the `clipboard` prefix:

| Capability          | Value                       | Information                                                                          |
|---------------------|-----------------------------|--------------------------------------------------------------------------------------|
| `notifications`     | boolean                     | Request `clipboard-pending-requests` packets                                          |
| `want_targets`      | boolean or list of strings  | Include targets for all or the named selections in `clipboard-data`                  |
| `greedy`            | boolean or list of strings  | Include contents for all or the named selections in `clipboard-data`                 |
| `preferred-targets` | list of strings             | The targets that the peer should prefer                                              |
| `selections`        | list of strings             | Clipboard selections supported by this endpoint                                      |
| `direction`         | string                      | Server only: one of `disabled`, `to-client`, `to-server` or `both`                   |
| `enabled`           | boolean                     | Client only, optional: default `True`                                                |

Notes:

* an absent `clipboard` map means that the subsystem is unavailable;
* `MacOS` clients normally request targets;
* both `MacOS` and `MS Windows` clients normally use greedy synchronization.

### Example capabilities

* X11 Client:
```json lines
{
  'clipboard': {
    'notifications': true,
    'selections': ['CLIPBOARD', 'PRIMARY', 'SECONDARY'],
    'preferred-targets': ['UTF8_STRING', 'TEXT', 'STRING', 'text/plain', 'image/png'],
  },
}
```
* X11 seamless server:
```json lines
{
  'clipboard': {
    'notifications': true,
    'selections': ['CLIPBOARD', 'PRIMARY', 'SECONDARY'],
    'preferred-targets': ['UTF8_STRING', 'TEXT', 'STRING', 'text/plain', 'image/png'],
    'direction': 'both',
  }
}
```

<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

This protocol is identical in both directions,
as either end can send and receive clipboard events.

| Packet Type                   | Arguments                                                                                              | Information                                                       |
|-------------------------------|--------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------|
| `clipboard-status`            | `enabled`: boolean, `reason`: string optional                                                          | Enable or disable synchronization                                 |
| `clipboard-enable-selections` | list of `selection`s                                                                                   | Select the clipboards to synchronize                              |
| `clipboard-data`              | `selection`, options dictionary                                                                        | Announce ownership and optionally include targets and contents    |
| `clipboard-request`           | `request-id`, `selection`, `target`                                                                    | Request clipboard contents                                       |
| `clipboard-contents`          | `request-id`, `selection`, `data-type`, `data-format`, `wire-encoding`, `data`, `truncated`             | Respond to `clipboard-request`                                    |
| `clipboard-contents-none`     | `request-id`, `selection` optional                                                                     | Empty response to `clipboard-request`                             |
| `clipboard-pending-requests`  | `pending-requests`: integer                                                                            | Number of requests waiting                                       |

The `clipboard-data` options are:

| Option | Type | Meaning |
|---|---|---|
| `claim` | boolean | The receiver should take ownership of its own selection, on behalf of the sender |
| `greedy` | boolean | The sender wants the contents to be included whenever possible |
| `origin` | string | A random identifier (at most 64 characters) of the sender's clipboard owner, used to detect loops: a peer MUST NOT re-announce a change that carries an `origin` it has just received |
| `synchronous` | boolean | The receiver should set the data immediately rather than on request |
| `targets` | list of strings | The targets available, at most 100 |
| `data` | map | Target name to `[data-type, data-format, wire-encoding, wire-data]` |


Clipboard data format details:

| Argument       | Data type | Information                                                   |
|----------------|-----------|---------------------------------------------------------------|
| `selection`    | `string`  | X11 supports 3 different _clipboards_, known as selections    |
| `request-id`   | `integer` | Each `clipboard-request` should use a new unique identifier   |
| `target`       | `string`  | A clipboard format, ie: `STRING`, `UTF8_STRING`, `text/plain` |
| `data-type`    | `string`  | The type of the contents, ie: `bytes` or `ATOM`               |
| `data-format`  | `integer` | The number of bits used by each item                          |
| `wire-encoding` | `string`  | Encoding used to convert the platform value to the wire form |
| `data`         | variable  | Depends on `wire-encoding`, see below                         |
| `truncated`    | `integer` | How much data was dropped to honour the sender's size limit, `0` when complete |

| `wire-encoding` | `data-format` | `data` |
|---|---|---|
| `bytes` | `8` | A byte string: text targets carry UTF-8 or Latin-1 text, image targets an encoded image |
| `integers` | `16` or `32` | A list of integers, one per item |
| `atoms` | `32` | A list of target names, for the `ATOM`, `ATOM_PAIR` and `TARGETS` data types |

`data-format` MUST be `8`, `16` or `32`. Data of 512 bytes or more may be sent
compressed, using the record-layer compression of a raw chunk: once decoded, it
is the same byte string. A packet is limited to 16 MiB of clipboard data.


### Flow

Whenever a clipboard change is detected, a `clipboard-data` packet must be sent to the peer.
If the peer advertises `want_targets`, the `targets` option must be included.
If the peer advertises `greedy`, matching contents must be included in the `data` option.
The contents may also be included if it is desirable to avoid a roundtrip later.

If the `targets` or the contents of the clipboard selection are needed,
a peer can send a `clipboard-request` with a unique `request_id`.
(use the value `TARGETS` as the `target` to get list of `targets`)

When requesting the clipboard contents, the `target` value chosen
should be one of the values from the list of `targets`.
If not, the peer may try to convert one of the valid `target`s.

If a value is sucessfully retrieved, a `clipboard-contents` packet is sent back,
otherwise a `clipboard-contents-none` is used.

A peer waits 2.5 seconds for the answer to a `clipboard-request`, after which the
request fails.

The server only exchanges clipboard data with one client at a time: the first
client with clipboard support, then whichever client most recently used the
keyboard or pointer (the "UI driver"). Clipboard packets from other clients are
ignored. The server also drops the clipboard packets it would send to a client
beyond 30 per second, to break clipboard loops. `clipboard-pending-requests` is only sent by the server, to clients that
advertise `notifications`: it is the number of requests still waiting for the
client's applications, so that the client can show progress.
