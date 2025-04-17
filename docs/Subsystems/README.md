# Subsystems

This documentation refers to individual [protocol](../Network/Protocol.md) features,
it links to the implementation and technical documentation for each subsystem.

Each subsystem should be using its own prefix for capabilities and packet types. (most already do)

Most modules are optional, see [security considerations](../Usage/Security.md).

## Concepts

* Client Module: feature implementation loaded by the client, it interfaces with the corresponding "Client Connection Module" on the server side
* Client Connection Module: for each connection with a client, the server will instantiate a handler
* Server Module: feature implemented by the server, it may interact with multiple "Client Connection Modules"


Most subsystems are independent of each other, except for:
* the `Display` subsystem is required by `Windows`
* the `Windows` subsystem is required by the `Keyboard` and `Pointer` subsystems

A client or server may choose to completely disable a subsystem.\
When this is the case, it will not load the module into memory and will not know how to handle requests for this feature.


| Subsystem                         | [Client Module](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/)                | [Server Module](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem)           | [Client Connection Module](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/)    | User Documentation                                    |
|-----------------------------------|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|-------------------------------------------------------|
| [Audio](Audio.md)                 | [audio](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/audio.py)                | [audio](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/audio.py)          | [audio](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/audio.py)               | [audio feature](../Features/Audio.md)                 |
| [Clipboard](Clipboard.md)         | [clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/clipboard.py)        | [clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/clipboard.py)  | [clipboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/clipboard.py)       | [clipboard feature](../Features/Clipboard.md)         |
| [Display](Display.md)             | [display](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/display.py)            | [display](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/display.py)      | [display](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/display.py)           | Automatically configured                              |
| [Encoding](Encoding.md)           | [encoding](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/encodings.py)         | [encoding](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/encoding.py)    | [encodings](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/encodings.py)       | Automatically configured                              |
| [Keyboard](Keyboard.md)           | [keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/keyboard.py)          | [keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/keyboard.py)    | [keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/keyboard.py)         | [keyboard feature](../Features/Keyboard.md)           |
| [Logging](Logging.md)             | [remote-logging](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/logging.py)     | [logging](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/logging.py)      | none                                                                                            | [logging usage](../Usage/Logging.md)                  |
| [MMAP](MMAP.md)                   | [mmap](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/mmap.py)                  | [mmap](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/mmap.py)            | [mmap](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/mmap.py)                 | enabled automatically                                 |
| [Notifications](Notifications.md) | [notifications](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/notification.py) | [logging](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/notification.py) | [notification](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/notification.py) | [notifications feature](../Features/Notifications.md) |
| [Pointer](Pointer.md)             | [pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/pointer.py)            | [pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/pointer.py)      | [pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/pointer.py)           |                                                       |
| [Webcam](Webcam.md)               | [webcam](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/webcam.py)              | [webcam](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/webcam.py)        | [webcam](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/webcam.py)             | [webcam usage](../Features/Webcam.md)                 |
| [Window](Window.md)               | [windows](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/windows.py)            | [window](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/window.py)        | [window](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/windows.py)            |                                                       |
