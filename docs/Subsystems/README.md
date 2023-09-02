# Subsystems

This documentation refers to individual [protocol](../Network/Protocol.md) features,
it links to the implementation and technical documentation for each subsystem.

Most modules are optional, see [security considerations](../Usage/Security.md).

## Concepts

* Client Module: feature implementation loaded by the client, it interfaces with the corresponding "Client Connection Module" on the server side
* Client Connection Module: for each connection to a client, the server will instantiate a handler
* Server Module: feature implemented by the server, it may interact with multiple "Client Connection Modules"


| Subsystem                           | [Client Module](../../xpra/client/mixins/)                   | [Server Module](../../xpra/server/mixins)           | [Client Connection Module](../../xpra/server/source/)      | User Documentation                                       |
|-------------------------------------|--------------------------------------------------------------|-----------------------------------------------------|------------------------------------------------------------|----------------------------------------------------------|
| [Audio](./Audio.md)                 | [audio](../../xpra/client/mixins/audio.py)                   | [audio](../../xpra/server/mixins/audio.py)          | [audio](../../xpra/server/source/audio.py)                 | [audio feature](../Features/Audio.md)                    |
| [Clipboard](./Clipboard.md)         | [clipboard](../../xpra/client/mixins/clipboard.py)           | [clipboard](../../xpra/server/mixins/clipboard.py)  | [clipboard](../../xpra/server/source/clipboard.py)         | [clipboard feature](../Features/Clipboard.md)            |
| [MMAP](./MMAP.md)                   | [mmap](../../xpra/client/mixins/mmap.py)                     | [mmap](../../xpra/server/mixins/mmap.py)            | [mmap](../../xpra/server/source/mmap.py)                   | enabled automatically                                    |
| [Logging](./Logging.md)             | [remote-logging](../../xpra/client/mixins/logging.py) | [logging](../../xpra/server/mixins/logging.py)      | none                                                       | [logging usage](../Usage/Logging.md)                     |
| [Notifications](./Notifications.md) | [notifications](../../xpra/client/mixins/notification.py)    | [logging](../../xpra/server/mixins/notification.py) | [notification](../../xpra/server/source/notification.py)   | [notifications feature](../Features/Notifications.md)    |
