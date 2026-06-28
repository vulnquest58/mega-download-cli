# MEGA Download CLI

> Batch-download MEGA links using MEGA-CMD — with HackMyVM direct integration and automatic MEGA-CMD installer.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=flat-square&logo=python)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-informational?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

---

## Features

| Feature | Description |
|---------|-------------|
| 📥 **Batch download** | Download all MEGA links from a `links.txt` file in one shot |
| 🎯 **Selection** | Pick specific entries: `--select "1,3-5"` or `--level easy` |
| 🎮 **HackMyVM integration** | `--hmv <MachineName>` resolves and downloads directly without a links file |
| 🔧 **Auto-install MEGA-CMD** | Detects missing `mega-get` and installs it automatically (apt/snap on Linux, browser prompt on Windows) |
| 📊 **Progress bar** | Live progress with speed, ETA, and file size |
| 🔁 **Parallel jobs** | `--jobs N` for concurrent downloads |

---

## Requirements

```bash
pip install requests beautifulsoup4 rich
```

MEGA-CMD must be installed (the script will offer to install it if missing):
- **Windows/macOS**: <https://mega.io/cmd>
- **Linux**: installed automatically via `apt` or `snap`

---

## Usage

### Download from a links file

```bash
python mega_download.py -f links.txt -d ~/Downloads/VMs
```

### Select specific entries

```bash
# Interactive selection prompt
python mega_download.py -f links.txt

# By index
python mega_download.py -f links.txt --select "1,3-5"

# By difficulty
python mega_download.py -f links.txt --level easy
```

### Download a HackMyVM machine directly

```bash
# Via CLI flags
python mega_download.py --hmv Milk --hmv-user youruser --hmv-pass yourpass -d ~/VMs

# Via environment variables (recommended)
export HMV_USER=youruser
export HMV_PASS=yourpass
python mega_download.py --hmv Milk -d ~/VMs
```

### List links without downloading

```bash
python mega_download.py -f links.txt --list
```

---

## Options

```
positional / main:
  -f FILE, --file FILE        Path to links file (default: links.txt)
  -d DIR,  --dest DIR         Destination directory (prompted if omitted)
  -j N,    --jobs N           Parallel workers (default: 1)
  --timeout SECS              Per-file timeout in seconds (default: 7200)
  --megacmd-dir DIR           Path to MEGAcmd folder (Windows, optional)
  --select SPEC               Entry selection: "1", "1,3,5", "2-7", "all"
  --level {easy,medium,hard}  Filter by difficulty
  --list                      Print link table and exit

HackMyVM integration:
  --hmv MACHINE               Machine name to resolve and download
  --hmv-user USER             HackMyVM username (or HMV_USER env var)
  --hmv-pass PASS             HackMyVM password (or HMV_PASS env var)
```

---

## links.txt Format

Generated automatically by `hmv/script.py --save-links`, or written manually:

```
# MachineName  [Easy]  1.2 GB
https://mega.nz/file/...

# AnotherBox   [Hard]  3.7 GB
https://mega.nz/folder/...
```

---

## HackMyVM CLI (`hmv/script.py`)

The bundled `hmv/script.py` is a full HackMyVM CLI companion:

```bash
# List all VMs with download links
python hmv/script.py -v

# Save undownloaded MEGA links to links.txt
python hmv/script.py --save-links links.txt -d /path/to/local/vms

# Show leaderboard
python hmv/script.py -l

# Submit a flag
python hmv/script.py -s user.txt MachineName
```

---

## Auto-install MEGA-CMD

When `mega-get` is not found:

- **Linux**: automatically runs `apt install megacmd` or `snap install megacmd`
- **Windows**: prints step-by-step instructions and optionally opens the download page
- **macOS**: opens the MEGA download page

---

## License

MIT — see [LICENSE](LICENSE)
