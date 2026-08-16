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

The server exposes a single `enabled` flag using the `notifications` capability prefix.


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
| `timeout`                   | `integer`               | in milliseconds, zero if unused  |
| `icon data`                 | `list` (optional)       | the icon data to use, see below  |
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
