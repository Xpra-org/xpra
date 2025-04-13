# ![Pointer](../../fs/share/xpra/icons/pointer.png) Pointer


## Implementations

The prefix for all packets and capabilities should be `pointer`, this work is not complete yet.

| Component         | Link                                                                                                     |
|-------------------|----------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/client/mixins/pointer.py) |
| client connection | [xpra.server.source.pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/pointer.py) |
| server            | [xpra.server.subsystem.pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/server/mixins/pointer.py) |


## Platforms

There is some platform specific code to handle mouse wheel.\
Links pending.

## Capabilities

The client should expose the following capabilities in its `hello` packet:

| Capability      | Value               | Information                                                                   |
|-----------------|---------------------|-------------------------------------------------------------------------------|
| `mouse`         | `enabled` : boolean | Whether pointer support is enabled                                            |
| `double_click` | dictionary | contains just two integer attributes: `time` (in milliseconds) and `distance` |


## Network Packets

| Packet Type      | Arguments                       | Information |
|------------------|---------------------------------|-------------|
| `pointer-position` | `wid`, position data, modifiers | |
| `pointer-button`   | `device_id`, `sequence`, `wid`, `button`, `pressed`, position data, properties | |
| `input-devices` |                                 | |
