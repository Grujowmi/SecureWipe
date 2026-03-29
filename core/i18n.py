"""
SecureWipe — i18n module
Gestion des traductions FR/EN avec détection automatique de la locale.
"""

import json
import locale
import os
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich import print as rprint

console = Console()

# Chemin vers le dossier i18n (relatif à ce fichier)
I18N_DIR = Path(__file__).parent.parent / "i18n"

SUPPORTED_LANGS = {
    "1": "fr",
    "2": "en",
}

_translations: dict = {}
_current_lang: str = "en"


def _load(lang: str) -> dict:
    """Charge le fichier de traduction pour la langue donnée."""
    path = I18N_DIR / f"{lang}.json"
    if not path.exists():
        console.print(f"[red]Translation file not found: {path}[/red]")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def t(key: str, **kwargs) -> str:
    """
    Retourne la chaîne traduite pour la clé donnée.
    Supporte les placeholders {variable} via kwargs.
    """
    val = _translations.get(key, f"[MISSING:{key}]")
    if kwargs:
        try:
            val = val.format(**kwargs)
        except KeyError:
            pass
    return val


def _detect_system_lang() -> str:
    """Détecte la langue système et retourne 'fr' ou 'en'."""
    try:
        # Essaie d'abord la variable d'environnement LANG
        env_lang = os.environ.get("LANG", "") or os.environ.get("LANGUAGE", "")
        if env_lang.lower().startswith("fr"):
            return "fr"

        # Fallback sur locale Python
        loc = locale.getdefaultlocale()
        if loc and loc[0] and loc[0].lower().startswith("fr"):
            return "fr"

        # Windows : lecture du registre via locale
        if sys.platform == "win32":
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            # 0x040C = French, 0x0C0C = French Canadian, etc.
            if (lang_id & 0xFF) == 0x0C:
                return "fr"

    except Exception:
        pass

    return "en"


def select_language() -> str:
    """
    Affiche le menu de sélection de langue.
    Détecte la locale système, propose confirmation, ou menu manuel.
    Retourne le code langue choisi ('fr' ou 'en').
    """
    global _translations, _current_lang

    # Charge EN par défaut pour le menu initial
    _translations = _load("en")
    _current_lang = "en"

    detected = _detect_system_lang()
    detected_name = "Français" if detected == "fr" else "English"

    console.print()
    console.print(Panel(
        "[bold cyan]SecureWipe[/bold cyan]",
        subtitle="[dim]Secure Storage Sanitization[/dim]",
        border_style="cyan",
        padding=(0, 4),
    ))
    console.print()

    # Affiche la langue détectée et demande confirmation
    rprint(f"  [dim]Langue détectée / Detected language:[/dim] [bold cyan]{detected_name}[/bold cyan]")
    console.print()

    # Propose les options
    rprint("  [bold]1.[/bold]  Français")
    rprint("  [bold]2.[/bold]  English")
    console.print()

    while True:
        choice = Prompt.ask(
            "  [bold white]Sélection / Selection[/bold white]",
            default="1" if detected == "fr" else "2",
            console=console,
        ).strip()

        if choice in SUPPORTED_LANGS:
            chosen = SUPPORTED_LANGS[choice]
            break
        # Accepte aussi "fr"/"en" directement
        elif choice.lower() in ("fr", "français", "francais"):
            chosen = "fr"
            break
        elif choice.lower() in ("en", "english"):
            chosen = "en"
            break
        else:
            rprint("  [red]Choix invalide / Invalid choice. Entrez 1 ou 2.[/red]")

    # Charge la langue choisie
    _translations = _load(chosen)
    _current_lang = chosen

    console.print()
    rprint(f"  [green]✓[/green] {t('lang_name')} sélectionné / selected.")
    console.print()

    return chosen


def get_lang() -> str:
    """Retourne la langue courante."""
    return _current_lang
