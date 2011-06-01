[Setup]
AppName=Xpra
AppVerName=Xpra 0.0.7.16
AppPublisher=devloop
AppPublisherURL=http://xpra.devloop.org.uk/
DefaultDirName={pf}\Xpra
DefaultGroupName=Xpra
DisableProgramGroupPage=true
OutputBaseFilename=setup
Compression=lzma
SolidCompression=true
AllowUNCPath=false
VersionInfoVersion=0.0.7.16
VersionInfoCompany=devloop
VersionInfoDescription=screen for X

[Dirs]
Name: {app}; Flags: uninsalwaysuninstall;

[Files]
Source: dist\*; DestDir: {app}; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: {group}\Xpra; Filename: {app}\client_launcher.exe; WorkingDir: {app}

[Run]
Filename: {app}\client_launcher.exe; Description: {cm:LaunchProgram,xpra}; Flags: nowait postinstall skipifsilent
