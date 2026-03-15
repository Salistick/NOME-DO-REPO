#ifndef TTSLiveVersion
#define TTSLiveVersion "dev"
#endif

#define MyAppName "TTS Live"
#define MyAppPublisher "Salistick"
#define MyAppExeName "TTSLive.exe"
#define MyAppInstallerName "TTSLiveInstaller"

[Setup]
AppId={{2E3AF7D8-A9F3-4D0C-B91F-5600A6F58C11}
AppName={#MyAppName}
AppVersion={#TTSLiveVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\TTSLive
DefaultGroupName={#MyAppName}
OutputDir=dist
OutputBaseFilename={#MyAppInstallerName}
SetupIconFile=icon.ico
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
Source: "dist\TTSLive.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Executar {#MyAppName}"; Flags: nowait postinstall skipifsilent
