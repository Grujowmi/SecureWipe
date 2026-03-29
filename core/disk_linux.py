"""
SecureWipe — disk_linux.py
Détection et analyse des disques sous Linux.

Dépendances système (installées par install.sh) :
  - lsblk    (util-linux, présent sur toutes les distros modernes)
  - hdparm   (pour ATA Secure Erase et infos HDD)
  - nvme-cli (pour NVMe Format)
  - smartctl (optionnel, smartmontools — enrichit les infos S/N)
  - lsblk    (pour LUKS : fstype = crypto_LUKS)
  - dmsetup  (pour détecter si un mapping LUKS est actif)
"""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.i18n import t

# ──────────────────────────────────────────────
# Structures de données
# ──────────────────────────────────────────────

DISK_TYPE_HDD   = "hdd"
DISK_TYPE_SSD   = "ssd"
DISK_TYPE_NVME  = "nvme"
DISK_TYPE_UNK   = "unknown"

ENC_NONE        = "none"
ENC_LUKS        = "luks"
ENC_BITLOCKER   = "bitlocker"   # rare sous Linux mais possible (disque dual-boot)
ENC_SED         = "sed"         # Self-Encrypting Drive détecté via hdparm


@dataclass
class DiskInfo:
    """Représente un disque physique détecté."""
    device: str          # ex: /dev/sda, /dev/nvme0n1
    name: str            # ex: sda, nvme0n1
    model: str           # ex: Samsung SSD 870 EVO
    serial: str          # numéro de série
    disk_type: str       # hdd / ssd / nvme / unknown
    size_bytes: int      # taille en octets
    size_human: str      # ex: 500 GiB
    is_system: bool      # True si contient /, /boot, [SWAP], etc.
    encryption: str      # none / luks / bitlocker / sed
    transport: str       # sata / nvme / usb / ...
    # Détails supplémentaires
    vendor: str = ""
    firmware: str = ""
    smart_available: bool = False
    mountpoints: list = field(default_factory=list)
    raw_lsblk: dict = field(default_factory=dict)


# ──────────────────────────────────────────────
# Utilitaires subprocess
# ──────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """Lance une commande, retourne (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LANG": "C", "LC_ALL": "C"},  # Force output en anglais
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"Timeout: {cmd}"
    except Exception as e:
        return 1, "", str(e)


def _tool_available(name: str) -> bool:
    """Vérifie si un outil est disponible dans le PATH."""
    rc, _, _ = _run(["which", name])
    return rc == 0


# ──────────────────────────────────────────────
# Parsing lsblk
# ──────────────────────────────────────────────

def _lsblk_json() -> list[dict]:
    """
    Lance lsblk en JSON et retourne la liste des blockdevices.
    Gère les deux formats (ancien lsblk sans --json).
    """
    rc, out, err = _run([
        "lsblk", "-J", "-b",   # -b = taille en octets
        "-o", "NAME,TYPE,SIZE,MODEL,SERIAL,ROTA,TRAN,MOUNTPOINTS,FSTYPE,VENDOR,FIRMWARE",
    ])

    if rc != 0 or not out:
        # Fallback : pas de JSON, on parse la sortie texte
        return _lsblk_fallback()

    try:
        data = json.loads(out)
        return data.get("blockdevices", [])
    except json.JSONDecodeError:
        return _lsblk_fallback()


def _lsblk_fallback() -> list[dict]:
    """
    Fallback si lsblk -J ne fonctionne pas.
    Parse /proc/partitions et /sys/block pour reconstruire la liste.
    """
    devices = []
    sys_block = Path("/sys/block")

    if not sys_block.exists():
        return []

    for dev_path in sorted(sys_block.iterdir()):
        name = dev_path.name
        # On ne garde que les disques (pas les partitions, loop, ram...)
        if not re.match(r'^(sd[a-z]+|hd[a-z]+|nvme\d+n\d+|vd[a-z]+|xvd[a-z]+)$', name):
            continue

        dev = {
            "name": name,
            "type": "disk",
            "size": _sysfs_read(dev_path / "size", "0"),
            "model": _sysfs_read(dev_path / "device" / "model", "Unknown").strip(),
            "serial": _sysfs_read(dev_path / "device" / "serial", "N/A").strip(),
            "vendor": _sysfs_read(dev_path / "device" / "vendor", "").strip(),
            "rota": _sysfs_read(dev_path / "queue" / "rotational", "1") == "1",
            "tran": _guess_transport(name),
            "mountpoints": [],
            "children": [],
        }
        # Taille : /sys/block/sdX/size est en secteurs de 512 octets
        try:
            sectors = int(dev["size"])
            dev["size"] = sectors * 512
        except ValueError:
            dev["size"] = 0

        devices.append(dev)

    return devices


def _sysfs_read(path: Path, default: str = "") -> str:
    try:
        return path.read_text().strip()
    except Exception:
        return default


def _guess_transport(name: str) -> str:
    if name.startswith("nvme"):
        return "nvme"
    if name.startswith(("sd", "hd")):
        return "sata"
    if name.startswith(("vd", "xvd")):
        return "virtio"
    return "unknown"


# ──────────────────────────────────────────────
# Conversion taille
# ──────────────────────────────────────────────

def _bytes_to_human(n: int) -> str:
    """Convertit des octets en chaîne lisible (GiB / TiB)."""
    if n <= 0:
        return "? GiB"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PiB"


def _parse_size(raw) -> int:
    """
    Convertit la taille retournée par lsblk en entier (octets).
    Avec -b c'est déjà un entier. Sans -b c'est '500G', '2T', etc.
    """
    if isinstance(raw, int):
        return raw
    if raw is None:
        return 0
    s = str(raw).strip().upper()
    try:
        return int(s)
    except ValueError:
        pass
    units = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4, "P": 1024**5}
    for suffix, mult in units.items():
        if s.endswith(suffix):
            try:
                return int(float(s[:-1]) * mult)
            except ValueError:
                return 0
    return 0


# ──────────────────────────────────────────────
# Détection type disque
# ──────────────────────────────────────────────

def _detect_disk_type(dev: dict) -> str:
    """Détermine HDD / SSD / NVMe à partir des infos lsblk."""
    tran = (dev.get("tran") or "").lower()
    rota = dev.get("rota")
    name = dev.get("name", "")

    if tran == "nvme" or name.startswith("nvme"):
        return DISK_TYPE_NVME

    # rota = True  → disque à plateaux (HDD)
    # rota = False → flash (SSD)
    if isinstance(rota, bool):
        return DISK_TYPE_HDD if rota else DISK_TYPE_SSD

    # Certains lsblk retournent "1"/"0" en string
    if str(rota) == "1":
        return DISK_TYPE_HDD
    if str(rota) == "0":
        return DISK_TYPE_SSD

    return DISK_TYPE_UNK


# ──────────────────────────────────────────────
# Détection disque système
# ──────────────────────────────────────────────

SYSTEM_MOUNTPOINTS = {"/", "/boot", "/boot/efi", "/usr", "[SWAP]", "swap"}


def _is_system_disk(dev: dict) -> bool:
    """
    Retourne True si le disque (ou une de ses partitions)
    est monté sur un point critique du système.
    """
    def _check_mounts(node: dict) -> bool:
        mounts = node.get("mountpoints") or node.get("mountpoint") or []
        if isinstance(mounts, str):
            mounts = [mounts]
        for m in mounts:
            if m and m in SYSTEM_MOUNTPOINTS:
                return True
        for child in node.get("children") or []:
            if _check_mounts(child):
                return True
        return False

    return _check_mounts(dev)


# ──────────────────────────────────────────────
# Détection chiffrement
# ──────────────────────────────────────────────

def _detect_encryption(dev: dict, device_path: str) -> str:
    """
    Détecte le type de chiffrement présent sur le disque.
    Priorité : LUKS > SED (hdparm) > BitLocker > aucun
    """
    # 1. LUKS — via fstype sur les partitions enfants ou le disque entier
    if _has_luks_child(dev):
        return ENC_LUKS

    # 2. SED — via hdparm -I (cherche "Security:" et "enabled")
    if _is_sed(device_path):
        return ENC_SED

    # 3. BitLocker — fstype = BitLocker (rare sous Linux, dual-boot)
    if _has_bitlocker_child(dev):
        return ENC_BITLOCKER

    return ENC_NONE


def _has_luks_child(dev: dict) -> bool:
    """Vérifie si le disque ou ses partitions ont fstype=crypto_LUKS."""
    fstype = (dev.get("fstype") or "").lower()
    if "luks" in fstype:
        return True
    for child in dev.get("children") or []:
        if _has_luks_child(child):
            return True
    return False


def _has_bitlocker_child(dev: dict) -> bool:
    """Vérifie si une partition a fstype contenant 'bitlocker'."""
    fstype = (dev.get("fstype") or "").lower()
    if "bitlocker" in fstype:
        return True
    for child in dev.get("children") or []:
        if _has_bitlocker_child(child):
            return True
    return False


def _is_sed(device_path: str) -> bool:
    """
    Vérifie si le disque est un Self-Encrypting Drive via hdparm -I.
    Cherche la ligne 'Security:' avec 'enabled' dans la sortie.
    """
    if not _tool_available("hdparm"):
        return False
    rc, out, _ = _run(["hdparm", "-I", device_path], timeout=5)
    if rc != 0:
        return False
    # hdparm signale un SED dans la section "Security:"
    in_security = False
    for line in out.splitlines():
        if "Security:" in line:
            in_security = True
        if in_security and "enabled" in line.lower():
            return True
        if in_security and line.strip() == "":
            break
    return False


# ──────────────────────────────────────────────
# Enrichissement via smartctl
# ──────────────────────────────────────────────

def _enrich_with_smartctl(disk: DiskInfo) -> None:
    """
    Complète les infos manquantes (S/N, firmware, vendor) via smartctl.
    Modifie disk en place. Ne bloque pas si smartctl est absent.
    """
    if not _tool_available("smartctl"):
        return

    rc, out, _ = _run(["smartctl", "-i", "--json", disk.device], timeout=8)
    if rc not in (0, 64):   # 64 = some SMART errors but output valid
        return

    try:
        data = json.loads(out)
        info = data.get("device", {})
        model_info = data.get("model_name", "")
        serial_info = data.get("serial_number", "")
        firmware_info = data.get("firmware_version", "")
        vendor_info = data.get("model_family", "") or info.get("type", "")

        if model_info and disk.model in ("Unknown", "", "N/A"):
            disk.model = model_info
        if serial_info and disk.serial in ("Unknown", "", "N/A"):
            disk.serial = serial_info
        if firmware_info:
            disk.firmware = firmware_info
        if vendor_info and not disk.vendor:
            disk.vendor = vendor_info

        disk.smart_available = True

    except (json.JSONDecodeError, KeyError):
        pass


# ──────────────────────────────────────────────
# Collecte des mountpoints actifs
# ──────────────────────────────────────────────

def _collect_mountpoints(dev: dict) -> list[str]:
    """Collecte tous les points de montage d'un disque et ses partitions."""
    mps = []

    def _recurse(node: dict):
        mounts = node.get("mountpoints") or node.get("mountpoint") or []
        if isinstance(mounts, str):
            mounts = [mounts]
        for m in mounts:
            if m:
                mps.append(m)
        for child in node.get("children") or []:
            _recurse(child)

    _recurse(dev)
    return mps


# ──────────────────────────────────────────────
# Fonction principale : list_disks()
# ──────────────────────────────────────────────

def list_disks() -> list[DiskInfo]:
    """
    Détecte tous les disques physiques disponibles sous Linux.
    Retourne une liste de DiskInfo, triée par device.

    Variable d'environnement SECUREWIPE_DEV=/chemin/vers/fichier :
    Injecte un fichier comme faux disque pour les tests (ex: fichier dd).
    """
    import os as _os

    # Mode test : SECUREWIPE_DEV=/tmp/testdisk.img
    test_dev = _os.environ.get("SECUREWIPE_DEV", "").strip()
    if test_dev and _os.path.exists(test_dev):
        size = _os.path.getsize(test_dev)
        fake = DiskInfo(
            device    = test_dev,
            name      = _os.path.basename(test_dev),
            model     = f"[TEST] Fichier image",
            serial    = "TEST-0001",
            disk_type = DISK_TYPE_HDD,
            size_bytes= size,
            size_human= _bytes_to_human(size),
            is_system = False,
            encryption= ENC_NONE,
            transport = "test",
            vendor    = "SecureWipe",
            firmware  = "",
            mountpoints=[],
        )
        return [fake]

    raw_devices = _lsblk_json()
    disks = []

    for dev in raw_devices:
        # On ne traite que les disques physiques (type=disk)
        if dev.get("type") != "disk":
            continue

        name = dev.get("name", "")
        if not name:
            continue

        device_path = f"/dev/{name}"
        size_bytes = _parse_size(dev.get("size", 0))

        # Modèle et S/N — nettoyage des valeurs vides/None
        model  = (dev.get("model") or "").strip() or "Unknown"
        serial = (dev.get("serial") or "").strip() or "N/A"
        vendor = (dev.get("vendor") or "").strip()

        disk = DiskInfo(
            device       = device_path,
            name         = name,
            model        = model,
            serial       = serial,
            vendor       = vendor,
            disk_type    = _detect_disk_type(dev),
            size_bytes   = size_bytes,
            size_human   = _bytes_to_human(size_bytes),
            is_system    = _is_system_disk(dev),
            encryption   = _detect_encryption(dev, device_path),
            transport    = (dev.get("tran") or "").lower() or _guess_transport(name),
            firmware     = (dev.get("firmware") or "").strip(),
            mountpoints  = _collect_mountpoints(dev),
            raw_lsblk    = dev,
        )

        # Enrichissement optionnel via smartctl
        _enrich_with_smartctl(disk)

        disks.append(disk)

    disks.sort(key=lambda d: d.device)
    return disks


# ──────────────────────────────────────────────
# Vérification des outils requis
# ──────────────────────────────────────────────

def check_linux_tools() -> dict[str, bool]:
    """
    Vérifie la disponibilité des outils nécessaires.
    Retourne un dict {outil: disponible}.
    """
    tools = {
        "lsblk"   : True,   # Toujours présent
        "hdparm"  : _tool_available("hdparm"),
        "nvme"    : _tool_available("nvme"),
        "smartctl": _tool_available("smartctl"),
        "dd"      : _tool_available("dd"),
        "shred"   : _tool_available("shred"),
    }
    return tools


# ──────────────────────────────────────────────
# Mock pour tests sans vrai matériel
# ──────────────────────────────────────────────

def _mock_disks() -> list[DiskInfo]:
    """
    Génère des disques fictifs pour les tests en environnement sandboxé.
    N'est jamais appelé en production.
    """
    return [
        DiskInfo(
            device="[MOCK] /dev/sda", name="sda",
            model="Samsung SSD 870 EVO 500GB", serial="S5YXNX0T654321",
            vendor="Samsung", disk_type=DISK_TYPE_SSD,
            size_bytes=500_107_862_016, size_human="465.8 GiB",
            is_system=False, encryption=ENC_LUKS,
            transport="sata", firmware="SVT01B6Q",
            smart_available=True, mountpoints=[],
        ),
        DiskInfo(
            device="[MOCK] /dev/sdb", name="sdb",
            model="Seagate Barracuda ST2000DM008", serial="ZFN0ABCD",
            vendor="Seagate", disk_type=DISK_TYPE_HDD,
            size_bytes=2_000_398_934_016, size_human="1.8 TiB",
            is_system=True, encryption=ENC_NONE,
            transport="sata", firmware="0001",
            smart_available=True, mountpoints=["/", "/boot"],
        ),
        DiskInfo(
            device="[MOCK] /dev/nvme0n1", name="nvme0n1",
            model="WD Black SN850X 1TB", serial="WD987654321",
            vendor="Western Digital", disk_type=DISK_TYPE_NVME,
            size_bytes=1_000_204_886_016, size_human="931.5 GiB",
            is_system=False, encryption=ENC_NONE,
            transport="nvme", firmware="620131WD",
            smart_available=False, mountpoints=[],
        ),
    ]
