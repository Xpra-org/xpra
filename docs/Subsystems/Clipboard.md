# ![Clipboard](../images/icons/clipboard.png) Clipboard

For usage related information, see [clipboard feature](../Features/Clipboard.md).


## Implementations

The prefix for all packets and capabilities is `clipboard`.

| Component         | Link                                                                                                               |
|-------------------|--------------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/clipboard.py) |
| client connection | [xpra.server.source.clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/clipboard.py)       |
| server            | [xpra.server.subsystem.clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/clipboard.py) |


## Platforms

[xpra.clipboard](https://github.com/Xpra-org/xpra/tree/master/xpra/clipboard/) contains the platform independent base class
used by all the backends.
It contains common features such as basic configuration, scheduling, filtering, etc.

| Platform | Link                                                                                                             |
|----------|------------------------------------------------------------------------------------------------------------------|
| `x11`    | [xpra.x11.gtk_x11.clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/gtk/clipboard.py)         |
| `win32`  | [xpra.platform.win32.clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/win32/clipboard.py)   |
| `MacOS`  | [xpra.platform.darwin.clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/darwin/clipboard.py) |
| others   | [xpra.gtk_common.gtk_clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/gtk/clipboard.py)              |



## Capabilities

The client and server should expose the following capabilities in their `hello` packet
using the `clipboard` prefix:

| Capability          | Value                     | Information                                                                          |
|---------------------|---------------------------|--------------------------------------------------------------------------------------|
| `enabled`           | `enabled` : boolean       | Whether clipboard support is enabled                                                 |
| `notification`      | `enabled` : boolean       | Request the peer to send `clipboard-pending-requests` packets                        |
| `want_targets`      | `enabled` : boolean       | Request the peer to send `target`s with `clipboard-token` packets                    |
| `greedy`            | `enabled` : boolean       | Request the peer to send clipboard data with `clipboard-token` packets               |
| `preferred-targets` | `targets` : list of strings | The `target`s that the peer should try to use                                        |
| `direction`         | `direction`: string       | Optional, which direction is supported, ie: `none`, `to-client`, `to-server`, `both` |

Notes:
* any unspecified boolean value defaults to `false`
* `MacOS` clients set the `want_targets` flag
* both `MacOS` and `MS Windows` clients set the `greedy` flag

### Example capabilities

* X11 Client:
```json lines
{
  'clipboard': {
    'enabled': true,
    'notifications': true,
    'selections': ['CLIPBOARD', 'PRIMARY', 'SECONDARY'],
    'preferred-targets': ['UTF8_STRING', 'TEXT', 'STRING', 'text/plain', 'image/png'],
    'direction': "both",
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

## Network Packets

This protocol is identical in both directions,
as either end can send and receive clipboard events.

| Packet Type                   | Arguments                                                      | Optional Arguments                                                 | Information                                                                                                                                                                      |
|-------------------------------|----------------------------------------------------------------|--------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `set-clipboard-enabled`       | `enabled` : boolean                                            | `reason` : string                                                  | Either end is free to enable or disable the clipboard at any time and should notify the peer.                                                                                    |
| `clipboard-enable-selections` | list of `selection`s                                           |                                                                    | The selections that the peer wants to synchronize with                                                                                                                           |
| `clipboard-token`             | `selection`                                                    | list of `target`s, `target`, `data-type`, `data-format` and `data` | Notify the peer of a clipboard state change event for the given `selection`, this may include the new clipboard contents if known and / or if the client is known to be _greedy_ |
| `clipboard-request`           | `request-id`, `target`                                         |                                                                    | Request clipboard contents from the peer                                                                                                                                         |
| `clipboard-contents`          | `request_id`, `selection`, `data-type`, `data-format`, `data`  |                                                                    | Response to a `clipboard-request`                                                                                                                                                |
| `clipboard-contents-none`     |                                                                |                                                                    | Empty response to a `clipboard-request`                                                                                                                                          |
| `clipboard-pending-requests`  | `pending-requests` : integers                                  |                                                                    | The number of clipboard requests waiting                                                                                                                                         |


Clipboard data format details:

| Argument       | Data type | Information                                                   |
|----------------|-----------|---------------------------------------------------------------|
| `selection`    | `string`  | X11 supports 3 different _clipboards_, known as selections    |
| `request-id`   | `integer` | Each `clipboard-request` should use a new unique identifier   |
| `target`       | `string`  | A clipboard format, ie: `STRING`, `UTF8_STRING`, `text/plain` |
| `data-type`    | `string`  | The type of the contents, ie: `bytes` or `ATOM`               |
| `data-format`  | `integer` | The number of bits used by each item                          |
| `data`         | variable  | Typically, `bytes` that need to be decoded                    |


### Flow

Whenever a clipboard change is detected, a `clipboard-token` packet must be sent to the peer.
If the peer advertises the `want_targets` flag then the list of `targets` must be included in the packet.
If the peer advertises the `greedy` flag then the actual contents of the selection must be included in the packet.
The contents may also be included if it is desirable to avoid a roundtrip later.

If the `targets` or the contents of the clipboard selection are needed,
a peer can send a `clipboard-request` with a unique `request_id`.
(use the value `TARGETS` as the `target` to get list of `targets`)

When requesting the clipboard contents, the `target` value chosen
should be one of the values from the list of `targets`.
If not, the peer may try to convert one of the valid `target`s.

If a value is sucessfully retrieved, a `clipboard-contents` packet is sent back,
otherwise a `clipboard-contents-none` is used.
