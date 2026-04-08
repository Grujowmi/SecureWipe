#!/usr/bin/env python3
"""
SecureWipe v2.0.0
Outil open source d'effacement sécurisé de supports de stockage.
Conforme ANSSI Palier 1/2 et NIST SP 800-88 Rev.2.

Licence : GPL v3
Auteur  : Grujowmi <grujowmi@proton.me>
Usage   :
  Linux   : sudo python3 securewipe.py
  Test    : sudo python3 securewipe.py --test-disk /tmp/testdisk.img
  Mock    : sudo python3 securewipe.py --mock
  Windows : python securewipe.py (en tant qu'Administrateur)
"""

import os
import sys
import platform
import argparse
from pathlib import Path

# Ajoute le répertoire du script au path Python
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# ──────────────────────────────────────────────
# Imports modules SecureWipe
# ──────────────────────────────────────────────

from core.i18n  import select_language, t
from core.ui    import (
    check_privileges, print_banner, print_section,
    prompt_operator, print_disk_table, select_disk,
    confirm_wipe, ask_another,
)
from core.crypto_detect import analyse_disk_crypto, crypto_summary
from core.wipe_engine   import run_wipe, select_wipe_mode, WipeMode, WipeStatus
from cert.generator     import generate_certificate

from rich import print as rprint
from rich.prompt import Prompt
from rich.console import Console

console = Console()

IS_WINDOWS = sys.platform == "win32"
IS_LINUX   = sys.platform != "win32"


# ──────────────────────────────────────────────
# Chargement du module disque selon l'OS
# ──────────────────────────────────────────────

def _get_disk_module():
    if IS_WINDOWS:
        from core import disk_windows as dm
    else:
        from core import disk_linux as dm
    return dm


# ──────────────────────────────────────────────
# Sélection du dossier de sortie certificat
# ──────────────────────────────────────────────

def _prompt_output_dir() -> Path:
    print_section(t("cert_title"))
    raw = Prompt.ask(
        f"  {t('cert_output_prompt')} {t('cert_output_default')}",
        default="",
        console=console,
    ).strip()
    if not raw:
        return SCRIPT_DIR
    p = Path(raw)
    try:
        p.mkdir(parents=True, exist_ok=True)
        return p
    except Exception as e:
        rprint(f"  [yellow]⚠ Dossier invalide ({e}) — utilisation du dossier script.[/yellow]")
        return SCRIPT_DIR


# ──────────────────────────────────────────────
# Boucle principale : un disque
# ──────────────────────────────────────────────

def _wipe_one_disk(operator: dict, dm, test_disk_path: str = None) -> bool:
    """
    Gère l'effacement complet d'un disque :
      détection → sélection → crypto → mode → confirmation → effacement → certificat
    Retourne True si l'opération s'est déroulée sans erreur fatale.
    """
    from pathlib import Path as _Path

    # ── Détection des disques ──
    print_section(t("disk_title"))
    rprint(f"  [dim]{t('disk_scanning')}[/dim]")
    console.print()

    # Mode test : injecte un fichier image comme faux disque
    if test_disk_path:
        p = _Path(test_disk_path)
        if not p.exists():
            rprint(f"  [bold red]Fichier introuvable : {test_disk_path}[/bold red]")
            return False
        import os as _os
        from core.disk_linux import DiskInfo, DISK_TYPE_HDD, ENC_NONE, _bytes_to_human
        size = p.stat().st_size
        disks = [DiskInfo(
            device=str(p), name=p.name,
            model="[TEST] Fichier image",
            serial="TEST-0001",
            disk_type=DISK_TYPE_HDD,
            size_bytes=size,
            size_human=_bytes_to_human(size),
            is_system=False,
            encryption=ENC_NONE,
            transport="test",
            vendor="SecureWipe", firmware="",
            mountpoints=[],
        )]
    else:
        disks = dm.list_disks()

    # Fallback mocks si container sandboxé (dev uniquement)
    if not disks:
        rprint(f"  [yellow]{t('disk_none_found')}[/yellow]")
        # En prod on quitterait ici. Pour le dev :
        if os.environ.get("SECUREWIPE_MOCK") == "1":
            rprint("  [dim](Mode mock activé — SECUREWIPE_MOCK=1)[/dim]")
            disks = dm._mock_disks()
        else:
            return False

    print_disk_table(disks)

    # ── Sélection du disque ──
    disk = select_disk(disks)

    # ── Analyse crypto ──
    rprint(f"\n  [dim]Analyse du chiffrement...[/dim]")
    crypto_profile = analyse_disk_crypto(disk)

    # Affiche warnings SED frozen si présents
    for warn in crypto_profile.warnings:
        console.print()
        rprint(f"  [yellow]{warn}[/yellow]")

    # ── Sélection du mode d'effacement ──
    mode, custom_passes, verify_pct, mode_label = select_wipe_mode(disk, crypto_profile)

    # ── Confirmation finale ──
    confirmed = confirm_wipe(disk, mode_label)
    if not confirmed:
        return True   # Pas une erreur — l'utilisateur a annulé

    # ── Effacement ──
    result = run_wipe(
        disk=disk,
        mode=mode,
        custom_passes=custom_passes,
        verify_pct=verify_pct,
        crypto_profile=crypto_profile,
    )

    # ── Certificat ──
    console.print()
    output_dir = _prompt_output_dir()

    rprint(f"  [dim]{t('cert_generating')}[/dim]")
    try:
        pdf_path, txt_path = generate_certificate(
            operator=operator,
            disk=disk,
            result=result,
            mode_label=mode_label,
            verify_pct=verify_pct,
            output_dir=output_dir,
            script_dir=SCRIPT_DIR,
        )
        rprint(f"  {t('cert_success', path=pdf_path)}")
        rprint(f"  {t('cert_log_success', path=txt_path)}")
    except Exception as e:
        rprint(f"  [red]Erreur génération certificat : {e}[/red]")

    console.print()
    return result.status == WipeStatus.SUCCESS


# ──────────────────────────────────────────────
# Vérification OS supporté
# ──────────────────────────────────────────────

def _check_os():
    if sys.platform not in ("linux", "linux2", "win32", "darwin"):
        rprint(t("err_os_unsupported", os=sys.platform))
        sys.exit(1)
    if sys.platform == "darwin":
        # macOS — non supporté officiellement mais les modules Linux fonctionnent
        rprint("[yellow]⚠ macOS non officiellement supporté. Continuez à vos risques.[/yellow]")


# ──────────────────────────────────────────────
# Point d'entrée
# ──────────────────────────────────────────────

def _parse_args():
    """Parse les arguments de ligne de commande."""
    parser = argparse.ArgumentParser(
        prog="securewipe",
        description="SecureWipe — Effacement sécurisé de supports (ANSSI/NIST)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  sudo python3 securewipe.py
  sudo python3 securewipe.py --test-disk /tmp/testdisk.img
  sudo python3 securewipe.py --mock
        """
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Force le mode terminal (pas de GUI).",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Force le mode graphique (CustomTkinter).",
    )
    parser.add_argument(
        "--test-disk",
        metavar="FICHIER",
        help="Utilise un fichier image comme faux disque (mode test Linux/WSL). "
             "Ex: sudo python3 securewipe.py --test-disk /tmp/testdisk.img",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Charge des disques fictifs pour tester l'interface (Windows et Linux).",
    )
    return parser.parse_args()


def _gui_available() -> bool:
    """Vérifie si CustomTkinter est disponible et qu'un display existe."""
    try:
        import customtkinter
        if IS_LINUX and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            return False
        return True
    except ImportError:
        return False


def _ask_mode() -> str:
    """Demande à l'utilisateur GUI ou CLI au lancement."""
    console.print()
    rprint("  [bold cyan]SecureWipe v2.0.0[/bold cyan]")
    console.print()
    rprint("  [bold]1.[/bold]  Interface graphique (GUI)")
    rprint("  [bold]2.[/bold]  Interface terminal  (CLI)")
    console.print()
    from rich.prompt import Prompt
    choice = Prompt.ask("  Mode", choices=["1","2"], default="1").strip()
    return "gui" if choice == "1" else "cli"


def main():
    args = _parse_args()

    # Injecte les arguments dans les variables d'environnement
    if args.test_disk:
        os.environ["SECUREWIPE_DEV"] = args.test_disk
    if args.mock:
        os.environ["SECUREWIPE_MOCK"] = "1"

    # Détermine le mode
    if getattr(args, "gui", False):
        mode = "gui"
    elif getattr(args, "cli", False):
        mode = "cli"
    elif _gui_available():
        mode = _ask_mode()
    else:
        mode = "cli"
        console.print()
        rprint("  [dim]GUI non disponible (CustomTkinter absent ou pas de display) — mode terminal.[/dim]")

    if mode == "gui":
        # Détecte la langue système
        from core.i18n import _detect_system_lang
        lang = _detect_system_lang()
        from gui.app import run_gui
        run_gui(lang=lang)
        return

    try:
        # 1. Vérification OS
        _check_os()

        # 2. Vérification privilèges (avant tout affichage lourd)
        check_privileges()

        # 3. Sélection langue
        select_language()

        # 4. Bannière
        print_banner()

        # 5. Identification opérateur
        operator = prompt_operator()

        # 6. Chargement module disque
        dm = _get_disk_module()

        # 7. Boucle multi-disques
        test_disk_path = getattr(args, "test_disk", None)
        while True:
            success = _wipe_one_disk(operator, dm, test_disk_path=test_disk_path)

            if not ask_another():
                break

        # 8. Au revoir
        console.print()
        rprint(f"  {t('session_goodbye')}")
        console.print()

    except KeyboardInterrupt:
        console.print()
        rprint("\n  [yellow]SecureWipe interrompu.[/yellow]")
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        console.print()
        rprint(f"  [bold red]Erreur inattendue : {e}[/bold red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
