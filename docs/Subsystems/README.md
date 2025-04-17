# Subsystems

This documentation refers to individual [protocol](../Network/Protocol.md) features,
it links to the implementation and technical documentation for each subsystem.

Each subsystem should be using its own prefix for capabilities and packet types. (most already do)

Most modules are optional, see [security considerations](../Usage/Security.md).

## Concepts

* Client Module: feature implementation loaded by the client, it interfaces with the corresponding "Client Connection Module" on the server side
* Client Connection Module: for each connection to a client, the server will instantiate a handler
* Server Module: feature implemented by the server, it may interact with multiple "Client Connection Modules"


| Subsystem                         | [Client Module](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/)                | [Server Module](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem)           | [Client Connection Module](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/)    | User Documentation                                    |
|-----------------------------------|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|-------------------------------------------------------|
| [Audio](Audio.md)                 | [audio](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/audio.py)                | [audio](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/audio.py)          | [audio](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/audio.py)               | [audio feature](../Features/Audio.md)                 |
| [Keyboard](Keyboard.md)           | [keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/keyboard.py)          | [keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/keyboard.py)    | [keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/keyboard.py)         | [keyboard feature](../Features/Keyboard.md)           |
| [Pointer](Pointer.md)             | [pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/pointer.py)            | [pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/pointer.py)      | [pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/pointer.py)           |                                                       |
| [Clipboard](Clipboard.md)         | [clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/clipboard.py)        | [clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/clipboard.py)  | [clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/clipboard.py)       | [clipboard feature](../Features/Clipboard.md)         |
| [MMAP](MMAP.md)                   | [mmap](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/mmap.py)                  | [mmap](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/mmap.py)            | [mmap](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/mmap.py)                 | enabled automatically                                 |
| [Logging](Logging.md)             | [remote-logging](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/logging.py)     | [logging](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/logging.py)      | none                                                                                            | [logging usage](../Usage/Logging.md)                  |
| [Notifications](Notifications.md) | [notifications](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/notification.py) | [logging](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/notification.py) | [notification](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/notification.py) | [notifications feature](../Features/Notifications.md) |
