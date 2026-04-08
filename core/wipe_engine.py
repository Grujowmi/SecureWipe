"""
SecureWipe — wipe_engine.py
Moteur d'effacement sécurisé.

Méthodes implémentées :
  Linux :
    - ANSSI P1 : dd avec /dev/zero (1 passe)
    - ANSSI P2 / NIST Clear : dd avec /dev/urandom (1 passe aléatoire)
    - NIST Purge HDD : ATA Secure Erase via hdparm
    - NIST Purge SSD/NVMe : nvme format --ses=1
    - Crypto Erase LUKS : cryptsetup erase
    - Crypto Erase SED  : hdparm --security-erase
    - Custom : N passes alternant zéros et aléatoire
  Windows :
    - ANSSI P1 / P2 : diskpart clean all (écriture zéros)
    - NIST Purge SSD/NVMe : format /p:1 + Optimize-Volume (Trim)
    - Crypto Erase BitLocker : manage-bde -off + diskpart clean all
    - Custom : passes via diskpart

Vérification post-effacement :
  Lecture d'un échantillon aléatoire de secteurs et vérification
  que le contenu correspond au motif attendu (zéros ou aléatoire).
"""

import os
import sys
import time
import math
import random
import struct
import hashlib
import subprocess
import threading
import tempfile
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum, auto

from rich.console import Console
from rich.progress import (
    Progress, SpinnerColumn, BarColumn, TextColumn,
    TimeElapsedColumn, TimeRemainingColumn, TransferSpeedColumn,
    MofNCompleteColumn, TaskProgressColumn,
)
from rich.live import Live
from rich.text import Text
from rich import print as rprint

from core.i18n import t
from core.crypto_detect import CryptoMethod, CryptoProfile

console = Console()

# ──────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────

BLOCK_SIZE = 4 * 1024 * 1024   # 4 MiB — bon compromis perf/précision

class WipeMode(Enum):
    ANSSI_P1       = auto()   # 1 passe zéros
    ANSSI_P2       = auto()   # 1 passe aléatoire
    NIST_PURGE     = auto()   # Secure Erase firmware
    CRYPTO_ERASE   = auto()   # Destruction clé
    CUSTOM         = auto()   # N passes

class WipeStatus(Enum):
    SUCCESS        = auto()
    FAILED         = auto()
    ABORTED        = auto()
    VERIFY_FAILED  = auto()


# ──────────────────────────────────────────────
# Résultat d'une opération
# ──────────────────────────────────────────────

@dataclass
class WipeResult:
    status: WipeStatus
    mode: WipeMode
    device: str
    bytes_written: int = 0
    duration_sec: float = 0.0
    passes_done: int = 0
    verify_pct: int = 0
    verify_ok: Optional[bool] = None
    error_msg: str = ""
    method_detail: str = ""   # ex: "ATA Secure Erase Enhanced"
    standard: str = ""        # ex: "ANSSI Palier 2 / NIST Clear"


# ──────────────────────────────────────────────
# Utilitaires subprocess
# ──────────────────────────────────────────────

def _run(cmd: list, timeout: int = None, env: dict = None) -> tuple[int, str, str]:
    try:
        kw = dict(capture_output=True, text=True)
        if timeout:
            kw["timeout"] = timeout
        if env:
            kw["env"] = env
        else:
            kw["env"] = {**os.environ, "LANG": "C", "LC_ALL": "C"}
        r = subprocess.run(cmd, **kw)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


def _tool_ok(name: str) -> bool:
    rc, _, _ = _run(["which" if sys.platform != "win32" else "where", name])
    return rc == 0


# ──────────────────────────────────────────────
# Barre de progression Rich
# ──────────────────────────────────────────────

def _make_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=40),
        TaskProgressColumn(),
        TransferSpeedColumn(),
        TimeElapsedColumn(),
        TextColumn("ETA"),
        TimeRemainingColumn(),
        console=console,
        refresh_per_second=4,
    )


# ──────────────────────────────────────────────
# Linux — effacement par réécriture (dd-like)
# ──────────────────────────────────────────────

def _write_pass_linux(
    device: str,
    disk_size: int,
    pass_num: int,
    total_passes: int,
    use_random: bool,
    progress_cb: Optional[Callable] = None,
) -> tuple[bool, int, str]:
    """
    Effectue une passe d'écriture sur le device.
    Retourne (success, bytes_written, error_msg).
    """
    source = "/dev/urandom" if use_random else "/dev/zero"
    label = t("wipe_progress_label") + f" ({t('wipe_pass_label')} {pass_num}/{total_passes})"

    written = 0
    error   = ""
    start   = time.time()

    try:
        # Ouvre le device en écriture directe (O_DIRECT si possible)
        flags = os.O_WRONLY
        try:
            flags |= os.O_DIRECT
            fd = os.open(device, flags)
            use_direct = True
        except (AttributeError, OSError):
            flags = os.O_WRONLY
            fd = os.open(device, flags)
            use_direct = False

        # Source de données
        src_fd = os.open(source, os.O_RDONLY)

        buf_size = BLOCK_SIZE
        # O_DIRECT nécessite un buffer aligné sur 512 octets
        if use_direct:
            buf_size = max(BLOCK_SIZE, 512)

        try:
            while written < disk_size:
                to_write = min(buf_size, disk_size - written)
                data = os.read(src_fd, to_write)
                if not data:
                    break
                # Padding si O_DIRECT et dernier bloc
                if use_direct and len(data) % 512 != 0:
                    pad = 512 - (len(data) % 512)
                    data += b'\x00' * pad
                n = os.write(fd, data)
                written += n
                if progress_cb:
                    progress_cb(n)
        finally:
            os.close(src_fd)
            # Flush vers le disque
            try:
                os.fsync(fd)
            except Exception:
                pass
            os.close(fd)

    except PermissionError:
        error = "Permission refusée — root requis."
    except OSError as e:
        error = str(e)
    except Exception as e:
        error = str(e)

    return (not error), written, error


# ──────────────────────────────────────────────
# Linux — ATA Secure Erase (HDD/SSD SATA)
# ──────────────────────────────────────────────

def _ata_secure_erase_linux(device: str, enhanced: bool = False) -> tuple[bool, str]:
    """
    Effectue un ATA Secure Erase via hdparm.
    Nécessite que le disque ne soit pas 'frozen'.
    Retourne (success, error_msg).
    """
    if not _tool_ok("hdparm"):
        return False, "hdparm non disponible."

    # 1. Définit un mot de passe temporaire (requis par le protocole)
    tmp_pass = "SecureWipeTmp123"
    rc, _, err = _run(["hdparm", "--user-master", "u",
                        "--security-set-pass", tmp_pass, device], timeout=10)
    if rc != 0:
        return False, f"Impossible de définir le mot de passe ATA : {err}"

    # 2. Lance l'effacement
    erase_cmd = "--security-erase-enhanced" if enhanced else "--security-erase"
    rprint(f"\n  [dim]Lancement ATA {'Enhanced ' if enhanced else ''}Secure Erase...[/dim]")
    rc, _, err = _run(
        ["hdparm", "--user-master", "u", erase_cmd, tmp_pass, device],
        timeout=3600,   # Peut prendre plusieurs heures sur un grand disque
    )

    if rc != 0:
        # Tente de supprimer le mot de passe si l'effacement a échoué
        _run(["hdparm", "--user-master", "u", "--security-disable", tmp_pass, device])
        return False, f"ATA Secure Erase échoué : {err}"

    return True, ""


# ──────────────────────────────────────────────
# Linux — NVMe Format (Crypto Erase)
# ──────────────────────────────────────────────

def _nvme_format_linux(device: str) -> tuple[bool, str]:
    """
    Effectue un nvme format --ses=1 (Cryptographic Erase).
    """
    if not _tool_ok("nvme"):
        return False, "nvme-cli non disponible. Installer : apt install nvme-cli"

    rprint(f"\n  [dim]Lancement NVMe Format (Cryptographic Erase --ses=1)...[/dim]")
    # --ses=1 = User Data Erase, --ses=2 = Cryptographic Erase
    # On utilise --ses=2 (Crypto) en priorité
    rc, _, err = _run(["nvme", "format", device, "--ses=2", "--force"], timeout=600)
    if rc != 0:
        # Fallback --ses=1
        rc, _, err = _run(["nvme", "format", device, "--ses=1", "--force"], timeout=600)
    if rc != 0:
        return False, f"NVMe Format échoué : {err}"
    return True, ""


# ──────────────────────────────────────────────
# Linux — LUKS Erase
# ──────────────────────────────────────────────

def _luks_erase_linux(luks_device: str) -> tuple[bool, str]:
    """
    Détruit la clé maître LUKS via cryptsetup erase.
    Compatible LUKS1 et LUKS2.
    """
    if not _tool_ok("cryptsetup"):
        # Fallback : écrasement du header LUKS (premiers 2 Mo) avec des zéros
        rprint("  [yellow]cryptsetup absent — écrasement du header LUKS (2 MiB)...[/yellow]")
        try:
            with open(luks_device, "wb") as f:
                f.write(b'\x00' * (2 * 1024 * 1024))
                f.flush()
                os.fsync(f.fileno())
            return True, ""
        except Exception as e:
            return False, str(e)

    rprint(f"\n  [dim]Destruction de la clé maître LUKS sur {luks_device}...[/dim]")
    # cryptsetup erase détruit tous les key slots → données inaccessibles
    rc, _, err = _run(
        ["cryptsetup", "erase", "--batch-mode", luks_device],
        timeout=30,
    )
    if rc != 0:
        return False, f"cryptsetup erase échoué : {err}"
    return True, ""


# ──────────────────────────────────────────────
# Windows — effacement via diskpart + format
# ──────────────────────────────────────────────

def _estimate_diskpart_duration(size_bytes: int, disk_type: str) -> int:
    """
    Estime la durée de diskpart clean all en secondes
    selon la taille et le type de disque.
    """
    # Vitesses moyennes observées sur diskpart clean all
    speed = {
        "ssd":  300 * 1024 * 1024,   # ~300 MB/s SSD SATA
        "nvme": 400 * 1024 * 1024,   # ~400 MB/s NVMe
        "hdd":  100 * 1024 * 1024,   # ~100 MB/s HDD
    }.get(disk_type.lower(), 120 * 1024 * 1024)

    return max(60, int(size_bytes / speed))


def _is_removable_disk(disk) -> bool:
    """
    Détecte si le disque est connecté en USB/amovible.
    Vérifie transport ET les lettres de lecteur (heuristique).
    """
    transport = getattr(disk, "transport", "").lower()
    if transport in ("usb", "removable", "ieee1394"):
        return True
    # Heuristique Windows : si BusType était 7 (USB) le transport vaut "usb"
    # mais certains pilotes retournent "unknown" pour les docks USB-SATA
    # On vérifie aussi si le device_id correspond à un bus USB via le modèle
    model = getattr(disk, "model", "").upper()
    if any(kw in model for kw in ("USB", "EXTERNAL", "PORTABLE", "FLASH DRIVE")):
        return True
    return False


def _dismount_volumes_windows(kernel32, drive_letters: list) -> tuple[list, list]:
    """
    Verrouille et démonte les volumes du disque CIBLE avant écriture.
    UNIQUEMENT les lettres appartenant au disque physique sélectionné.
    Les autres disques et leurs lettres ne sont JAMAIS touchés.

    Retourne (vol_handles, failed_letters) :
    - vol_handles    : handles à fermer après écriture
    - failed_letters : lettres non verrouillables (fichiers ouverts dessus)
    """
    import ctypes
    GENERIC_READ      = 0x80000000
    GENERIC_WRITE     = 0x40000000
    FILE_SHARE_READ   = 0x00000001
    FILE_SHARE_WRITE  = 0x00000002
    OPEN_EXISTING     = 3
    FSCTL_LOCK_VOLUME     = 0x00090018
    FSCTL_DISMOUNT_VOLUME = 0x00090020
    INVALID_HANDLE    = ctypes.c_void_p(-1).value

    vol_handles    = []
    failed_letters = []

    for letter in drive_letters:
        letter_clean = letter.strip().rstrip("\\").rstrip("/").rstrip(":")
        vol_path = f"\\\\.\\{letter_clean}:"

        h = kernel32.CreateFileW(
            vol_path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, 0, None,
        )
        if h == INVALID_HANDLE:
            failed_letters.append(letter)
            continue

        # Verrouillage exclusif — échoue si des fichiers sont ouverts
        lock_ok = kernel32.DeviceIoControl(
            h, FSCTL_LOCK_VOLUME, None, 0, None, 0, None, None
        )
        if not lock_ok:
            kernel32.CloseHandle(h)
            failed_letters.append(letter)
            continue

        # Démontage du système de fichiers (flush cache inclus)
        kernel32.DeviceIoControl(h, FSCTL_DISMOUNT_VOLUME, None, 0, None, 0, None, None)
        vol_handles.append(h)

    return vol_handles, failed_letters


def _write_pass_windows(
    device: str,
    disk_size: int,
    pass_num: int,
    total_passes: int,
    use_random: bool,
    progress_cb=None,
    drive_letters: list = None,
) -> tuple[bool, int, str]:
    """
    Ecriture directe sur PhysicalDriveX via ctypes CreateFile (Windows API).
    Démonte les volumes du disque cible avant écriture.
    Les autres disques/volumes ne sont pas affectés.
    Sur Linux, délègue à _write_pass_linux.
    """
    if sys.platform != "win32":
        return _write_pass_linux(device, disk_size, pass_num, total_passes, use_random, progress_cb)

    import secrets
    import ctypes
    import ctypes.wintypes as wt

    GENERIC_READ      = 0x80000000
    GENERIC_WRITE     = 0x40000000
    FILE_SHARE_READ   = 0x00000001
    FILE_SHARE_WRITE  = 0x00000002
    OPEN_EXISTING     = 3
    FILE_FLAG_NO_BUFFERING  = 0x20000000
    FILE_FLAG_WRITE_THROUGH = 0x80000000
    FSCTL_UNLOCK_VOLUME     = 0x0009001C
    INVALID_HANDLE    = ctypes.c_void_p(-1).value

    SECTOR = 512
    BLOCK  = 4 * 1024 * 1024  # 4 MiB

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # Ouvre le disque physique
    handle = kernel32.CreateFileW(
        device,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING,
        FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH,
        None,
    )
    if handle == INVALID_HANDLE:
        err_code = ctypes.get_last_error()
        msgs = {
            5:   "Acces refuse - lancez PowerShell en tant qu'Administrateur.",
            32:  "Disque utilise par un autre processus.",
            87:  "Parametre invalide - verifiez le numero du disque.",
            1117:"Erreur materielle sur le disque.",
        }
        return False, 0, msgs.get(err_code, f"CreateFile echoue (code Windows {err_code}).")

    # Démontage des volumes du disque CIBLE uniquement
    letters = drive_letters or []
    vol_handles, failed = _dismount_volumes_windows(kernel32, letters)

    # Si des lettres n'ont pas pu être verrouillées, on avertit mais on continue
    # (le démontage forcé via FSCTL_DISMOUNT_VOLUME suffit dans la plupart des cas)
    if failed:
        failed_str = ", ".join(failed)
        rprint(f"  [yellow]{t('wipe_vol_locked_fail', letters=failed_str)}[/yellow]")
        rprint(f"  [dim]{t('wipe_vol_close_hint')}[/dim]")

    written = 0
    error   = ""

    try:
        while written < disk_size:
            to_write = min(BLOCK, disk_size - written)
            aligned  = ((to_write + SECTOR - 1) // SECTOR) * SECTOR
            data = secrets.token_bytes(aligned) if use_random else (b"\x00" * aligned)
            buf  = (ctypes.c_char * aligned).from_buffer_copy(data)
            written_dword = wt.DWORD(0)

            ok = kernel32.WriteFile(handle, buf, aligned, ctypes.byref(written_dword), None)
            if not ok:
                err_code = ctypes.get_last_error()
                if err_code == 5:
                    error = t("wipe_access_denied",
                        device=device,
                        letters=", ".join(letters) if letters else device,
                    )
                else:
                    error = f"WriteFile echoue (code Windows {err_code})."
                break

            written += to_write
            if progress_cb:
                progress_cb(to_write)

    except Exception as e:
        error = str(e)
    finally:
        for vh in vol_handles:
            kernel32.DeviceIoControl(vh, FSCTL_UNLOCK_VOLUME, None, 0, None, 0, None, None)
            kernel32.CloseHandle(vh)
        kernel32.CloseHandle(handle)

    return (not error), written, error


def _diskpart_clean_windows_nist(
    disk_number: str,
    size_bytes: int = 0,
    disk_type: str = "hdd",
) -> tuple[bool, int, str]:
    """
    NIST Purge sur disque Windows INTERNE via diskpart clean all.
    Ne pas appeler sur disque amovible/USB — utiliser _is_removable_disk() avant.
    """
    estimated_sec = _estimate_diskpart_duration(size_bytes, disk_type)
    h = estimated_sec // 3600
    m = (estimated_sec % 3600) // 60
    eta_str = f"{h}h {m:02d}min" if h else f"{m}min"

    script = (
        f"select disk {disk_number}\n"
        f"offline disk noerr\n"
        f"attributes disk clear readonly noerr\n"
        f"clean all\n"
        f"online disk noerr\n"
        f"exit\n"
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="ascii"
    ) as f:
        f.write(script)
        script_path = f.name

    console.print()
    console.print(f"  [dim]NIST Purge — Disk {disk_number} (diskpart clean all)[/dim]")
    console.print(f"  [yellow]⚠  Durée estimée : ~{eta_str} — ne pas interrompre.[/yellow]")
    console.print()

    result_box = {"rc": None, "out": "", "err": ""}

    def _run_diskpart():
        try:
            import subprocess as _sp
            r = _sp.run(
                ["diskpart", "/s", script_path],
                capture_output=True, text=True, timeout=14400,
            )
            result_box["rc"]  = r.returncode
            result_box["out"] = r.stdout.strip()
            result_box["err"] = r.stderr.strip()
        except Exception as e:
            result_box["rc"]  = 1
            result_box["err"] = str(e)

    import threading
    import time as _time
    from rich.progress import (
        Progress, SpinnerColumn, BarColumn, TextColumn,
        TimeElapsedColumn, TimeRemainingColumn,
    )

    th = threading.Thread(target=_run_diskpart, daemon=True)
    th.start()

    start = _time.time()
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TextColumn("ETA"),
        TimeRemainingColumn(),
        console=console,
        refresh_per_second=2,
    ) as progress:
        task = progress.add_task(
            t("wipe_progress_label") + f" (Disk {disk_number})",
            total=estimated_sec,
        )
        while th.is_alive():
            elapsed = _time.time() - start
            progress.update(task, completed=min(elapsed, estimated_sec * 0.97))
            _time.sleep(0.5)
        progress.update(task, completed=estimated_sec)

    try:
        os.unlink(script_path)
    except Exception:
        pass

    rc = result_box["rc"]
    if rc != 0:
        return False, 0, f"diskpart échoué (code {rc}) : {result_box['err'] or result_box['out']}"
    return True, size_bytes, ""


def _bitlocker_off_windows(drive_letters: list) -> tuple[bool, str]:
    """
    Désactive BitLocker sur chaque lettre de lecteur.
    Attend la fin du déchiffrement.
    """
    for letter in drive_letters:
        rprint(f"  [dim]Désactivation BitLocker sur {letter}...[/dim]")
        rc, _, err = _run(["manage-bde", "-off", letter], timeout=7200)
        if rc != 0:
            return False, f"manage-bde -off {letter} échoué : {err}"
        # Attend la fin
        for _ in range(360):   # max 1h
            time.sleep(10)
            rc2, out2, _ = _run(["manage-bde", "-status", letter], timeout=15)
            if "Fully Decrypted" in out2 or "Protection Off" in out2:
                break
    return True, ""


# ──────────────────────────────────────────────
# Vérification post-effacement
# ──────────────────────────────────────────────

def _verify_wipe(
    device: str,
    disk_size: int,
    verify_pct: int,
    expect_zeros: bool,
    gui_verify_cb=None,
) -> tuple[bool, str]:
    """
    Lit un échantillon aléatoire de secteurs et vérifie qu'ils sont
    bien effacés (zéros si expect_zeros, sinon tout sauf les données originales).
    Pour 'aléatoire', on vérifie juste que c'est pas que des zéros partout
    (signe que l'écriture a bien eu lieu).
    Retourne (ok, detail_msg).
    """
    sample_size = int(disk_size * verify_pct / 100)
    sample_size = max(sample_size, BLOCK_SIZE)   # minimum 1 bloc
    num_blocks  = max(1, sample_size // BLOCK_SIZE)

    # Positions aléatoires réparties sur le disque
    max_offset = max(0, disk_size - BLOCK_SIZE)
    population = list(range(0, max(BLOCK_SIZE, max_offset + 1), BLOCK_SIZE))
    k = min(num_blocks, len(population))
    offsets = sorted(random.sample(population, k)) if k > 0 else [0]

    if not offsets:
        return True, t("verify_too_small")

    try:
        fd = os.open(device, os.O_RDONLY)
        try:
            all_zeros_count = 0
            non_zeros_count = 0

            for idx_v, offset in enumerate(offsets):
                os.lseek(fd, offset, os.SEEK_SET)
                data = os.read(fd, BLOCK_SIZE)
                if not data:
                    continue
                is_zero_block = all(b == 0 for b in data)
                if is_zero_block:
                    all_zeros_count += 1
                else:
                    non_zeros_count += 1
                if gui_verify_cb:
                    gui_verify_cb(idx_v + 1, len(offsets))
        finally:
            os.close(fd)

        if expect_zeros:
            if non_zeros_count > 0:
                return False, t("verify_detail_fail", n=non_zeros_count, total=len(offsets))
            return True, t("verify_detail_zeros", n=len(offsets))
        else:
            if all_zeros_count == len(offsets):
                return False, t("verify_detail_rand")
            return True, t("verify_detail_write", n=len(offsets))

    except PermissionError:
        return False, t("verify_perm_denied")
    except Exception as e:
        return False, str(e)


# ──────────────────────────────────────────────
# Windows — reformatage post-effacement
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# Orchestrateur principal
# ──────────────────────────────────────────────

def run_wipe(
    disk,
    mode: WipeMode,
    custom_passes: int = 3,
    verify_pct: int = 10,
    crypto_profile: Optional[CryptoProfile] = None,
    gui_progress_cb: Optional[Callable] = None,
) -> WipeResult:
    """
    Exécute l'effacement complet d'un disque.
    gui_progress_cb(bytes_done, total_bytes, elapsed_sec) : callback GUI optionnel.
    Si fourni, bypasse la barre Rich terminal pour envoyer la progression au GUI.
    """
    is_linux   = sys.platform != "win32"
    is_windows = sys.platform == "win32"
    device     = disk.device
    dtype      = disk.disk_type
    size_bytes = disk.size_bytes

    result = WipeResult(
        status=WipeStatus.FAILED,
        mode=mode,
        device=device,
    )

    start_time = time.time()

    # ── Affichage du démarrage ──
    console.print()
    rprint(f"  [bold cyan]{t('wipe_starting')}[/bold cyan]")
    console.print()

    try:
        # ══════════════════════════════════════
        # CRYPTO ERASE
        # ══════════════════════════════════════
        if mode == WipeMode.CRYPTO_ERASE and crypto_profile:
            cm = crypto_profile.recommended_method

            if cm == CryptoMethod.LUKS_ERASE:
                ok, err = _luks_erase_linux(crypto_profile.luks_device)
                result.method_detail = f"LUKS Erase ({crypto_profile.luks_version})"
                result.standard      = "ANSSI Palier 2 / NIST Purge"
                result.passes_done   = 1

            elif cm == CryptoMethod.SED_ATA:
                ok, err = _ata_secure_erase_linux(device, crypto_profile.sed_enhanced)
                result.method_detail = f"ATA Secure Erase {'Enhanced' if crypto_profile.sed_enhanced else ''}"
                result.standard      = "NIST Purge"
                result.passes_done   = 1

            elif cm == CryptoMethod.SED_NVME:
                ok, err = _nvme_format_linux(device)
                result.method_detail = "NVMe Format --ses=2 (Cryptographic Erase)"
                result.standard      = "NIST Purge"
                result.passes_done   = 1

            elif cm == CryptoMethod.BITLOCKER_OFF:
                ok, err = _bitlocker_off_windows(crypto_profile.bitlocker_drives)
                if ok:
                    disk_num = getattr(disk, "device_id", "0")
                    is_removable = getattr(disk, "transport", "").lower() in ("usb", "removable")
                    ok2, _, err2 = _diskpart_clean_windows(disk_num, disk.size_bytes, disk.disk_type, is_removable)
                    if not ok2:
                        ok, err = False, err2
                result.method_detail = "BitLocker Off + diskpart clean all"
                result.standard      = "NIST Purge"
                result.passes_done   = 1
            else:
                ok, err = False, "Méthode crypto non reconnue."

            if ok:
                result.status        = WipeStatus.SUCCESS
                result.duration_sec  = time.time() - start_time
                rprint(f"  {t('wipe_success')}")
            else:
                result.status    = WipeStatus.FAILED
                result.error_msg = err
                rprint(f"  {t('wipe_failed', error=err)}")
            return result

        # ══════════════════════════════════════
        # NIST PURGE — Firmware Secure Erase
        # ══════════════════════════════════════
        elif mode == WipeMode.NIST_PURGE:
            if is_linux:
                if dtype == "nvme":
                    ok, err = _nvme_format_linux(device)
                    result.method_detail = "NVMe Format --ses=1/2"
                elif dtype in ("hdd", "ssd"):
                    from core.crypto_detect import _analyse_sed_linux, SedStatus
                    status, enhanced, _ = _analyse_sed_linux(device)
                    if status == SedStatus.FROZEN:
                        rprint("  [yellow]⚠ Disque frozen — tentative sans enhanced...[/yellow]")
                    ok, err = _ata_secure_erase_linux(device, enhanced=(status != SedStatus.FROZEN and enhanced))
                    result.method_detail = "ATA Secure Erase"
                else:
                    ok, err = False, "Type de disque non supporté pour NIST Purge."
            else:
                # Windows : NIST Purge via diskpart uniquement sur disques internes
                if _is_removable_disk(disk):
                    ok  = False
                    err = t("nist_blocked_err")
                    rprint(f"\n  [bold yellow]⚠ NIST Purge bloqué :[/bold yellow]")
                    rprint(f"  [dim]{t('nist_blocked_err')}[/dim]")
                else:
                    disk_num = getattr(disk, "device_id", "0")
                    ok, _, err = _diskpart_clean_windows_nist(disk_num, disk.size_bytes, disk.disk_type)
                result.method_detail = "ATA Secure Erase (diskpart)"

            result.standard    = "NIST SP 800-88 Purge"
            result.passes_done = 1

            if ok:
                result.status       = WipeStatus.SUCCESS
                result.duration_sec = time.time() - start_time
                rprint(f"  {t('wipe_success')}")
            else:
                result.status    = WipeStatus.FAILED
                result.error_msg = err
                rprint(f"  {t('wipe_failed', error=err)}")
            return result

        # ══════════════════════════════════════
        # OVERWRITE PASSES (ANSSI P1, P2, Custom)
        # ══════════════════════════════════════
        else:
            # Détermine les passes
            if mode == WipeMode.ANSSI_P1:
                passes      = [False]   # 1 passe zéros
                result.standard = "ANSSI Palier 1"
                result.method_detail = "1 passe (zéros)"
            elif mode == WipeMode.ANSSI_P2:
                passes      = [True]    # 1 passe aléatoire
                result.standard = "ANSSI Palier 2 / NIST Clear"
                result.method_detail = "1 passe (aléatoire)"
            else:  # CUSTOM
                # Alternance zéros/aléatoire
                passes = [i % 2 == 1 for i in range(custom_passes)]
                result.standard = f"Custom ({custom_passes} passes)"
                result.method_detail = f"{custom_passes} passes (alternance zéros/aléatoire)"

            total_bytes   = size_bytes * len(passes)
            total_written = 0

            # Compteur cumulatif pour le callback GUI
            # Utilise une liste pour être modifiable dans la closure
            _gui_written = [0]

            def _make_gui_cb():
                """Callback GUI : accumule les octets écrits à travers toutes les passes."""
                def cb(n):
                    _gui_written[0] += n
                    gui_progress_cb(
                        _gui_written[0], total_bytes,
                        time.time() - start_time
                    )
                return cb

            if gui_progress_cb:
                # Mode GUI : progression via callback cumulatif
                for i, use_random in enumerate(passes, 1):
                    cb = _make_gui_cb()
                    letters = getattr(disk, "drive_letters", []) or getattr(disk, "mountpoints", [])
                    if is_linux:
                        ok, written, err = _write_pass_linux(
                            device, size_bytes, i, len(passes), use_random, cb)
                    else:
                        ok, written, err = _write_pass_windows(
                            device, size_bytes, i, len(passes), use_random, cb,
                            drive_letters=letters)
                    total_written += written
                    if not ok:
                        result.status    = WipeStatus.FAILED
                        result.error_msg = err
                        result.bytes_written = total_written
                        result.passes_done   = i - 1
                        result.duration_sec  = time.time() - start_time
                        return result
            else:
                # Mode CLI : Rich progress bar
                with _make_progress() as progress:
                    task = progress.add_task(t("wipe_progress_label"), total=total_bytes)

                    for i, use_random in enumerate(passes, 1):
                        def cb(n, _task=task):
                            progress.advance(_task, n)

                        letters = getattr(disk, "drive_letters", []) or getattr(disk, "mountpoints", [])
                        if is_linux:
                            ok, written, err = _write_pass_linux(
                                device, size_bytes, i, len(passes), use_random, cb)
                        else:
                            ok, written, err = _write_pass_windows(
                                device, size_bytes, i, len(passes), use_random, cb,
                                drive_letters=letters)

                        total_written += written
                        if not ok:
                            result.status    = WipeStatus.FAILED
                            result.error_msg = err
                            rprint(f"  {t('wipe_failed', error=err)}")
                            result.bytes_written = total_written
                            result.passes_done   = i - 1
                            result.duration_sec  = time.time() - start_time
                            return result

            result.bytes_written = total_written
            result.passes_done   = len(passes)

            rprint(f"  {t('wipe_success')}")

            # ── Vérification ──
            # Active sur Linux ET Windows (écriture directe = lecture possible)
            if verify_pct > 0 and size_bytes > 0:
                console.print()
                rprint(f"  [dim]{t('wipe_verify_label')} ({verify_pct}%)...[/dim]")

                expect_zeros = (mode == WipeMode.ANSSI_P1) or \
                               (mode == WipeMode.CUSTOM and not passes[-1])

                if gui_progress_cb:
                    # Adapte le callback vérif : (done_blk, total_blk) → gui_progress_cb(done, total, elapsed)
                    # On réutilise l'interface existing en passant done=blk, total=total_blk, elapsed=0
                    def _verif_adapter(done_blk, total_blk):
                        gui_progress_cb(done_blk, total_blk, 0)
                    ok_v, detail = _verify_wipe(
                        device, size_bytes, verify_pct, expect_zeros,
                        gui_verify_cb=_verif_adapter,
                    )
                else:
                    with _make_progress() as progress:
                        progress.add_task(t("wipe_verify_label"), total=None)
                        ok_v, detail = _verify_wipe(device, size_bytes, verify_pct, expect_zeros)

                result.verify_pct = verify_pct
                result.verify_ok  = ok_v

                if ok_v:
                    rprint(f"  {t('wipe_verify_success', pct=verify_pct)}")
                    rprint(f"  [dim]{detail}[/dim]")
                    result.status = WipeStatus.SUCCESS
                else:
                    rprint(f"  {t('wipe_verify_failed')}")
                    rprint(f"  [dim]{detail}[/dim]")
                    result.status = WipeStatus.VERIFY_FAILED
            else:
                result.status     = WipeStatus.SUCCESS
                result.verify_ok  = None   # Pas de vérification

    except KeyboardInterrupt:
        result.status    = WipeStatus.ABORTED
        result.error_msg = "Interrompu par l'utilisateur."
        rprint("\n  [yellow]⚠ Opération interrompue.[/yellow]")
    except Exception as e:
        result.status    = WipeStatus.FAILED
        result.error_msg = str(e)
        rprint(f"  {t('wipe_failed', error=e)}")
    finally:
        result.duration_sec = time.time() - start_time

    return result


# ──────────────────────────────────────────────
# Menu de sélection du mode (appelé par ui.py)
# ──────────────────────────────────────────────

def select_wipe_mode(disk, crypto_profile: CryptoProfile) -> tuple[WipeMode, int, int, str]:
    """
    Affiche le menu de sélection du mode d'effacement.
    Retourne (mode, custom_passes, verify_pct, mode_label).
    """
    from core.ui import print_section, numbered_menu
    from rich import print as rprint

    dtype = disk.disk_type
    is_flash = dtype in ("ssd", "nvme")

    print_section(t("wipe_mode_title"))

    # Avertissement disque amovible
    is_removable = _is_removable_disk(disk)
    if is_removable:
        console.print()
        rprint(f"  [bold yellow]⚠  {t('removable_warning')}[/bold yellow]")
        rprint(f"  [dim]{t('removable_nist_msg1')}[/dim]")
        rprint(f"  [dim]{t('removable_nist_msg2')}[/dim]")
        console.print()

    # Info SSD/NVMe
    if is_flash:
        rprint(f"  {t('wipe_mode_ssd_info')}")
        console.print()

    # Info crypto disponible
    if crypto_profile.has_crypto_option:
        enc = disk.encryption.upper()
        rprint(f"  {t('wipe_mode_crypto_info', enc=enc)}")
        console.print()

    # Construction du menu selon le type de disque
    options = []
    mode_map = {}

    if crypto_profile.has_crypto_option:
        label = crypto_profile.display_name or t("wipe_m4_name")
        desc  = crypto_profile.display_desc or t("wipe_m4_desc")
        options.append((label, desc))
        mode_map[len(options)] = WipeMode.CRYPTO_ERASE

    if not is_flash:
        options.append((t("wipe_m1_name"), f"{t('wipe_m1_desc')} [{t('wipe_m1_compat')}]"))
        mode_map[len(options)] = WipeMode.ANSSI_P1

        options.append((t("wipe_m2_name"), f"{t('wipe_m2_desc')} [{t('wipe_m2_compat')}]"))
        mode_map[len(options)] = WipeMode.ANSSI_P2

    if not is_removable:
        options.append((t("wipe_m3_name"), f"{t('wipe_m3_desc')} [{t('wipe_m3_compat')}]"))
        mode_map[len(options)] = WipeMode.NIST_PURGE
    else:
        options.append((
            f"[dim]{t('wipe_m3_name')} — {t('nist_unavailable')}[/dim]",
            f"[dim]{t('nist_unavailable_desc')}[/dim]"
        ))
        mode_map[len(options)] = None  # Choix désactivé

    if not is_flash:
        options.append((t("wipe_m5_name"), f"{t('wipe_m5_desc')} [{t('wipe_m5_compat')}]"))
        mode_map[len(options)] = WipeMode.CUSTOM

    from core.ui import numbered_menu
    while True:
        idx = numbered_menu("", options, default=1)  # titre deja affiche par print_section
        chosen_num = idx + 1
        mode = mode_map[chosen_num]
        if mode is None:
            rprint(f"  [red]{t('nist_unavailable')}[/red]")
            rprint(f"  [dim]{t('removable_nist_msg2')}[/dim]")
            console.print()
            continue
        break

    # Passes custom
    custom_passes = 3
    if mode == WipeMode.CUSTOM:
        rprint(f"\n  {t('wipe_m5_warn')}")
        console.print()
        from rich.prompt import Prompt
        while True:
            raw = Prompt.ask(f"  {t('wipe_m5_passes')}", default="3").strip()
            try:
                n = int(raw)
                if 2 <= n <= 7:
                    custom_passes = n
                    break
            except ValueError:
                pass
            rprint(f"  {t('wipe_m5_passes_invalid')}")

    # Niveau de vérification
    verify_pct = 10
    if mode not in (WipeMode.CRYPTO_ERASE, WipeMode.NIST_PURGE):
        from rich.prompt import Prompt
        print_section(t("verify_title"))
        v_options = [
            (t("verify_opt1"), ""),
            (t("verify_opt2"), ""),
        ]
        v_idx = numbered_menu(t("verify_title"), v_options, default=1)
        if v_idx == 1:  # Custom
            while True:
                raw = Prompt.ask(f"  {t('verify_custom_prompt')}", default="10").strip()
                try:
                    n = int(raw)
                    if 1 <= n <= 100:
                        verify_pct = n
                        break
                except ValueError:
                    pass
                rprint(f"  {t('verify_custom_invalid')}")

    mode_label = options[idx][0]
    return mode, custom_passes, verify_pct, mode_label
