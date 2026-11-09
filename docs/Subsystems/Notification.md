# Notifications

For usage related information, see [notifications feature](../Features/Notifications.md).


<div class="docs-section-heading" markdown="1">

## Implementations

</div>

The prefix for all packets and capabilities is `notification`.

| Component         | Link                                                                                                                     |
|-------------------|--------------------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.notification](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/notification.py) |
| client connection | [xpra.server.source.notification](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/notification.py)       |
| server            | [xpra.server.subsystem.notification](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/notification.py) |


<div class="docs-section-heading" markdown="1">

## Capabilities

</div>

The client sends a top-level `notification` boolean: notifications are only
forwarded to clients that set it. The server's `hello` contains a `notification`
key when it can forward notifications.
The client can enable or disable them later with `notification-status`.


<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

| Packet Type           | Arguments                                                                                | Direction        |
|-----------------------|------------------------------------------------------------------------------------------|------------------|
| `notification-show`   | notification data (see below)                                                            | server to client |
| `notification-close`  | `notification id` : integer<br/>`reason` : string optional<br/>`text` : string optional  | either direction |
| `notification-action` | `notification id` : integer<br/>`action_key` : string                                    | client to server |
| `notification-status` | `enabled` : boolean                                                                      | client to server |


### Notification data

| Argument                    | Type                    | Notes                            |
|-----------------------------|-------------------------|----------------------------------|
| `dbus_id`                   | `string`                | Empty if unused                  |
| `notification id`           | `integer`               | should be unique                 |
| `application name`          | `string`                |                                  |
| `replaced notification id`  | `integer`               | 0 if unused                      |
| `application icon`          | `string`                | the name of the icon to show     |
| `summary`                   | `string`                | the title of the notification    |
| `body`                      | `string`                | the contents of the notification |
| `timeout`                   | `integer`               | in milliseconds; `0` never expires, `-1` uses the default |
| `icon data`                 | `list` (optional)       | the icon data to use, see below, empty list for none |
| `actions`                   | `list`  (optional)      | see below                        |
| `hints`                     | `dictionary` (optional) | see below                        |

### Notification Icon

The icon data is a list or tuple with 4 elements:

| Argument | Type      |
|----------|-----------|
| `format` | `string`  |
| `width`  | `integer` |
| `height` | `integer` |
| `data`   | `bytes`   |

The only format which is guaranteed to be supported is `png`.
Other formats should not be used.

### Actions and hints

`actions` is a flat list alternating action keys and their labels, as in the
freedesktop notification specification: `["default", "Open", "reply", "Reply"]`.
When the user selects one, the client sends `notification-action` with the key.
When the notification is dismissed or expires, it sends `notification-close`.
A `notification-close` from the server asks the client to remove the notification.

`hints` follows the freedesktop notification hints (`urgency`, `category`,
`transient`, ...). The `image-data` and `app-icon-data` hints use the same 4-element
icon format as the icon data above. Unknown hints MUST be ignored.
Clients SHOULD decode and re-encode any icon they show rather than passing the
received bytes to a third-party component.
