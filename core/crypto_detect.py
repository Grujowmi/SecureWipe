"""
SecureWipe — crypto_detect.py
Analyse du chiffrement détecté et recommandation de la méthode
d'effacement cryptographique appropriée.

Ce module est cross-platform : il reçoit un DiskInfo (Linux ou Windows)
et retourne un CryptoProfile décrivant ce qu'il faut faire.
"""

import re
import sys
import subprocess
import os
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

# ──────────────────────────────────────────────
# Énumérations
# ──────────────────────────────────────────────

class CryptoMethod(Enum):
    """Méthode d'effacement cryptographique recommandée."""
    NONE             = auto()   # Pas de chiffrement → pas de crypto erase
    LUKS_ERASE       = auto()   # cryptsetup erase (LUKS1/2)
    SED_ATA          = auto()   # hdparm ATA Secure Erase (SED SATA)
    SED_NVME         = auto()   # nvme format --ses=1 (SED NVMe)
    BITLOCKER_OFF    = auto()   # manage-bde -off puis format
    BITLOCKER_KEY    = auto()   # Suppression clé BitLocker (si accès recovery key)


class SedStatus(Enum):
    """État du verrou SED (ATA Security Feature Set)."""
    NOT_SUPPORTED = auto()
    FROZEN        = auto()   # Frozen = impossible d'envoyer Secure Erase sans reboot
    LOCKED        = auto()
    ENABLED       = auto()   # Prêt pour Secure Erase
    NOT_ENABLED   = auto()   # SED présent mais pas activé


# ──────────────────────────────────────────────
# Structure résultat
# ──────────────────────────────────────────────

@dataclass
class CryptoProfile:
    """
    Résultat complet de l'analyse cryptographique d'un disque.
    Transmis au wipe_engine pour exécuter la bonne méthode.
    """
    # Y a-t-il une option de crypto erase disponible ?
    has_crypto_option: bool = False

    # Méthode recommandée
    recommended_method: CryptoMethod = CryptoMethod.NONE

    # Détails LUKS
    luks_version: str = ""          # "LUKS1" ou "LUKS2"
    luks_device: str = ""           # ex: /dev/sda1 (partition LUKS)
    luks_cipher: str = ""           # ex: aes-xts-plain64

    # Détails SED
    sed_frozen: bool = False        # True → Secure Erase impossible sans reboot
    sed_enhanced: bool = False      # True → Enhanced Secure Erase disponible
    sed_time_min: int = 2           # Durée estimée en minutes

    # Détails BitLocker
    bitlocker_drives: list = field(default_factory=list)  # ex: ["C:"]
    bitlocker_pct: int = 0          # % chiffré

    # Avertissements à afficher à l'utilisateur
    warnings: list = field(default_factory=list)

    # Infos affichage
    display_name: str = ""          # Nom court pour le menu
    display_desc: str = ""          # Description pour le menu


# ──────────────────────────────────────────────
# Utilitaire subprocess
# ──────────────────────────────────────────────

def _run(cmd: list, timeout: int = 8) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "LANG": "C", "LC_ALL": "C"},
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


def _tool_ok(name: str) -> bool:
    rc, _, _ = _run(["which", name] if sys.platform != "win32" else ["where", name])
    return rc == 0


# ──────────────────────────────────────────────
# Analyse LUKS (Linux)
# ──────────────────────────────────────────────

def _analyse_luks(device: str) -> tuple[str, str, str, str]:
    """
    Retourne (luks_version, luks_device, luks_cipher, warning).
    Utilise cryptsetup luksDump pour obtenir les détails.
    """
    # Cherche la partition LUKS sur ce disque via blkid
    luks_device = ""
    rc, out, _ = _run(["blkid", "-t", "TYPE=crypto_LUKS", "-o", "device"])
    if rc == 0 and out:
        for line in out.splitlines():
            line = line.strip()
            # Garde les partitions de ce disque (ex: /dev/sda → /dev/sda1, /dev/sda2)
            dev_base = device.rstrip("0123456789").replace("n1", "")  # nvme0n1 → /dev/nvme0
            if line.startswith(device) or line.startswith(dev_base):
                luks_device = line
                break
        if not luks_device and out.splitlines():
            luks_device = out.splitlines()[0].strip()

    if not luks_device:
        luks_device = device  # fallback sur le disque entier

    # luksDump pour les détails
    luks_version = "LUKS"
    luks_cipher  = "aes-xts-plain64"
    warning      = ""

    if _tool_ok("cryptsetup"):
        rc, out, _ = _run(["cryptsetup", "luksDump", luks_device], timeout=5)
        if rc == 0:
            v = re.search(r'Version:\s+(\d)', out)
            c = re.search(r'[Cc]ipher(?:\s+name)?:\s+(\S+)', out)
            if v:
                luks_version = f"LUKS{v.group(1)}"
            if c:
                luks_cipher = c.group(1)
        else:
            warning = "cryptsetup luksDump a échoué — le disque sera quand même effacé via luksErase."
    else:
        warning = "cryptsetup non installé — l'effacement LUKS sera effectué via dd sur la partition."

    return luks_version, luks_device, luks_cipher, warning


# ──────────────────────────────────────────────
# Analyse SED / ATA Security (Linux)
# ──────────────────────────────────────────────

def _analyse_sed_linux(device: str) -> tuple[SedStatus, bool, int]:
    """
    Analyse l'état ATA Security via hdparm -I.
    Retourne (status, enhanced_available, erase_time_min).
    """
    if not _tool_ok("hdparm"):
        return SedStatus.NOT_SUPPORTED, False, 2

    rc, out, _ = _run(["hdparm", "-I", device], timeout=6)
    if rc != 0:
        return SedStatus.NOT_SUPPORTED, False, 2

    # Section Security dans la sortie hdparm
    in_security = False
    supported    = False
    enabled      = False
    frozen       = False
    locked       = False
    enhanced     = False
    erase_min    = 2

    for line in out.splitlines():
        if re.search(r'^\s*Security:', line):
            in_security = True
            continue
        if not in_security:
            continue
        # Fin de section : ligne non vide commençant en colonne 0 (pas d'indentation)
        if line and not line[0].isspace() and "Security" not in line:
            break

        l = line.lower().strip()
        if not l:
            continue
        # On détecte la négation "not X" pour ne pas inverser le sens
        is_negated = l.startswith("not")
        if "supported" in l and not is_negated:
            supported = True
        if "enabled" in l and not is_negated:
            enabled = True
        if "frozen" in l and not is_negated:
            frozen = True
        if "locked" in l and not is_negated:
            locked = True
        if "enhanced erase" in l:
            enhanced = True
        # Durée estimée : "2min for SECURITY ERASE UNIT"
        m = re.search(r'(\d+)min for security erase', l)
        if m:
            erase_min = int(m.group(1))

    if not supported:
        return SedStatus.NOT_SUPPORTED, False, 2
    if frozen:
        return SedStatus.FROZEN, enhanced, erase_min
    if locked:
        return SedStatus.LOCKED, enhanced, erase_min
    if enabled:
        return SedStatus.ENABLED, enhanced, erase_min
    return SedStatus.NOT_ENABLED, enhanced, erase_min


# ──────────────────────────────────────────────
# Analyse BitLocker (Windows)
# ──────────────────────────────────────────────

def _analyse_bitlocker_windows(drive_letters: list) -> tuple[list, int, str]:
    """
    Analyse l'état BitLocker sur les lettres de lecteur du disque.
    Retourne (encrypted_drives, pct_encrypted, warning).
    """
    encrypted = []
    pct_total = 0
    warning   = ""

    for letter in drive_letters:
        rc, out, _ = _run(["manage-bde", "-status", letter], timeout=8)
        if rc != 0:
            continue
        # Protection Status
        ps = re.search(r'Protection Status:\s+(.+)', out)
        if ps and "on" in ps.group(1).lower():
            encrypted.append(letter)
        # % chiffré
        pct = re.search(r'Percentage Encrypted:\s+([\d.]+)%', out)
        if pct:
            pct_total = max(pct_total, int(float(pct.group(1))))

    if not encrypted:
        warning = "manage-bde indique que BitLocker n'est pas actif sur ce disque."

    return encrypted, pct_total, warning


# ──────────────────────────────────────────────
# Analyse NVMe Secure Erase
# ──────────────────────────────────────────────

def _analyse_nvme(device: str) -> tuple[bool, str]:
    """
    Vérifie si nvme-cli est disponible et si le format NVMe est supporté.
    Retourne (supported, warning).
    """
    if not _tool_ok("nvme"):
        return False, "nvme-cli non installé. Installer avec : apt install nvme-cli"

    # nvme id-ctrl pour vérifier le support du Format NVM Command
    rc, out, _ = _run(["nvme", "id-ctrl", device, "--output-format=normal"], timeout=6)
    if rc != 0:
        return True, ""  # On suppose supporté si on peut pas vérifier

    # Vérifie fna (Format NVM Attributes) — bit 2 = supports crypto erase
    fna = re.search(r'fna\s*:\s*(0x[0-9a-fA-F]+|\d+)', out)
    if fna:
        val = int(fna.group(1), 16) if fna.group(1).startswith("0x") else int(fna.group(1))
        if val & 0x4:  # bit 2 = Cryptographic Erase supported
            return True, ""
        else:
            return True, "Le contrôleur NVMe supporte Format mais pas nécessairement Crypto Erase (fna bit 2 = 0). L'effacement sera quand même effectué."

    return True, ""


# ──────────────────────────────────────────────
# Fonction principale
# ──────────────────────────────────────────────

def analyse_disk_crypto(disk) -> CryptoProfile:
    """
    Analyse le chiffrement d'un DiskInfo (Linux ou Windows).
    Retourne un CryptoProfile avec la méthode recommandée et les détails.

    Compatile avec disk_linux.DiskInfo et disk_windows.DiskInfo
    grâce à l'interface commune.
    """
    profile = CryptoProfile()

    enc       = getattr(disk, "encryption", "none").lower()
    dtype     = getattr(disk, "disk_type", "unknown").lower()
    device    = getattr(disk, "device", "")
    transport = getattr(disk, "transport", "").lower()
    letters   = getattr(disk, "drive_letters", []) or getattr(disk, "mountpoints", [])

    is_linux   = sys.platform != "win32"
    is_windows = sys.platform == "win32"

    # ── Cas 1 : LUKS (Linux) ──────────────────
    if enc == "luks" and is_linux:
        luks_v, luks_dev, luks_cipher, warn = _analyse_luks(device)
        profile.has_crypto_option    = True
        profile.recommended_method   = CryptoMethod.LUKS_ERASE
        profile.luks_version         = luks_v
        profile.luks_device          = luks_dev
        profile.luks_cipher          = luks_cipher
        profile.display_name         = f"Crypto Erase — {luks_v}"
        profile.display_desc         = (
            f"Destruction de la clé maître {luks_v} ({luks_cipher}). "
            "Les données deviennent inaccessibles instantanément."
        )
        if warn:
            profile.warnings.append(warn)
        return profile

    # ── Cas 2 : SED (Linux, SATA) ─────────────
    if enc == "sed" and is_linux and dtype in ("hdd", "ssd"):
        status, enhanced, erase_min = _analyse_sed_linux(device)

        if status == SedStatus.FROZEN:
            profile.has_crypto_option = True
            profile.recommended_method = CryptoMethod.SED_ATA
            profile.sed_frozen    = True
            profile.sed_enhanced  = enhanced
            profile.sed_time_min  = erase_min
            profile.warnings.append(
                "⚠ Le disque SED est en état 'frozen' (verrouillé par le BIOS/UEFI).\n"
                "  → Débranchez et rebranchez le disque à chaud (hot-plug SATA),\n"
                "    ou redémarrez depuis un LiveUSB sans suspension SED,\n"
                "    puis relancez SecureWipe."
            )
            profile.display_name = "Crypto Erase — SED ATA (⚠ frozen)"
            profile.display_desc = "ATA Secure Erase disponible après déblocage du frozen."

        elif status in (SedStatus.ENABLED, SedStatus.NOT_ENABLED, SedStatus.LOCKED):
            profile.has_crypto_option  = True
            profile.recommended_method = CryptoMethod.SED_ATA
            profile.sed_frozen    = False
            profile.sed_enhanced  = enhanced
            profile.sed_time_min  = erase_min
            profile.display_name  = "Crypto Erase — SED ATA Secure Erase"
            profile.display_desc  = (
                f"Commande ATA Secure Erase{'Enhanced' if enhanced else ''}. "
                f"Durée estimée : {erase_min} min."
            )
        else:
            # SED non supporté finalement
            profile.has_crypto_option = False
            profile.recommended_method = CryptoMethod.NONE

        return profile

    # ── Cas 3 : SED NVMe (Linux) ──────────────
    if enc == "sed" and is_linux and dtype == "nvme":
        supported, warn = _analyse_nvme(device)
        profile.has_crypto_option  = supported
        profile.recommended_method = CryptoMethod.SED_NVME if supported else CryptoMethod.NONE
        profile.display_name       = "Crypto Erase — NVMe Format (--ses=1)"
        profile.display_desc       = "nvme format avec Cryptographic Erase. Données inaccessibles instantanément."
        if warn:
            profile.warnings.append(warn)
        return profile

    # ── Cas 4 : BitLocker (Windows) ───────────
    if enc == "bitlocker" and is_windows:
        enc_drives, pct, warn = _analyse_bitlocker_windows(letters)
        profile.has_crypto_option    = True
        profile.recommended_method   = CryptoMethod.BITLOCKER_OFF
        profile.bitlocker_drives     = enc_drives or letters
        profile.bitlocker_pct        = pct
        profile.display_name         = "Crypto Erase — Désactivation BitLocker"
        profile.display_desc         = (
            f"Désactive BitLocker ({pct}% chiffré) puis formate le disque. "
            "Clé AES détruite, données inaccessibles."
        )
        if warn:
            profile.warnings.append(warn)
        return profile

    # ── Cas 5 : Aucun chiffrement ─────────────
    profile.has_crypto_option  = False
    profile.recommended_method = CryptoMethod.NONE
    return profile


# ──────────────────────────────────────────────
# Résumé lisible pour l'UI
# ──────────────────────────────────────────────

def crypto_summary(profile: CryptoProfile, lang: str = "fr") -> dict:
    """
    Retourne un dict prêt pour l'affichage dans le menu wipe_mode.
    {
        'available': bool,
        'name': str,
        'desc': str,
        'warnings': list[str],
        'method': CryptoMethod,
    }
    """
    return {
        "available": profile.has_crypto_option,
        "name":      profile.display_name,
        "desc":      profile.display_desc,
        "warnings":  profile.warnings,
        "method":    profile.recommended_method,
        "profile":   profile,
    }
