r"""JobRadar uninstaller - runs under the bundled, digitally signed Python runtime.

Windows Smart App Control (enforce mode) can block Inno Setup's freshly generated, unsigned
``unins000.exe`` because it has no reputation yet. The embedded Python runtime shipped with the app
*is* signed (by the Python Software Foundation), so SAC allows it - this script does the same job:
stop the app, remove the night-scan wake task, shortcuts and the registry entry, then delete the
program folder. Your jobs, CVs and profile in %LOCALAPPDATA%\JobRadar are kept unless you say so.

Usage (wired up by the installer):
    pythonw.exe uninstall.py            # asks, shows the result
    python.exe  uninstall.py /quiet     # no prompts, data kept (Windows "Apps" quiet uninstall)
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile

APP_NAME = "JobRadar"
APPID_KEY = "{7C1E9B42-5D3A-4F86-B2E0-JOBRADAR0001}_is1"
HERE = os.path.dirname(os.path.abspath(__file__))        # ...\JobRadar\app
INSTALL_DIR = os.path.dirname(HERE)                       # ...\JobRadar
QUIET = any(a.lower() in ("/quiet", "/silent", "/verysilent", "-q") for a in sys.argv[1:])
CREATE_NO_WINDOW = 0x8000000

MB_YESNO = 0x4
MB_DEFBUTTON2 = 0x100
MB_ICONQUESTION = 0x20
MB_ICONWARNING = 0x30
MB_ICONINFO = 0x40
IDYES = 6


def _msg(text, title=APP_NAME, flags=MB_ICONINFO, quiet_answer=IDYES):
    if QUIET:
        return quiet_answer
    try:
        return ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        return quiet_answer


def _data_dir():
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), APP_NAME)


def _kill_under(folder):
    """Terminate every python/pythonw whose executable lives inside *folder* (except ourselves)."""
    import ctypes.wintypes as wt

    folder_l = os.path.normcase(os.path.abspath(folder))
    me = os.getpid()
    k32 = ctypes.windll.kernel32

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
            ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260),
        ]

    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    if snap == -1:
        return
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            pid = entry.th32ProcessID
            if pid and pid != me and entry.szExeFile.lower() in ("python.exe", "pythonw.exe"):
                h = k32.OpenProcess(0x1000, False, pid)
                if h:
                    buf = ctypes.create_unicode_buffer(32768)
                    size = wt.DWORD(len(buf))
                    path = buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else ""
                    k32.CloseHandle(h)
                    if path and os.path.normcase(os.path.abspath(path)).startswith(folder_l):
                        ht = k32.OpenProcess(0x1, False, pid)
                        if ht:
                            k32.TerminateProcess(ht, 0)
                            k32.CloseHandle(ht)
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)


def _remove_wake_task():
    try:
        subprocess.run(["schtasks", "/Delete", "/TN", "JobRadar Night Scan", "/F"], capture_output=True,
                       creationflags=CREATE_NO_WINDOW, timeout=20)
    except Exception:
        pass


def _remove_shortcuts():
    links = []
    for env in ("USERPROFILE", "OneDrive", "OneDriveConsumer"):
        base = os.environ.get(env)
        if base:
            links.append(os.path.join(base, "Desktop", APP_NAME + ".lnk"))
    appdata = os.environ.get("APPDATA")
    if appdata:
        programs = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs")
        links += [os.path.join(programs, APP_NAME + ".lnk"), os.path.join(programs, "Uninstall " + APP_NAME + ".lnk")]
        shutil.rmtree(os.path.join(programs, APP_NAME), ignore_errors=True)
    for lnk in links:
        try:
            if os.path.exists(lnk):
                os.remove(lnk)
        except OSError:
            pass


def _remove_registry():
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + APPID_KEY)
    except OSError:
        pass


def _schedule_dir_delete(folder):
    """Delete the install folder after we exit (cmd.exe is Microsoft-signed, so SAC allows it)."""
    bat = os.path.join(tempfile.gettempdir(), "jobradar_uninstall_cleanup.bat")
    script = ("@echo off\r\n:retry\r\nping -n 2 127.0.0.1 >nul\r\n"
              'rmdir /s /q "%s"\r\nif exist "%s" goto retry\r\ndel "%%~f0"\r\n') % (folder, folder)
    try:
        with open(bat, "w", encoding="ascii") as fh:
            fh.write(script)
        subprocess.Popen(["cmd.exe", "/c", bat], creationflags=0x8 | CREATE_NO_WINDOW, close_fds=True)
    except Exception:
        pass


def main():
    if _msg("Remove %s from this computer?" % APP_NAME, "Uninstall " + APP_NAME, MB_YESNO | MB_ICONQUESTION) != IDYES:
        return 1
    wipe = os.path.isdir(_data_dir()) and _msg(
        "Also delete your JobRadar data?\n\nThis permanently removes your jobs, pipeline, CVs, profile and settings from:\n"
        + _data_dir() + "\n\nChoose No to keep them (they come back if you reinstall).",
        "Uninstall " + APP_NAME, MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2, quiet_answer=0) == IDYES
    _kill_under(INSTALL_DIR)
    _remove_wake_task()
    _remove_shortcuts()
    _remove_registry()
    if wipe:
        shutil.rmtree(_data_dir(), ignore_errors=True)
    _schedule_dir_delete(INSTALL_DIR)
    _msg("%s has been removed.%s" % (APP_NAME, "" if wipe else "\n\nYour data is still on this PC at:\n" + _data_dir()),
         APP_NAME + " uninstalled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
