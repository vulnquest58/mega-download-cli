#!/usr/bin/env python3
"""
mega_download.py — Batch downloader for MEGA links using MEGA-CMD.

v2 — accuracy + selection
--------------------------
1) FIXED: filename/size reported after each download were taken from a live
   folder-monitor "this looks stable" heuristic, which often fired on the
   intermediate ".getxfer.<pid>.<n>.mega" temp file MEGAcmd writes to while
   downloading (e.g. during a brief network stall) — long before the real
   download was actually finished. That gave wildly wrong sizes (a few MB
   reported for a multi-GB file) even though the real download kept running
   in the background until the process genuinely exited.
   Now: the live monitor is used ONLY to draw the progress bar. The
   authoritative filename/size always comes from a fresh scan of the
   destination folder taken *after* the mega-get process has actually
   exited, ignoring any leftover ".getxfer.*" temp artifacts.

2) NEW: you can choose which links to actually download instead of always
   grabbing the whole file:
     --select "1"            a single entry
     --select "1,3,5"        several entries
     --select "2-7"          a range
     --select "1,3-5,8"      mix of both
     --level easy|medium|hard  filter by difficulty (parsed from the
                                "# Name  [Level]  Size" comment lines that
                                script.py's --save-links writes above each
                                URL)
     --list                  just print the parsed link table and exit
   If --select is omitted and you're running in an interactive terminal,
   you'll be shown a numbered table and prompted (press Enter for "all").
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from threading import Lock
from typing import List, Optional, Dict, Tuple
import threading


# --------------------------------------------------------------------------- #
#  Terminal colours
# --------------------------------------------------------------------------- #
class _C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    BLUE   = "\033[94m"


def _enable_win_ansi() -> bool:
    if platform.system() != "Windows":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        return True
    except Exception:
        return False


def _strip_colours() -> None:
    for attr in list(vars(_C)):
        if not attr.startswith("_"):
            setattr(_C, attr, "")


if not sys.stdout.isatty() or not _enable_win_ansi():
    _strip_colours()


# --------------------------------------------------------------------------- #
#  Logging
# --------------------------------------------------------------------------- #
_print_lock = Lock()


def _log(tag: str, colour: str, msg: str, *, file=sys.stdout) -> None:
    with _print_lock:
        print(f"{colour}{tag}{_C.RESET}  {msg}", file=file, flush=True)


def info(msg: str)  -> None: _log("[INFO]", _C.CYAN,   msg)
def ok(msg: str)    -> None: _log("[ OK ]", _C.GREEN,  msg)
def warn(msg: str)  -> None: _log("[WARN]", _C.YELLOW, msg)
def error(msg: str) -> None: _log("[FAIL]", _C.RED,    msg, file=sys.stderr)


def divider() -> None:
    print(f"{_C.DIM}{'─' * 78}{_C.RESET}", flush=True)


def step(i: int, n: int, msg: str) -> None:
    with _print_lock:
        print(f"\n{_C.BOLD}[{i}/{n}]{_C.RESET}  {msg[:90]}", flush=True)


# --------------------------------------------------------------------------- #
#  Progress bar utilities
# --------------------------------------------------------------------------- #
def format_size(size_bytes: int) -> str:
    """Format bytes to human readable"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def show_progress_bar(filename: str, current: int, total: int, elapsed: float):
    """Show custom progress bar (cosmetic only — not used for the final result)"""
    if total > 0:
        percent = min(100, (current / total) * 100)
        bar_length = 40
        filled = int(bar_length * current / total)
        bar = '█' * filled + '░' * (bar_length - filled)

        speed = current / elapsed if elapsed > 0 else 0
        speed_str = f"{format_size(int(speed))}/s" if elapsed > 0 else "0 B/s"

        if speed > 0 and current < total:
            eta = (total - current) / speed
            eta_str = str(timedelta(seconds=int(eta)))
        else:
            eta_str = "--:--:--"

        line = f"\r{_C.CYAN}{filename[:30]:<30}{_C.RESET} |{_C.GREEN}{bar}{_C.RESET}| {percent:5.1f}%  {format_size(current)}/{format_size(total)}  {speed_str}  ETA: {eta_str}"
    else:
        line = f"\r{_C.CYAN}{filename[:30]:<30}{_C.RESET}  {_C.BLUE}Downloading...{_C.RESET}  {format_size(current)}  Elapsed: {str(timedelta(seconds=int(elapsed)))}"

    with _print_lock:
        sys.stdout.write(line)
        sys.stdout.flush()


def clear_progress_line() -> None:
    with _print_lock:
        sys.stdout.write('\r' + ' ' * 120 + '\r')
        sys.stdout.flush()


# --------------------------------------------------------------------------- #
#  MEGA-CMD resolver
# --------------------------------------------------------------------------- #
_WIN_DEFAULT_DIRS: List[Path] = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "MEGAcmd",
    Path(os.environ.get("PROGRAMFILES", "")) / "MEGAcmd",
    Path(os.environ.get("PROGRAMFILES(X86)", "")) / "MEGAcmd",
]

IS_WINDOWS = platform.system() == "Windows"

# Real candidate names for the non-interactive "get" client command.
# Windows ships these as .bat wrappers — "mega-get.exe" never existed.
_MEGA_GET_CANDIDATES = [
    "mega-get.bat", "mega-get.cmd", "mega-get.exe",
    "megaget.bat", "megaget.cmd", "megaget.exe",
]

# MEGAcmd writes to a temp file while a transfer is in progress, then renames
# it to the real filename on success. Never treat this as the final result.
_TEMP_ARTIFACT_RE = re.compile(r"^\.getxfer\.\d+\.\d+\.mega$", re.IGNORECASE)


def _is_temp_artifact(name: str) -> bool:
    return bool(_TEMP_ARTIFACT_RE.match(name)) or name.lower().endswith(".getxfer")


@dataclass
class MegaBackend:
    is_windows: bool
    mega_get_exe: Optional[Path] = None   # Windows: path to mega-get.bat/.exe
    megaget_bin: Optional[str] = None     # Linux/macOS: resolved binary name

    def describe(self) -> str:
        if self.is_windows:
            return f"mega-get  →  {self.mega_get_exe}"
        return f"mega-get  →  {self.megaget_bin}"


def _find_windows_mega_get(extra_dir: Optional[Path]) -> Optional[Path]:
    search_dirs: List[Path] = []
    if extra_dir:
        search_dirs.append(extra_dir)
    search_dirs.extend(_WIN_DEFAULT_DIRS)

    for d in search_dirs:
        for name in _MEGA_GET_CANDIDATES:
            candidate = d / name
            if candidate.exists():
                return candidate

    for name in _MEGA_GET_CANDIDATES:
        found = shutil.which(name)
        if found:
            return Path(found)

    return None


def resolve_backend(extra_dir: Optional[Path]) -> MegaBackend:
    if IS_WINDOWS:
        mega_get = _find_windows_mega_get(extra_dir)
        if mega_get is None:
            search_dirs = ([extra_dir] if extra_dir else []) + _WIN_DEFAULT_DIRS
            raise FileNotFoundError(
                "Could not find the non-interactive 'mega-get' client command.\n"
                "  On Windows it ships as 'mega-get.bat' inside the MEGAcmd\n"
                "  install folder (usually %LOCALAPPDATA%\\MEGAcmd).\n\n"
                "  Checked:\n" +
                "\n".join(f"    {d}" for d in search_dirs) +
                "\n\n  Fix options:\n"
                "    1) Add the folder to PATH, e.g. in PowerShell:\n"
                "         $env:PATH += \";$env:LOCALAPPDATA\\MEGAcmd\"\n"
                "    2) Or pass --megacmd-dir \"C:\\path\\to\\MEGAcmd\"\n"
                "    3) If MEGAcmd isn't installed: https://mega.io/cmd\n"
            )
        return MegaBackend(is_windows=True, mega_get_exe=mega_get)
    else:
        megaget = shutil.which("mega-get") or shutil.which("megaget")
        if not megaget:
            raise FileNotFoundError(
                "mega-get not found in PATH.\n"
                "  Install MEGA-CMD from https://mega.io/cmd"
            )
        return MegaBackend(is_windows=False, megaget_bin=megaget)


# --------------------------------------------------------------------------- #
#  MEGA-CMD auto-installer
# --------------------------------------------------------------------------- #
MEGACMD_DOWNLOAD_URL = "https://mega.io/cmd"


def install_megacmd() -> bool:
    """Attempt to install MEGA-CMD automatically.

    - Windows : open the download page in the browser + print instructions.
    - Linux   : try 'apt install megacmd' then 'snap install megacmd'.
    - macOS   : open the download page in the browser.

    Returns True when the tool is (or may be) available after this call.
    """
    system = platform.system()
    warn("MEGA-CMD (mega-get) was not found on this system.")

    if system == "Windows":
        print()
        print(f"{_C.CYAN}  MEGA-CMD is required for downloads.  Install steps:{_C.RESET}")
        print(f"  1) Download the installer from:  {_C.BOLD}{MEGACMD_DOWNLOAD_URL}{_C.RESET}")
        print(f"  2) Run the MSI installer.")
        print(f"  3) Add  %LOCALAPPDATA%\\MEGAcmd  to your PATH.")
        print(f"  4) Re-run this script.")
        print()
        try:
            open_yn = input("  Open the download page now? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            open_yn = "n"
        if open_yn in ("", "y", "yes"):
            import webbrowser
            webbrowser.open(MEGACMD_DOWNLOAD_URL)
        return False

    elif system == "Linux":
        print()
        print(f"{_C.CYAN}  Attempting automatic installation of MEGA-CMD on Linux...{_C.RESET}")
        # Method 1: apt
        if shutil.which("apt"):
            print(f"  {_C.DIM}[apt] Adding MEGA repository and installing megacmd...{_C.RESET}")
            cmds = [
                ["sudo", "apt", "install", "-y", "lsb-release", "apt-transport-https"],
                [
                    "bash", "-c",
                    "curl -fsSL https://mega.nz/linux/repo/Debian_12/Release.key "
                    "| gpg --dearmor | sudo tee /usr/share/keyrings/meganz.gpg > /dev/null"
                ],
                [
                    "bash", "-c",
                    "echo 'deb [signed-by=/usr/share/keyrings/meganz.gpg] "
                    "https://mega.nz/linux/repo/Debian_12/ ./' "
                    "| sudo tee /etc/apt/sources.list.d/meganz.list > /dev/null"
                ],
                ["sudo", "apt", "update", "-qq"],
                ["sudo", "apt", "install", "-y", "megacmd"],
            ]
            for cmd in cmds:
                try:
                    subprocess.run(cmd, check=True)
                except subprocess.CalledProcessError:
                    break
            if shutil.which("mega-get") or shutil.which("megaget"):
                ok("MEGA-CMD installed successfully via apt.")
                return True

        # Method 2: snap
        if shutil.which("snap"):
            print(f"  {_C.DIM}[snap] Installing megacmd via snap...{_C.RESET}")
            try:
                subprocess.run(["sudo", "snap", "install", "megacmd"], check=True)
                if shutil.which("mega-get") or shutil.which("megaget"):
                    ok("MEGA-CMD installed successfully via snap.")
                    return True
            except subprocess.CalledProcessError:
                pass

        print()
        print(f"{_C.RED}  Automatic installation failed.{_C.RESET}")
        print(f"  Please install manually from:  {_C.BOLD}{MEGACMD_DOWNLOAD_URL}{_C.RESET}")
        return False

    else:  # macOS and other
        print()
        print(f"{_C.CYAN}  MEGA-CMD is required.  Download from:{_C.RESET}")
        print(f"  {_C.BOLD}{MEGACMD_DOWNLOAD_URL}{_C.RESET}")
        try:
            import webbrowser
            webbrowser.open(MEGACMD_DOWNLOAD_URL)
        except Exception:
            pass
        return False


# --------------------------------------------------------------------------- #
#  HackMyVM integration
# --------------------------------------------------------------------------- #
def hmv_resolve_link(machine: str, user: str, password: str) -> Optional[str]:
    """Resolve the MEGA download link for a HackMyVM machine.

    Imports the HackMyVM class from hmv/script.py (located next to
    mega_download.py or in a 'hmv' sub-folder).  Credentials can be
    supplied via --hmv-user/--hmv-pass or the HMV_USER/HMV_PASS env vars.
    """
    # Locate script.py
    _here = Path(__file__).parent
    candidates = [
        _here / "hmv" / "script.py",
        _here / "script.py",
    ]
    script_path: Optional[Path] = None
    for c in candidates:
        if c.exists():
            script_path = c
            break

    if script_path is None:
        error(
            "HackMyVM script not found.  Expected at:\n"
            + "\n".join(f"  {c}" for c in candidates)
        )
        return None

    import importlib.util
    spec = importlib.util.spec_from_file_location("hmv_script", script_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception as exc:
        error(f"Failed to load HackMyVM script: {exc}")
        return None

    hmv = mod.HackMyVM(user, password)
    info(f"Logging in to HackMyVM as '{user}'...")
    if not hmv.login():
        error("HackMyVM login failed — check credentials.")
        return None
    ok("Logged in.")

    info(f"Resolving download link for machine '{machine}'...")
    link = hmv.resolve_download_link(machine)
    if not link:
        error(f"Could not resolve a MEGA link for machine '{machine}'.")
        return None
    ok(f"Resolved: {link}")
    return link


# --------------------------------------------------------------------------- #
#  Folder snapshot helpers (authoritative result detection)
# --------------------------------------------------------------------------- #
def _snapshot_folder(folder: Path) -> Dict[str, int]:
    snap: Dict[str, int] = {}
    if folder.exists():
        for f in folder.iterdir():
            if f.is_file():
                try:
                    snap[f.name] = f.stat().st_size
                except Exception:
                    pass
    return snap


def _find_real_downloaded_file(dest: Path, pre_snapshot: Dict[str, int]) -> Tuple[str, int]:
    """Compare the folder to how it looked before the download started and
    return the (filename, size) of whichever real file actually changed —
    skipping MEGAcmd's intermediate .getxfer temp artifacts entirely."""
    post_snapshot = _snapshot_folder(dest)
    candidates: List[Tuple[str, int]] = []

    for name, size in post_snapshot.items():
        if _is_temp_artifact(name):
            continue
        if name not in pre_snapshot or size != pre_snapshot.get(name):
            candidates.append((name, size))

    if not candidates:
        return "", 0

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0]


# --------------------------------------------------------------------------- #
#  Live folder monitor — cosmetic progress bar only
# --------------------------------------------------------------------------- #
class FolderMonitor:
    """Watches a folder while a transfer is in flight, purely to draw a live
    progress bar. It never decides success/failure or the final result —
    that always comes from a post-completion folder scan."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.initial_files: Dict[str, int] = {}
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.start_time: float = 0

    def snapshot(self) -> Dict[str, int]:
        self.initial_files = _snapshot_folder(self.folder)
        return self.initial_files

    def start_monitoring(self):
        self.snapshot()
        self.start_time = time.monotonic()
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()

    def _monitor_loop(self):
        while self.running:
            time.sleep(0.5)
            current_files = _snapshot_folder(self.folder)

            growing = {}
            for name, size in current_files.items():
                if name not in self.initial_files or size > self.initial_files.get(name, 0):
                    growing[name] = size

            if growing:
                largest_name, largest_size = max(growing.items(), key=lambda x: x[1])
                elapsed = time.monotonic() - self.start_time
                show_progress_bar(largest_name, largest_size, 0, elapsed)
            # No self-stop heuristic here on purpose — a real transfer can
            # legitimately stall for a few seconds (throttling, reconnects)
            # without being finished. Only stop() (called once the mega-get
            # process has actually exited) ends this loop.

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)


# --------------------------------------------------------------------------- #
#  Data model
# --------------------------------------------------------------------------- #
@dataclass
class LinkEntry:
    url:   str
    name:  str = ""
    level: str = ""
    size:  str = ""

    def label(self) -> str:
        if self.name:
            extra = "  ".join(p for p in (self.level, self.size) if p)
            return f"{self.name}  [{extra}]" if extra else self.name
        return self.url


@dataclass
class DownloadResult:
    url:      str
    success:  bool
    duration: float
    filename: str = ""
    size:     int = 0
    output:   str = ""


@dataclass
class Session:
    links:    List[LinkEntry]
    dest:     Path
    jobs:     int
    backend:  MegaBackend
    timeout:  int
    results:  List[DownloadResult] = field(default_factory=list)

    @property
    def succeeded(self) -> List[DownloadResult]:
        return [r for r in self.results if r.success]

    @property
    def failed(self) -> List[DownloadResult]:
        return [r for r in self.results if not r.success]


# --------------------------------------------------------------------------- #
#  Core download logic
# --------------------------------------------------------------------------- #
def _run_mega_get(cmd_line: List[str], dest: Path, timeout: int) -> Tuple[int, str, str, int]:
    """Launch a one-shot mega-get client process, show a live progress bar
    while it runs, then — once it has actually exited — scan the folder for
    the real resulting file. Returns (returncode, captured_output, filename, size)."""
    monitor = FolderMonitor(dest)
    pre_snapshot = monitor.snapshot()
    monitor.start_monitoring()

    proc = subprocess.Popen(
        cmd_line,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    try:
        captured_output, _ = proc.communicate(timeout=timeout)
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        monitor.stop()
        clear_progress_line()
        return -1, "Timeout waiting for mega-get to finish", "", 0

    monitor.stop()
    clear_progress_line()

    filename, size = _find_real_downloaded_file(dest, pre_snapshot)
    return returncode, (captured_output or "").strip(), filename, size


def download_windows(url: str, dest: Path, mega_get_exe: Path, timeout: int) -> DownloadResult:
    """Download on Windows using mega-get.bat (auto-starts MEGAcmdServer)."""
    t0 = time.monotonic()

    if mega_get_exe.suffix.lower() in (".bat", ".cmd"):
        cmd_line = ["cmd.exe", "/c", str(mega_get_exe), url, str(dest)]
    else:
        cmd_line = [str(mega_get_exe), url, str(dest)]

    returncode, output, filename, size = _run_mega_get(cmd_line, dest, timeout)

    return DownloadResult(
        url=url,
        success=(returncode == 0) and size > 0,
        duration=time.monotonic() - t0,
        filename=filename,
        size=size,
        output=output,
    )


def download_unix(url: str, dest: Path, megaget: str, timeout: int) -> DownloadResult:
    """Download on Linux/macOS using mega-get."""
    t0 = time.monotonic()

    cmd_line = [megaget, url, str(dest)]
    returncode, output, filename, size = _run_mega_get(cmd_line, dest, timeout)

    return DownloadResult(
        url=url,
        success=(returncode == 0) and size > 0,
        duration=time.monotonic() - t0,
        filename=filename,
        size=size,
        output=output,
    )


def download(url: str, session: Session) -> DownloadResult:
    if session.backend.is_windows:
        return download_windows(url, session.dest, session.backend.mega_get_exe, session.timeout)
    else:
        return download_unix(url, session.dest, session.backend.megaget_bin, session.timeout)


# --------------------------------------------------------------------------- #
#  Runner
# --------------------------------------------------------------------------- #
def run_session(session: Session) -> None:
    total = len(session.links)
    counter = {"n": 0}

    def _task(entry: LinkEntry) -> DownloadResult:
        with _print_lock:
            counter["n"] += 1
            idx = counter["n"]
        step(idx, total, entry.label())

        result = download(entry.url, session)

        if result.success:
            ok(f"Done in {timedelta(seconds=int(result.duration))}.  {result.filename or 'file'}  ({format_size(result.size)})")
        else:
            detail = result.output[:300] if result.output else "no output captured from mega-get"
            error(f"Failed.  {detail}")
        divider()
        return result

    if session.jobs == 1:
        for entry in session.links:
            session.results.append(_task(entry))
    else:
        warn("Running sequentially (parallel mode not enabled in this build).")
        for entry in session.links:
            session.results.append(_task(entry))


# --------------------------------------------------------------------------- #
#  Summary
# --------------------------------------------------------------------------- #
def print_summary(session: Session, elapsed: float) -> None:
    duration = str(timedelta(seconds=int(elapsed)))
    n_ok = len(session.succeeded)
    n_fail = len(session.failed)
    total = len(session.links)

    print(f"\n{_C.BOLD}{'SUMMARY':-<60}{_C.RESET}")
    print(f"  {'Total':<20} {total}")
    print(f"  {_C.GREEN}{'Succeeded':<20} {n_ok}{_C.RESET}")
    print(f"  {_C.RED}{'Failed':<20} {n_fail}{_C.RESET}")
    print(f"  {'Elapsed':<20} {duration}")
    print(f"  {'Destination':<20} {session.dest}")

    if session.succeeded:
        total_size = sum(r.size for r in session.succeeded)
        if total_size > 0:
            print(f"  {'Total downloaded':<20} {format_size(total_size)}")

    if n_fail:
        log_dir = session.dest / ".mega_dl_logs"
        log_dir.mkdir(exist_ok=True)
        fail_path = log_dir / "failed_links.txt"
        fail_path.write_text(
            "\n".join(r.url for r in session.failed) + "\n", encoding="utf-8"
        )
        print(f"\n{_C.YELLOW}  Failed links saved to: {fail_path}{_C.RESET}")


# --------------------------------------------------------------------------- #
#  Link loading + selection
# --------------------------------------------------------------------------- #
# Matches comment lines written by script.py's --save-links, e.g.:
#   # Calc  [Medium]  1.6 Gb
_META_RE = re.compile(r"^#\s*(?P<name>.+?)\s*\[(?P<level>[^\]]+)\]\s*(?P<size>.+?)\s*$")


def load_links(filepath: Path) -> List[LinkEntry]:
    if not filepath.exists():
        error(f"Links file not found: {filepath}")
        sys.exit(1)

    entries: List[LinkEntry] = []
    pending_name = pending_level = pending_size = ""

    with filepath.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                m = _META_RE.match(line)
                if m:
                    pending_name = m.group("name").strip()
                    pending_level = m.group("level").strip()
                    pending_size = m.group("size").strip()
                continue
            if "mega.nz" in line:
                entries.append(LinkEntry(
                    url=line, name=pending_name, level=pending_level, size=pending_size
                ))
                pending_name = pending_level = pending_size = ""

    if not entries:
        warn(f"No valid MEGA links found in '{filepath}'.")
        sys.exit(0)
    return entries


def parse_selection(spec: str, total: int) -> List[int]:
    """Parse '1', '1,3,5', '2-7', '1,3-5,8' or 'all' into sorted 1-based indices."""
    spec = spec.strip().lower()
    if spec in ("", "all", "*"):
        return list(range(1, total + 1))

    indices = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                a_str, b_str = part.split("-", 1)
                a, b = int(a_str.strip()), int(b_str.strip())
            except ValueError:
                continue
            if a > b:
                a, b = b, a
            indices.update(range(a, b + 1))
        else:
            try:
                indices.add(int(part))
            except ValueError:
                continue

    return sorted(i for i in indices if 1 <= i <= total)


def print_link_table(entries: List[LinkEntry]) -> None:
    divider()
    print(f"{_C.BOLD}{'#':<4}{'Name':<24}{'Level':<10}{'Size':<10}{'URL'}{_C.RESET}")
    divider()
    level_colour = {"easy": _C.GREEN, "medium": _C.YELLOW, "hard": _C.RED}
    for idx, e in enumerate(entries, 1):
        name = (e.name or "—")[:22]
        level = e.level or "—"
        size = e.size or "—"
        colour = level_colour.get(level.lower(), _C.RESET)
        url_short = e.url if len(e.url) <= 50 else e.url[:49] + "…"
        print(f"{idx:<4}{name:<24}{colour}{level:<10}{_C.RESET}{size:<10}{_C.DIM}{url_short}{_C.RESET}")
    divider()


def prompt_selection(entries: List[LinkEntry]) -> List[LinkEntry]:
    print_link_table(entries)
    print(f"{_C.CYAN}Select which to download — e.g. 1  |  1,3,5  |  2-7  |  all{_C.RESET}")
    try:
        spec = input(f"{_C.BOLD}> {_C.RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        spec = "all"
    indices = parse_selection(spec, len(entries))
    if not indices:
        warn("No valid selection recognised — downloading everything.")
        return entries
    chosen = [entries[i - 1] for i in indices]
    info(f"Selected {len(chosen)} of {len(entries)} link(s).")
    return chosen


def resolve_dest(dest: Optional[Path]) -> Path:
    default = Path.home() / "Downloads" / "MEGA"
    if dest is None:
        user_input = input(f"Destination directory [{default}]: ").strip()
        dest = Path(user_input) if user_input else default
    dest = Path(dest).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def megacmd_version(backend: MegaBackend) -> str:
    """Best-effort version lookup via the sibling mega-version client command."""
    try:
        if backend.is_windows:
            version_exe = None
            for candidate_name in ["mega-version.bat", "mega-version.cmd", "mega-version.exe"]:
                p = backend.mega_get_exe.parent / candidate_name
                if p.exists():
                    version_exe = p
                    break
            if version_exe is None:
                return "unknown"
            if version_exe.suffix.lower() in (".bat", ".cmd"):
                cmd_line = ["cmd.exe", "/c", str(version_exe)]
            else:
                cmd_line = [str(version_exe)]
            proc = subprocess.run(cmd_line, capture_output=True, text=True, timeout=15)
            output = (proc.stdout + proc.stderr).strip()
            return output.splitlines()[0] if output else "unknown"
        else:
            version_bin = shutil.which("mega-version") or shutil.which("megaversion")
            if not version_bin:
                return "unknown"
            return subprocess.check_output(
                [version_bin], stderr=subprocess.DEVNULL, text=True, timeout=10
            ).strip()
    except Exception:
        return "unknown"


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mega_download.py",
        description="Batch-download MEGA links using MEGA-CMD's non-interactive mega-get client.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("-f", "--file",
                   type=Path, default=Path("links.txt"), metavar="FILE",
                   help="Path to the links file  (default: links.txt)")
    p.add_argument("-d", "--dest",
                   type=Path, default=None, metavar="DIR",
                   help="Destination directory  (prompted if omitted)")
    p.add_argument("-j", "--jobs",
                   type=int, default=1, metavar="N",
                   help="Parallel download workers  (default: 1)")
    p.add_argument("--timeout",
                   type=int, default=7_200, metavar="SECS",
                   help="Per-file timeout in seconds  (default: 7200)")
    p.add_argument("--megacmd-dir",
                   type=Path, default=None, metavar="DIR",
                   help="Directory containing mega-get.bat  (Windows only)")
    p.add_argument("--select", type=str, default=None, metavar="SPEC",
                   help="Which entries to download: '1', '1,3,5', '2-7', '1,3-5,8', or 'all'.\n"
                        "If omitted in an interactive terminal you'll be prompted.")
    p.add_argument("--level", choices=["all", "easy", "medium", "hard"], default="all",
                   help="Filter entries by difficulty parsed from links.txt comments (default: all)")
    p.add_argument("--list", action="store_true",
                   help="Print the parsed link table and exit without downloading")

    # ── HackMyVM integration ────────────────────────────────────────────────
    hmv = p.add_argument_group("HackMyVM integration")
    hmv.add_argument("--hmv", type=str, default=None, metavar="MACHINE",
                     help="Resolve and download a HackMyVM machine by name "
                          "(e.g. --hmv Milk).  Skips the links file.")
    hmv.add_argument("--hmv-user", type=str,
                     default=os.environ.get("HMV_USER", ""),
                     metavar="USER",
                     help="HackMyVM username  (or set HMV_USER env var)")
    hmv.add_argument("--hmv-pass", type=str,
                     default=os.environ.get("HMV_PASS", ""),
                     metavar="PASS",
                     help="HackMyVM password  (or set HMV_PASS env var)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    # ── HackMyVM mode ───────────────────────────────────────────────────────
    if args.hmv:
        user = args.hmv_user
        password = args.hmv_pass
        if not user or not password:
            error(
                "HackMyVM credentials required.\n"
                "  Use --hmv-user / --hmv-pass, or set HMV_USER / HMV_PASS env vars."
            )
            return 1
        link = hmv_resolve_link(args.hmv, user, password)
        if not link:
            return 1
        entries = [LinkEntry(url=link, name=args.hmv, level="", size="")]
        info(f"Resolved 1 link for '{args.hmv}'.  Proceeding to download.")
        divider()
    else:
        # ── Normal file-based mode ─────────────────────────────────────────
        entries = load_links(args.file)

        if args.level != "all":
            filtered = [e for e in entries if e.level.lower() == args.level]
            if not filtered:
                warn(f"No links found with level '{args.level}' in '{args.file}'.")
                return 0
            entries = filtered

        if args.list:
            print_link_table(entries)
            return 0

        if args.select:
            indices = parse_selection(args.select, len(entries))
            if not indices:
                error(f"Invalid --select spec: '{args.select}'")
                return 1
            entries = [entries[i - 1] for i in indices]
            info(f"Selected {len(entries)} of {len(load_links(args.file))} link(s) via --select.")
        elif sys.stdin.isatty():
            entries = prompt_selection(entries)
        # else: non-interactive with no --select -> download everything

    # ── Resolve MEGA-CMD backend (with auto-install fallback) ───────────────
    try:
        backend = resolve_backend(args.megacmd_dir)
    except FileNotFoundError as exc:
        error(str(exc))
        installed = install_megacmd()
        if not installed:
            return 1
        # Retry after installation
        try:
            backend = resolve_backend(args.megacmd_dir)
        except FileNotFoundError:
            error("MEGA-CMD still not found after installation attempt.  Aborting.")
            return 1

    dest = resolve_dest(args.dest)
    jobs = max(1, args.jobs)

    info(f"Platform         : {platform.system()}")
    info(f"MEGA-CMD         : {backend.describe()}")
    info(f"MEGA-CMD version : {megacmd_version(backend)}")
    info(f"Destination      : {dest}")
    info(f"Links file       : {args.file}")
    info(f"Links to fetch   : {len(entries)}")
    info(f"Parallel jobs    : {jobs}")
    divider()

    session = Session(
        links=entries, dest=dest, jobs=jobs,
        backend=backend, timeout=args.timeout,
    )
    t0 = time.monotonic()
    run_session(session)
    elapsed = time.monotonic() - t0

    print_summary(session, elapsed)
    return 0 if not session.failed else 1


if __name__ == "__main__":
    sys.exit(main())