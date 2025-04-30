# Notifications

For usage related information, see [notitications feature](../Features/Notifications.md).


## Implementations

The prefix for all packets and capabilities is `notification`.

| Component         | Link                                                                                                                     |
|-------------------|--------------------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.notification](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/notification.py) |
| client connection | [xpra.server.source.notification](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/notification.py)       |
| server            | [xpra.server.subsystem.notification](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/notification.py) |


## Capabilities

The server exposes a single `enabled` flag using the `notifications` capability prefix.


## Network Packets

| Packet Type           | Arguments                                                                                | Direction        |
|-----------------------|------------------------------------------------------------------------------------------|------------------|
| `notification-show`   | notification data (see below)                                                            | server to client |
| `notification-close`  | `notification id` : integer<br/>`reason` : integer optional<br/>`text` : string optional | client to server |
| `notification-action` | `notification id` : integer<br/>`action_key` : integer                                   | client to server |
| `notification-status` | `enabled` : boolean                                                                      | client to server |


### Notification data

| Argument                    | Type                    | Notes                            |
|-----------------------------|-------------------------|----------------------------------|
| `dbus_id`                   | `integer`               | 0 if unused                      |
| `notification id`           | `integer`               | should be unique                 |
| `applciation name`          | `string`                |                                  |
| `replaced notification id`  | `integer`               | 0 if unused                      |
| `application icon`          | `string`                | the name of the icon to show     |
| `summary`                   | `string`                | the title of the notification    |
| `body`                      | `string`                | the contents of the notification |
| `timeout`                   | `integer`               | in seconds, zero if unused       |
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
