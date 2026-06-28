#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║         HackMyVM CLI Tool - Complete Edition                  ║
║   VMs • Challenges • Leaderboard • Labs • Submit Flags       ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import sys
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
import argparse
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings()
console = Console()


# ═══════════════════════════════════════════════════════════
#  HackMyVM CLASS
# ═══════════════════════════════════════════════════════════
class HackMyVM:
    """CLI tool to interact with HackMyVM."""

    def __init__(self, user, password):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/125.0.0.0 Safari/537.36')
        })
        self.base_url = "https://hackmyvm.eu"
        self.download_base = "https://downloads.hackmyvm.eu"
        self.credentials = {"admin": user, "password_usuario": password}

    def login(self):
        try:
            login_url = f"{self.base_url}/login/auth.php"
            res = self.session.post(login_url, data=self.credentials,
                                    allow_redirects=True, timeout=15)
            if 'logout' in res.text.lower() or 'dashboard' in res.text.lower() or res.ok:
                return True
            return False
        except requests.exceptions.RequestException:
            return False

    def fetch_all_machines_fast(self):
        machines = {}
        page = 1
        difficulty_map = {
            "#28a745": "Easy",
            "#ffc107": "Medium",
            "#dc3545": "Hard"
        }

        while True:
            url = f"{self.base_url}/machines/?l=all&p={page}"
            try:
                res = self.session.get(url, timeout=20)
                res.raise_for_status()
                soup = BeautifulSoup(res.text, 'html.parser')
                tbody = soup.find('tbody')
                rows = tbody.find_all('tr') if tbody else []

                if not rows:
                    break

                found_new = False
                for row in rows:
                    try:
                        cols = row.find_all('td')
                        if len(cols) < 3:
                            continue

                        name = cols[0].find('h4', class_='vmname').find('a').text.strip()
                        lower_name = name.lower()
                        if lower_name in machines:
                            continue
                        found_new = True

                        creator = cols[1].find('a', class_='creator').text.strip()
                        status = cols[0].find('span', class_='badge').text.strip()

                        size_tag = cols[2].find('p', class_='size')
                        size = size_tag.text.strip() if size_tag else "N/A"

                        div_style = cols[0].find('div', style=True)
                        if div_style:
                            style_attr = div_style['style']
                            level_hex = style_attr.split('solid')[-1].strip().replace(';', '').strip()
                            level = difficulty_map.get(level_hex, "Unknown")
                        else:
                            level = "Unknown"

                        machines[lower_name] = {
                            'name': name,
                            'creator': creator,
                            'status': status,
                            'size': size,
                            'level': level
                        }
                    except (AttributeError, IndexError, TypeError):
                        continue

                if not found_new:
                    break
                page += 1

            except requests.exceptions.RequestException:
                break

        return machines

    def resolve_download_link(self, machine_name):
        clean_name = machine_name.strip().lower().replace(' ', '')
        
        for ext in ['.zip', '.7z']:
            initial_url = f"https://downloads.hackmyvm.eu/{clean_name}{ext}"
            
            try:
                res = self.session.get(
                    initial_url,
                    allow_redirects=True,
                    timeout=15,
                    stream=True
                )
                
                if res.status_code == 200:
                    final_url = res.url
                    
                    if 'mega.nz' in final_url or 'drive.google.com' in final_url:
                        return final_url
                    elif final_url != initial_url and 'downloads.hackmyvm.eu' not in final_url:
                        return final_url
                    
            except requests.exceptions.RequestException:
                continue
        
        try:
            machine_page_url = f"{self.base_url}/machines/machine.php?vm={machine_name}"
            res = self.session.get(machine_page_url, timeout=10)
            
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                
                mega_link = soup.find('a', href=lambda href: href and 'mega.nz' in href)
                if mega_link:
                    return mega_link['href']
                
                drive_link = soup.find('a', href=lambda href: href and 'drive.google.com' in href)
                if drive_link:
                    return drive_link['href']
        except Exception:
            pass
        
        return None

    def submit_flag(self, flag, vm_name):
        url = f"{self.base_url}/machines/checkflag.php"
        data = {"flag": flag, "vm": vm_name}
        try:
            res = self.session.post(url, data=data, timeout=15)
            res.raise_for_status()
            
            if "wrong" in res.text.lower():
                return {"success": False, "message": "The flag is WRONG"}
            elif "correct" in res.text.lower():
                return {"success": True, "message": "CORRECT! Congratulations!"}
            elif "already" in res.text.lower():
                return {"success": None, "message": "You have already submitted the flag for this machine"}
            else:
                return {"success": False, "message": "Unknown response from server"}
        except requests.exceptions.RequestException as e:
            return {"success": False, "message": f"Flag submission failed: {e}"}

    def fetch_challenges(self):
        challenges = []
        page = 1
        
        while True:
            url = f"{self.base_url}/challenges/?p={page}"
            try:
                res = self.session.get(url, timeout=20)
                res.raise_for_status()
                soup = BeautifulSoup(res.text, 'html.parser')
                
                tbody = soup.find('tbody')
                if not tbody:
                    break
                
                rows = tbody.find_all('tr')
                if not rows:
                    break
                
                for row in rows:
                    try:
                        cols = row.find_all('td')
                        if len(cols) < 4:
                            continue
                        
                        name = cols[0].find('a').text.strip() if cols[0].find('a') else "N/A"
                        category = cols[1].text.strip() if len(cols) > 1 else "N/A"
                        level = cols[2].text.strip() if len(cols) > 2 else "N/A"
                        status = cols[3].text.strip() if len(cols) > 3 else "N/A"
                        
                        challenges.append({
                            'name': name,
                            'category': category,
                            'level': level,
                            'status': status
                        })
                    except Exception:
                        continue
                
                page += 1
            except Exception:
                break
        
        return challenges

    def fetch_leaderboard(self, limit=50):
        url = f"{self.base_url}/leaderboard/"
        try:
            res = self.session.get(url, timeout=20)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'html.parser')
            
            leaderboard = []
            tbody = soup.find('tbody')
            if tbody:
                rows = tbody.find_all('tr')[:limit]
                for idx, row in enumerate(rows, 1):
                    try:
                        cols = row.find_all('td')
                        if len(cols) < 3:
                            continue
                        
                        username = cols[0].text.strip()
                        points = cols[1].text.strip()
                        machines = cols[2].text.strip() if len(cols) > 2 else "N/A"
                        
                        leaderboard.append({
                            'rank': idx,
                            'username': username,
                            'points': points,
                            'machines': machines
                        })
                    except Exception:
                        continue
            
            return leaderboard
        except Exception:
            return []

    def fetch_labs(self):
        url = f"{self.base_url}/labs/"
        try:
            res = self.session.get(url, timeout=20)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'html.parser')
            
            labs = []
            cards = soup.find_all('div', class_='card')
            
            for card in cards:
                try:
                    name_tag = card.find('h5') or card.find('h4')
                    name = name_tag.text.strip() if name_tag else "N/A"
                    
                    desc_tag = card.find('p', class_='card-text')
                    description = desc_tag.text.strip() if desc_tag else "N/A"
                    
                    link_tag = card.find('a')
                    link = link_tag['href'] if link_tag else "N/A"
                    
                    labs.append({
                        'name': name,
                        'description': description,
                        'link': link
                    })
                except Exception:
                    continue
            
            return labs
        except Exception:
            return []

    def submit_vm(self, vm_data):
        url = f"{self.base_url}/submit/vm.php"
        try:
            res = self.session.post(url, data=vm_data, timeout=15)
            res.raise_for_status()
            
            if "success" in res.text.lower() or "thank" in res.text.lower():
                return {"success": True, "message": "VM submitted successfully!"}
            else:
                return {"success": False, "message": "VM submission may have failed. Check the website."}
        except Exception as e:
            return {"success": False, "message": f"Submission failed: {e}"}

    def submit_challenge(self, challenge_data):
        url = f"{self.base_url}/submit/challenge.php"
        try:
            res = self.session.post(url, data=challenge_data, timeout=15)
            res.raise_for_status()
            
            if "success" in res.text.lower() or "thank" in res.text.lower():
                return {"success": True, "message": "Challenge submitted successfully!"}
            else:
                return {"success": False, "message": "Challenge submission may have failed. Check the website."}
        except Exception as e:
            return {"success": False, "message": f"Submission failed: {e}"}


# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════
def scan_local_files(directory):
    local_files = {}
    valid_exts = ('.zip', '.7z', '.ova', '.vbox', '.rar')
    for f in os.listdir(directory):
        if f.lower().endswith(valid_exts):
            vm_name = os.path.splitext(f)[0].lower()
            local_files[vm_name] = f
    return local_files


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════
def main():
    DEFAULT_DIRECTORY = r"E:\2026\VirtualBox-VMs\HackmyVm\ok-2026"
    
    parser = argparse.ArgumentParser(
        description="HackMyVM CLI Tool - Complete Edition",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('-v', '--vms', action='store_true',
                           help="List VMs with local comparison (default mode)")
    mode_group.add_argument('-c', '--challenges', action='store_true',
                           help="List all challenges from HackMyVM")
    mode_group.add_argument('-l', '--leaderboard', action='store_true',
                           help="Show leaderboard")
    mode_group.add_argument('--labs', action='store_true',
                           help="Show HMV Labs")
    mode_group.add_argument('-s', '--submit-flag', nargs=2, metavar=('FLAG', 'VM_NAME'),
                           help="Submit a flag for a VM")
    mode_group.add_argument('--submit-vm', action='store_true',
                           help="Submit a new VM (interactive)")
    mode_group.add_argument('--submit-challenge', action='store_true',
                           help="Submit a new challenge (interactive)")
    
    # VM mode options
    parser.add_argument('-d', '--directory', default=DEFAULT_DIRECTORY,
                        help=f"Directory containing local VM files (default: {DEFAULT_DIRECTORY})")
    parser.add_argument('-f', '--filter',
                        choices=['all', 'missing', 'tohacking', 'downloaded',
                                 'local-unsolved', 'easy', 'medium', 'hard'],
                        default='all',
                        help="Filter VMs")
    parser.add_argument('--no-links', action='store_true',
                        help="Skip resolving download links")
    parser.add_argument('--workers', type=int, default=10,
                        help="Threads for resolving links (default: 10)")
    parser.add_argument('--save-links', nargs='?', const='links.txt', default=None,
                        metavar='FILE',
                        help="Save resolved MEGA links of unsolved (TO HACK) machines\n"
                             "that aren't downloaded locally yet into FILE, ready to\n"
                             "feed into mega_download.py (default file: links.txt).\n"
                             "Implies link resolution even if --no-links is passed.")
    
    args = parser.parse_args()

    if args.save_links and args.no_links:
        console.print("[bold yellow]⚠️  --save-links needs resolved links; ignoring --no-links.[/]")
        args.no_links = False

    USER = "wassim58"
    PASSWORD = "!!##radarp19##!!"

    if not USER or not PASSWORD:
        console.print("[bold red]❌ Please set USER and PASSWORD in the script.[/]")
        sys.exit(1)

    # ── Banner ───────────────────────────────────────────────
    console.print(Panel.fit(
        "[bold cyan]⚡ HackMyVM[/] [bold white]CLI Tool - Complete Edition[/]\n"
        "[dim]VMs • Challenges • Leaderboard • Labs • Submit Flags[/]",
        border_style="bright_cyan",
        box=box.DOUBLE_EDGE
    ))
    console.print()

    # ── Login ────────────────────────────────────────────────
    cli = HackMyVM(USER, PASSWORD)
    with console.status("[bold cyan]🔐 Logging in to HackMyVM...[/]"):
        if not cli.login():
            console.print("[bold red]❌ Login failed! Check credentials.[/]")
            sys.exit(1)
    console.print(f"[bold green]✅ Logged in as[/] [bold bright_white]{USER}[/]")
    console.print()

    # ── MODE: Submit Flag ────────────────────────────────────
    if args.submit_flag:
        flag, vm_name = args.submit_flag
        console.print(f"[bold cyan]🚩 Submitting flag for[/] [bold]{vm_name}[/]...")
        result = cli.submit_flag(flag, vm_name)
        
        if result['success'] is True:
            console.print(f"[bold green]✅ {result['message']}[/]")
        elif result['success'] is None:
            console.print(f"[bold yellow]⚠️  {result['message']}[/]")
        else:
            console.print(f"[bold red]❌ {result['message']}[/]")
        return

    # ── MODE: Submit VM ──────────────────────────────────────
    if args.submit_vm:
        console.print("[bold cyan]📤 Submit New VM[/]")
        console.print("[dim]Fill in the details below:[/]\n")
        
        vm_data = {
            'name': input("VM Name: "),
            'url': input("URL (download link): "),
            'user_flag': input("User Flag: "),
            'root_flag': input("Root Flag: "),
            'tags': input("Tags (comma-separated, e.g., lfi,log poisoning,csrf): "),
            'level': input("Level (Easy/Medium/Hard): "),
            'notes': input("Notes: "),
            'writeup': input("Writeup (summary or URL): ")
        }
        
        result = cli.submit_vm(vm_data)
        if result['success']:
            console.print(f"\n[bold green]✅ {result['message']}[/]")
        else:
            console.print(f"\n[bold red]❌ {result['message']}[/]")
        return

    # ── MODE: Submit Challenge ───────────────────────────────
    if args.submit_challenge:
        console.print("[bold cyan]📤 Submit New Challenge[/]")
        console.print("[dim]Fill in the details below:[/]\n")
        
        challenge_data = {
            'category': input("Category (Stego, Web, Crypto, etc.): "),
            'flag': input("Challenge Flag: "),
            'level': input("Level (explain how to implement): "),
            'url_file': input("URL File (optional): "),
            'solution': input("Solution (how to solve): ")
        }
        
        result = cli.submit_challenge(challenge_data)
        if result['success']:
            console.print(f"\n[bold green]✅ {result['message']}[/]")
        else:
            console.print(f"\n[bold red]❌ {result['message']}[/]")
        return

    # ── MODE: Challenges ─────────────────────────────────────
    if args.challenges:
        with console.status("[bold cyan]🎯 Fetching challenges...[/]"):
            challenges = cli.fetch_challenges()
        
        if not challenges:
            console.print("[bold red]❌ No challenges found or failed to fetch.[/]")
            return
        
        table = Table(
            title="\n[bold bright_white]🎯 HackMyVM Challenges[/]",
            box=box.ROUNDED,
            border_style="bright_cyan",
            header_style="bold white on dark_blue"
        )
        
        table.add_column("#", style="dim", justify="right", width=4)
        table.add_column("Name", style="bold bright_white", min_width=20)
        table.add_column("Category", justify="center", width=15)
        table.add_column("Level", justify="center", width=12)
        table.add_column("Status", justify="center", width=12)
        
        for idx, ch in enumerate(challenges, 1):
            level_color = {'Easy': 'green', 'Medium': 'yellow', 'Hard': 'red'}.get(ch['level'], 'white')
            status_color = 'green' if 'solved' in ch['status'].lower() else 'yellow'
            
            table.add_row(
                str(idx),
                ch['name'],
                ch['category'],
                f"[{level_color}]{ch['level']}[/]",
                f"[{status_color}]{ch['status']}[/]"
            )
        
        console.print(table)
        console.print(f"\n[bold green]✅ Found {len(challenges)} challenges[/]")
        return

    # ── MODE: Leaderboard ────────────────────────────────────
    if args.leaderboard:
        with console.status("[bold cyan]🏆 Fetching leaderboard...[/]"):
            leaderboard = cli.fetch_leaderboard(limit=50)
        
        if not leaderboard:
            console.print("[bold red]❌ Failed to fetch leaderboard.[/]")
            return
        
        table = Table(
            title="\n[bold bright_white]🏆 HackMyVM Leaderboard - Top 50[/]",
            box=box.ROUNDED,
            border_style="bright_cyan",
            header_style="bold white on dark_blue"
        )
        
        table.add_column("Rank", style="bold yellow", justify="right", width=6)
        table.add_column("Username", style="bold bright_white", min_width=20)
        table.add_column("Points", justify="right", width=12)
        table.add_column("Machines", justify="right", width=12)
        
        for entry in leaderboard:
            rank_style = "bold magenta" if entry['rank'] <= 3 else "white"
            table.add_row(
                f"[{rank_style}]#{entry['rank']}[/]",
                entry['username'],
                f"[bold cyan]{entry['points']}[/]",
                entry['machines']
            )
        
        console.print(table)
        return

    # ── MODE: Labs ───────────────────────────────────────────
    if args.labs:
        with console.status("[bold cyan]🧪 Fetching labs...[/]"):
            labs = cli.fetch_labs()
        
        if not labs:
            console.print("[bold red]❌ No labs found or failed to fetch.[/]")
            return
        
        table = Table(
            title="\n[bold bright_white]🧪 HackMyVM Labs[/]",
            box=box.ROUNDED,
            border_style="bright_cyan",
            header_style="bold white on dark_blue"
        )
        
        table.add_column("#", style="dim", justify="right", width=4)
        table.add_column("Name", style="bold bright_white", min_width=25)
        table.add_column("Description", min_width=40)
        table.add_column("Link", min_width=30)
        
        for idx, lab in enumerate(labs, 1):
            link_str = f"[link={lab['link']}][bright_cyan underline]{lab['link']}[/][/]" if lab['link'] != "N/A" else "[dim]N/A[/]"
            table.add_row(
                str(idx),
                lab['name'],
                lab['description'][:100] + "..." if len(lab['description']) > 100 else lab['description'],
                link_str
            )
        
        console.print(table)
        console.print(f"\n[bold green]✅ Found {len(labs)} labs[/]")
        return

    # ── MODE: VMs (Default) ──────────────────────────────────
    console.print(f"[dim]📁 Directory:[/] [bold bright_white]{args.directory}[/]")
    console.print(f"[dim]🔍 Filter:[/]    [bold bright_white]{args.filter}[/]")
    console.print(f"[dim]⚙️  Workers:[/]   [bold bright_white]{args.workers}[/]")
    console.print(f"[dim]🔗 Links:[/]     [bold bright_white]{'Enabled' if not args.no_links else 'Disabled'}[/]")
    console.print()

    scan_dir = os.path.abspath(args.directory)
    if not os.path.isdir(scan_dir):
        console.print(f"[bold red]❌ Directory not found: {scan_dir}[/]")
        sys.exit(1)

    local_files = scan_local_files(scan_dir)
    console.print(f"[bold green]✅ Found[/] [bold bright_white]{len(local_files)}[/]"
                  f" [green]VM files in[/] [bold]{scan_dir}[/]")

    with console.status("[bold cyan]🌐 Fetching all machines from HackMyVM...[/]"):
        remote_vms = cli.fetch_all_machines_fast()
    console.print(f"[bold green]✅ Fetched[/] [bold bright_white]{len(remote_vms)}[/]"
                  f" [green]machines from website[/]")

    download_links = {}
    if not args.no_links:
        need_links = [
            k for k, v in remote_vms.items()
            if k not in local_files and v['status'] == 'TO HACK'
        ]

        if need_links:
            with Progress(
                SpinnerColumn(style="cyan"),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(bar_width=30, style="bright_blue", complete_style="bright_green"),
                TextColumn("[bold]{task.completed}/{task.total}"),
                console=console
            ) as progress:
                task = progress.add_task("🔗 Resolving download links...", total=len(need_links))

                with ThreadPoolExecutor(max_workers=args.workers) as pool:
                    futures = {pool.submit(cli.resolve_download_link, vm): vm for vm in need_links}
                    for future in as_completed(futures):
                        vm = futures[future]
                        try:
                            link = future.result()
                            if link:
                                download_links[vm] = link
                        except Exception:
                            pass
                        progress.advance(task)
        else:
            console.print("[bold green]✅ All TO HACK machines are already downloaded locally![/]")
    else:
        console.print("[dim]⏭  Skipped link resolution (--no-links)[/]")

    # ── Save unsolved machines' links to a file for mega_download.py ────
    if args.save_links:
        mega_items = sorted(
            ((vm, link) for vm, link in download_links.items() if 'mega.nz' in link),
            key=lambda item: remote_vms[item[0]]['name'].lower()
        )
        skipped_items = [
            (vm, link) for vm, link in download_links.items() if 'mega.nz' not in link
        ]

        save_path = os.path.abspath(args.save_links)
        with open(save_path, 'w', encoding='utf-8') as fh:
            fh.write("# HackMyVM — unsolved (TO HACK) machines, not yet downloaded locally\n")
            fh.write(f"# Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            fh.write(f"# Run with:  python mega_download.py -f \"{save_path}\"\n\n")

            for vm, link in mega_items:
                vm_info = remote_vms[vm]
                fh.write(f"# {vm_info['name']}  [{vm_info['level']}]  {vm_info['size']}\n")
                fh.write(f"{link}\n\n")

            if skipped_items:
                fh.write("\n# --- Non-MEGA links found (mega_download.py only handles mega.nz) ---\n")
                for vm, link in skipped_items:
                    vm_info = remote_vms[vm]
                    fh.write(f"# {vm_info['name']}: {link}\n")

        console.print()
        console.print(f"[bold green]💾 Saved[/] [bold bright_white]{len(mega_items)}[/]"
                      f" [green]MEGA link(s) for unsolved machines to[/]"
                      f" [bold cyan]{save_path}[/]")
        if skipped_items:
            console.print(f"[dim]   ({len(skipped_items)} non-MEGA link(s) listed as comments only — "
                          f"mega_download.py won't pick them up)[/]")
        console.print(f"[dim]   Next step: python mega_download.py -f \"{save_path}\"[/]")

    rows_data = []
    stats = {
        'total': 0,
        'local': 0,
        'local_to_hack': 0,
        'local_solved': 0,
        'missing_hack': 0,
        'missing_solved': 0
    }

    for vm_key in sorted(remote_vms.keys()):
        info = remote_vms[vm_key]
        is_local = vm_key in local_files
        is_to_hack = info['status'].upper() == 'TO HACK'

        stats['total'] += 1
        if is_local:
            stats['local'] += 1
            if is_to_hack:
                stats['local_to_hack'] += 1
            else:
                stats['local_solved'] += 1
        else:
            if is_to_hack:
                stats['missing_hack'] += 1
            else:
                stats['missing_solved'] += 1

        if args.filter == 'missing' and is_local:
            continue
        if args.filter == 'tohacking' and (is_local or not is_to_hack):
            continue
        if args.filter == 'downloaded' and not is_local:
            continue
        if args.filter == 'local-unsolved' and not (is_local and is_to_hack):
            continue
        if args.filter in ('easy', 'medium', 'hard') and info['level'].lower() != args.filter:
            continue

        rows_data.append((vm_key, info, is_local, is_to_hack))

    console.print()

    table = Table(
        title=f"\n[bold bright_white]📊 HackMyVM Lab Report[/]"
              f"  [dim](Filter: {args.filter})[/]",
        box=box.ROUNDED,
        border_style="bright_cyan",
        header_style="bold white on dark_blue",
        row_styles=["", "dim"],
        show_lines=False,
        pad_edge=True,
        expand=False
    )

    table.add_column("#", style="dim", justify="right", width=4, no_wrap=True)
    table.add_column("Machine", style="bold bright_white", min_width=16, no_wrap=True)
    table.add_column("Level", justify="center", width=11)
    table.add_column("Status", justify="center", width=13)
    table.add_column("Creator", min_width=10, max_width=16)
    table.add_column("Size", justify="right", width=9, no_wrap=True)
    table.add_column("Local File", min_width=20)
    table.add_column("Download Link", min_width=45, max_width=70)

    for idx, (vm_key, info, is_local, is_to_hack) in enumerate(rows_data, 1):
        lvl = info['level']
        if lvl == 'Easy':
            level_str = "[bold green]● Easy[/]"
        elif lvl == 'Medium':
            level_str = "[bold yellow]● Medium[/]"
        elif lvl == 'Hard':
            level_str = "[bold red]● Hard[/]"
        else:
            level_str = f"[dim]● {lvl}[/]"

        if is_to_hack:
            status_str = "[bold yellow]⚡ TO HACK[/]"
        else:
            status_str = "[bold green]✔ SOLVED[/]"

        if is_local:
            local_str = f"[bold green]✔[/] [green]{local_files[vm_key]}[/]"
        else:
            local_str = "[bold red]✗ Missing[/]"

        if not is_local and is_to_hack and vm_key in download_links:
            link = download_links[vm_key]
            if 'mega.nz' in link:
                link_str = f"[link={link}][bold magenta]🔗 MEGA:[/] [bright_cyan underline]{link}[/][/]"
            elif 'drive.google.com' in link:
                link_str = f"[link={link}][bold blue]🔗 GDRIVE:[/] [bright_cyan underline]{link}[/][/]"
            else:
                link_str = f"[link={link}][bold green]🔗 DIRECT:[/] [bright_cyan underline]{link}[/][/]"
        elif not is_local and is_to_hack and not args.no_links:
            link_str = "[red italic]✗ not found[/]"
        elif not is_local and is_to_hack and args.no_links:
            link_str = "[dim italic]use without --no-links[/]"
        elif is_local:
            link_str = "[dim]—[/]"
        else:
            link_str = "[dim italic](already solved)[/]"

        table.add_row(
            str(idx),
            info['name'],
            level_str,
            status_str,
            info['creator'],
            info['size'],
            local_str,
            link_str
        )

    console.print(table)

    console.print()

    summary_table = Table(box=None, show_header=False, expand=False, pad_edge=False)
    summary_table.add_column("Icon", width=3, no_wrap=True)
    summary_table.add_column("Label", width=35)
    summary_table.add_column("Value", justify="right", width=8)

    summary_table.add_row("🌐", "[bold]Total machines on HackMyVM[/]", f"[bold bright_white]{stats['total']}[/]")
    summary_table.add_row("", "", "")
    summary_table.add_row("💾", "[bold cyan]Downloaded locally[/]", f"[bold cyan]{stats['local']}[/]")
    summary_table.add_row("🔴", "[bold red]  └─ TO HACK (not solved)[/]", f"[bold red]{stats['local_to_hack']}[/]")
    summary_table.add_row("✅", "[bold green]  └─ SOLVED (completed)[/]", f"[bold green]{stats['local_solved']}[/]")
    summary_table.add_row("", "", "")
    summary_table.add_row("📥", "[bold yellow]Missing (not downloaded)[/]", f"[bold yellow]{stats['total'] - stats['local']}[/]")
    summary_table.add_row("⚡", "[bold yellow]  └─ TO HACK[/]", f"[bold yellow]{stats['missing_hack']}[/]")
    summary_table.add_row("✔", "[dim]  └─ Already SOLVED[/]", f"[dim]{stats['missing_solved']}[/]")
    summary_table.add_row("", "", "")
    summary_table.add_row("📋", "Rows shown in table", f"[bold cyan]{len(rows_data)}[/]")
    
    if download_links:
        mega_count = sum(1 for link in download_links.values() if 'mega.nz' in link)
        gdrive_count = sum(1 for link in download_links.values() if 'drive.google.com' in link)
        direct_count = len(download_links) - mega_count - gdrive_count
        
        summary_table.add_row("", "", "")
        summary_table.add_row("🔗", "[magenta]Mega links found[/]", f"[bold magenta]{mega_count}[/]")
        summary_table.add_row("🔗", "[blue]Google Drive links found[/]", f"[bold blue]{gdrive_count}[/]")
        if direct_count > 0:
            summary_table.add_row("🔗", "[green]Direct links found[/]", f"[bold green]{direct_count}[/]")

    if stats['total'] > 0:
        summary_table.add_row("", "", "")
        pct = (stats['local'] / stats['total']) * 100
        bar_len = 30
        filled = int(bar_len * pct / 100)
        bar = f"[green]{'█' * filled}[/][dim]{'░' * (bar_len - filled)}[/]"
        summary_table.add_row("📈", "[bold]Collection Progress[/]", f"{bar} [bold]{pct:.1f}%[/]")
        
        if stats['local'] > 0:
            solve_pct = (stats['local_solved'] / stats['local']) * 100
            solve_bar_len = 30
            solve_filled = int(solve_bar_len * solve_pct / 100)
            solve_bar = f"[green]{'█' * solve_filled}[/][dim]{'░' * (solve_bar_len - solve_filled)}[/]"
            summary_table.add_row("🎯", "[bold]Solve Progress (local)[/]", f"{solve_bar} [bold]{solve_pct:.1f}%[/]")

    console.print(Panel(
        summary_table,
        title="[bold green]📈 Comprehensive Summary[/]",
        border_style="green",
        box=box.ROUNDED,
        expand=False
    ))

    console.print()
    if stats['local_to_hack'] > 0:
        console.print(f"[bold yellow]💡 Tip:[/] You have [bold red]{stats['local_to_hack']}[/] machines downloaded but not solved.")
        console.print(f"        Run with [bold cyan]-f local-unsolved[/] to see them.")
    
    if stats['missing_hack'] > 0:
        console.print(f"[bold yellow]💡 Tip:[/] You still need to download [bold red]{stats['missing_hack']}[/] machines.")
        console.print(f"        Run with [bold cyan]-f tohacking[/] to see them with download links.")
    
    console.print(f"[bold yellow]💡 Tip:[/] Run with [bold cyan]--no-links[/] for faster results without resolving URLs.")
    console.print()


if __name__ == "__main__":
    main()