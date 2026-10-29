#ifndef TTSLiveVersion
#define TTSLiveVersion "dev"
#endif

#ifndef TTSLiveExePath
#define TTSLiveExePath "dist\TTSLive.exe"
#endif

#ifdef TTSLiveValidationBuild
  #ifndef TTSLiveValidationDirectory
    #error "Validation builds require an explicit TTSLiveValidationDirectory."
  #endif
  #define MyAppName "TTS Live - Isolated Validation"
  #define MyAppInstallerName "TTSLiveValidationInstaller"
#else
  #define MyAppName "TTS Live"
  #define MyAppInstallerName "TTSLiveInstaller"
#endif
#define MyAppPublisher "Salistick"
#define MyAppExeName "TTSLive.exe"

[Setup]
#ifdef TTSLiveValidationBuild
AppId={{E8019612-CC81-4BF8-A17E-A5075CDE2411}
DefaultDirName={#TTSLiveValidationDirectory}
CreateUninstallRegKey=no
Uninstallable=yes
UsePreviousAppDir=no
CloseApplications=no
RestartApplications=no
#else
AppId={{2E3AF7D8-A9F3-4D0C-B91F-5600A6F58C11}
DefaultDirName={localappdata}\TTSLive
#endif
AppName={#MyAppName}
AppVersion={#TTSLiveVersion}
AppPublisher={#MyAppPublisher}
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

[Files]
Source: "{#TTSLiveExePath}"; DestDir: "{app}"; Flags: ignoreversion

#ifndef TTSLiveValidationBuild
[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Executar {#MyAppName}"; Flags: nowait postinstall skipifsilent
#endif

[UninstallDelete]
Type: dirifempty; Name: "{app}"
