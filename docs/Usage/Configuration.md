# Configure Xpra

Most day-to-day Xpra settings can be changed from its graphical configuration
tool. Open **Xpra** from your application menu, choose **Configure**, then
choose the area you want to change: features, picture quality, packages,
server components, or debugging.

The graphical tool is the best starting point because it describes the setting
and saves the choice for you. Use the methods below when you need a repeatable
change, want to manage settings remotely, or cannot use the graphical tool.

## Change one setting permanently

Use `xpra set` to save a single setting for your user account. For example,
this makes Xpra use a 120 DPI display scale:

```shell
xpra set dpi 120
```

Remove a saved setting and return to the default with:

```shell
xpra unset dpi
```

Run `xpra --help` or read the manual for the full list of settings available in
your installed Xpra version.

<details markdown="1">
<summary>Configure Xpra with files or command-line options</summary>

Most settings can also be passed on the command line or written in Xpra
configuration files. The setting names are the same as the command-line
options, but configuration files omit the leading `--`. For example:

```text
min-quality=50
```

matches the command-line option `--min-quality=50`.

Example files are available in the
[template `/etc/xpra/` directory](https://github.com/Xpra-org/xpra/tree/master/fs/etc).
The installed manual is the reference for the version you are running; on most
Unix-like systems, open it with:

```shell
man xpra
```

Some less common features are configured through environment variables.
</details>

<details markdown="1">
<summary>Find configuration files on your platform</summary>

Use a per-user configuration file for your own settings. Do not normally edit
system defaults because an Xpra upgrade may replace them.

- On Unix-like systems, system files are commonly in `/etc/xpra` and per-user
  files in `~/.config/xpra`. Run `xpra/platform/paths.py` for exact locations.
- On macOS, the per-user location is usually
  `~/Library/Application Support/Xpra`; `~/.config/xpra` also works. Run
  `Xpra.app/Contents/Helpers/Path_info` for the paths used by your installation.
- On Windows, run `Path_info.exe` from the Xpra installation folder.
</details>

## Next steps

- [Choose which features to forward](../Features/README.md)
- [Connect and save client settings](Client.md)
- [Use logging to diagnose a problem](Logging.md)
