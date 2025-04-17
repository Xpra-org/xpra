# Command Subsystem


This subsystem allows clients to execute new commands on the server.


## Implementations

| Component         | Link                                                                                                                   |
|-------------------|------------------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.child_command](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/child_command.py) |
| client connection | n/a                                                                                                                    |
| server            | [xpra.server.subsystem.child_command](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/child_command.py)     |


## Client Capabilities

| Capability | Type    | Purpose                                                                  |
|------------|---------|--------------------------------------------------------------------------|
| `xdg-menu` | boolean | The client wants to receive the menu of commands available on the server |



## Network Packets

### Server-to-Client

If the client requested it, the server sends the menu using a generic `setting-change` packet:

| Argument         | Type       | Purpose          |
|------------------|------------|------------------|
| `setting-change` | string     | packet type      |
| `xdg-menu`       | string     | setting          |
| menu-data        | dictionary | The updated menu |


### Client-to-Server

The only packet type that can be sent to the server is `start-command`:

| Argument        | Type            | Purpose                                                                                          |
|-----------------|-----------------|--------------------------------------------------------------------------------------------------|
| `start-command` | string          | packet type                                                                                      |
| name            | string          | The name of the command to execute, for presentation purposes only                               |
| command         | list of strings | The full command to execute                                                                      |
| ignore          | boolean         | Whether this command should be taken into account by the `exit-with-children` server feature     |
| sharing         | boolean         | Whether this application should be shared with other clients connected to the same server or not |
