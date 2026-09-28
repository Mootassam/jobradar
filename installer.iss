; JobRadar installer - ships the official, digitally signed Python runtime (Python Software Foundation)
; with the app, so Windows Smart App Control can verify what it runs.
; Build: powershell -ExecutionPolicy Bypass -File build.ps1   (stages build_embed\ then runs ISCC)

#define MyAppName "JobRadar"
#define MyAppVersion "1.4.0"
#define MyAppPublisher "JobRadar"

[Setup]
AppId={{7C1E9B42-5D3A-4F86-B2E0-JOBRADAR0001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=installer_output
OutputBaseFilename=JobRadar-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
SetupIconFile=jobradar.ico
UninstallDisplayIcon={app}\app\jobradar.ico
UninstallDisplayName={#MyAppName}
CloseApplications=no
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: checkedonce

[Files]
Source: "build_embed\runtime\*"; DestDir: "{app}\runtime"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "build_embed\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs createallsubdirs ignoreversion

[InstallDelete]
; clean old program files on update (never the data in %LOCALAPPDATA%\JobRadar)
Type: filesandordirs; Name: "{app}\app"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\server.py"" --open"; WorkingDir: "{app}\app"; IconFilename: "{app}\app\jobradar.ico"; Comment: "Worldwide job search"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\server.py"" --open"; WorkingDir: "{app}\app"; IconFilename: "{app}\app\jobradar.ico"; Comment: "Worldwide job search"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\server.py"" --open"; WorkingDir: "{app}\app"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
{ Close a running JobRadar (python/pythonw started from this install folder) so its files can be replaced
  or removed. Only processes whose path is inside the install folder are touched. }
procedure StopJobRadar(Dir: String);
var
  Rc: Integer;
  Cmd: String;
begin
  Cmd := '-NoProfile -ExecutionPolicy Bypass -Command "Get-Process python,pythonw -ErrorAction SilentlyContinue | ' +
         'Where-Object { $_.Path -and $_.Path.ToLower().StartsWith(''' + Lowercase(Dir) + ''') } | ' +
         'Stop-Process -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 800"';
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, Rc);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopJobRadar(ExpandConstant('{app}'));
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopJobRadar(ExpandConstant('{app}'));
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Rc: Integer;
begin
  { remove the optional "wake the PC for the night scan" task, if it was set up }
  if CurUninstallStep = usUninstall then
    Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /TN "JobRadar Night Scan" /F', '', SW_HIDE, ewWaitUntilTerminated, Rc);
end;

[UninstallDelete]
; program files only - your jobs, CVs and profile in %LOCALAPPDATA%\JobRadar are never touched
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\runtime"
Type: dirifempty; Name: "{app}"
