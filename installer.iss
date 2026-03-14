#ifndef BotLiveVersion
#define BotLiveVersion "dev"
#endif

#define MyAppName "Bot Live"
#define MyAppPublisher "Salistick"
#define MyAppExeName "BotLive.exe"
#define MyAppInstallerName "BotLiveInstaller"

[Setup]
AppId={{2E3AF7D8-A9F3-4D0C-B91F-5600A6F58C11}
AppName={#MyAppName}
AppVersion={#BotLiveVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\BotLive
DefaultGroupName={#MyAppName}
OutputDir=dist
OutputBaseFilename={#MyAppInstallerName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos adicionais:"

[Files]
Source: "dist\BotLive.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Executar {#MyAppName}"; Flags: nowait postinstall skipifsilent
