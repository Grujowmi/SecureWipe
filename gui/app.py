"""
SecureWipe GUI — app.py
Fenêtre principale avec header fixe + stepper + contenu par étapes.
"""
import sys, os
from pathlib import Path
import customtkinter as ctk
from PIL import Image

from gui.theme import *
from gui.steps.step1_operator import Step1Operator
from gui.steps.step2_disk     import Step2Disk
from gui.steps.step3_method   import Step3Method
from gui.steps.step4_wipe     import Step4Wipe

# Config CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

SCRIPT_DIR = Path(__file__).resolve().parent.parent

class SecureWipeApp(ctk.CTk):
    def __init__(self, lang="fr"):
        super().__init__()

        # i18n
        from core import i18n as i18n_mod
        i18n_mod._translations = i18n_mod._load(lang)
        self._lang = lang

        # Fenêtre
        self.title("SecureWipe v2.0.0")
        self.geometry(f"{WIN_W}x{WIN_H}")
        self.minsize(WIN_MIN_W, WIN_MIN_H)
        self.configure(fg_color=BG_DARK)

        # Icône
        icon_path = SCRIPT_DIR / "cert" / "template" / "logo.png"
        if icon_path.exists():
            try:
                img = Image.open(str(icon_path))
                self.iconphoto(True, ctk.CTkImage(img).create_scaled_photo_image(32,32, "ctk_scaled"))
            except Exception:
                pass

        self._step      = 0
        self._step_done = 0   # Nombre d'étapes validées
        self._operator  = None
        self._disk      = None
        self._config    = None
        self._profile   = None

        self._build_layout()
        self._show_step(0)

    # ──────────────────────────────────────────────
    # Layout principal
    # ──────────────────────────────────────────────

    def _build_layout(self):
        # ── Header fixe ──
        self._header = ctk.CTkFrame(self, height=HEADER_H,
            fg_color=BG_CARD, corner_radius=0,
            border_width=0)
        self._header.pack(fill="x", side="top")
        self._header.pack_propagate(False)
        self._build_header()

        # ── Séparateur ──
        ctk.CTkFrame(self, height=1, fg_color=BORDER).pack(fill="x")

        # ── Stepper ──
        self._stepper_frame = ctk.CTkFrame(self, height=STEPPER_H,
            fg_color=BG_DARK, corner_radius=0)
        self._stepper_frame.pack(fill="x")
        self._stepper_frame.pack_propagate(False)
        self._build_stepper()

        # ── Séparateur ──
        ctk.CTkFrame(self, height=1, fg_color=BORDER).pack(fill="x")

        # ── Footer (packé AVANT le contenu — règle obligatoire de Tkinter pack) ──
        # Si le footer est packé après expand=True, il se fait écraser
        ctk.CTkFrame(self, height=1, fg_color=BORDER).pack(fill="x", side="bottom")
        self._footer = ctk.CTkFrame(self, height=FOOTER_H,
            fg_color=BG_CARD, corner_radius=0)
        self._footer.pack(fill="x", side="bottom")
        self._footer.pack_propagate(False)
        self._build_footer()

        # ── Zone contenu (packée EN DERNIER avec expand=True) ──
        self._content = ctk.CTkFrame(self, fg_color=BG_DARK, corner_radius=0)
        self._content.pack(fill="both", expand=True)

    def _build_header(self):
        # Logo
        logo_path = SCRIPT_DIR / "cert" / "template" / "logo.png"
        if logo_path.exists():
            try:
                img = ctk.CTkImage(Image.open(str(logo_path)),
                    size=(48,48))
                ctk.CTkLabel(self._header, image=img, text="",
                    width=56).pack(side="left", padx=(12,4), pady=8)
            except Exception:
                pass

        # Titre
        title_frame = ctk.CTkFrame(self._header, fg_color="transparent")
        title_frame.pack(side="left", padx=4)
        ctk.CTkLabel(title_frame, text="SecureWipe",
            font=FONT_TITLE, text_color=BLUE_LIGHT).pack(anchor="w")
        ctk.CTkLabel(title_frame, text="ANSSI · NIST SP 800-88 Rev.2 · GPL v3",
            font=FONT_SMALL, text_color=TEXT_DIM).pack(anchor="w")

        # Langue
        lang_frame = ctk.CTkFrame(self._header, fg_color="transparent")
        lang_frame.pack(side="right", padx=16)
        self._lang_var = ctk.StringVar(value="FR" if self._lang=="fr" else "EN")
        ctk.CTkSegmentedButton(lang_frame,
            values=["FR","EN"],
            variable=self._lang_var,
            command=self._switch_lang,
            fg_color=BG_INPUT,
            selected_color=BLUE_PRIMARY,
            selected_hover_color=BLUE_LIGHT,
            unselected_color=BG_INPUT,
            unselected_hover_color=BG_HOVER,
            text_color=TEXT_PRIMARY,
            font=FONT_STEP, height=32,
            corner_radius=RADIUS_SM,
        ).pack()

    def _build_stepper(self):
        from core.i18n import t
        from core.i18n import t
        steps = [
            f"1. {t('step1_label')}",
            f"2. {t('step2_label')}",
            f"3. {t('step3_label')}",
            f"4. {t('step4_label')}",
        ]
        self._step_labels = []
        container = ctk.CTkFrame(self._stepper_frame, fg_color="transparent")
        container.pack(expand=True)

        for i, label in enumerate(steps):
            # Numéro
            step_done = getattr(self, "_step_done", self._step)
            num_color = (STEP_ACTIVE if i == self._step and step_done < 4
                         else GREEN_OK if i < max(self._step, step_done)
                         else GREEN_OK if step_done >= 4
                         else BG_HOVER)
            circle = ctk.CTkButton(container,
                text="✓" if (i < self._step or step_done >= 4) else str(i+1),
                width=28, height=28, corner_radius=14,
                fg_color=num_color, hover_color=num_color,
                text_color=TEXT_PRIMARY, font=FONT_SMALL)
            circle.pack(side="left", padx=(4,2))

            lbl = ctk.CTkLabel(container, text=label,
                font=FONT_STEP,
                text_color=TEXT_PRIMARY if i == self._step else TEXT_SECOND)
            lbl.pack(side="left", padx=(0,8))
            self._step_labels.append((circle, lbl))

            # Connecteur
            if i < len(steps)-1:
                ctk.CTkFrame(container, width=24, height=1,
                    fg_color=BLUE_DARK).pack(side="left", padx=4)

    def _refresh_stepper(self):
        for w in self._stepper_frame.winfo_children():
            w.destroy()
        self._build_stepper()

    # ──────────────────────────────────────────────
    # Footer avec boutons nav
    # ──────────────────────────────────────────────

    def _build_footer(self):
        # Gauche : version
        ctk.CTkLabel(self._footer, text="SecureWipe v2.0.0 — GPL v3",
            font=FONT_SMALL, text_color=TEXT_DIM).pack(side="left", padx=16)

        # Droite : boutons
        btn_frame = ctk.CTkFrame(self._footer, fg_color="transparent")
        btn_frame.pack(side="right", padx=16)

        from core.i18n import t
        self._btn_back = ctk.CTkButton(btn_frame, text=f"← {t('nav_back')}",
            font=FONT_BTN, height=BTN_H,
            fg_color=BG_CARD, hover_color=BG_HOVER,
            text_color=TEXT_SECOND, border_width=1, border_color=BORDER,
            corner_radius=RADIUS_SM, command=self._go_back)
        self._btn_back.pack(side="left", padx=(0,8))

        self._btn_next = ctk.CTkButton(btn_frame,
            text="Suivant →", font=FONT_BTN, height=BTN_H,
            fg_color=BLUE_PRIMARY, hover_color=BLUE_LIGHT,
            text_color="#ffffff", corner_radius=RADIUS_SM,
            command=self._go_next)
        self._btn_next.pack(side="left")
        self._update_nav_buttons()

    def _update_nav_buttons(self):
        from core.i18n import t
        self._btn_back.configure(
            state="normal" if self._step > 0 else "disabled",
            text=f"← {t('nav_back')}",
        )
        if self._step == 3:
            self._btn_next.configure(
                text=f"🦈  {t('nav_wipe')}",
                fg_color=RED_DANGER, hover_color=RED_LIGHT,
            )
        else:
            self._btn_next.configure(
                text=f"{t('nav_next')} →",
                fg_color=BLUE_PRIMARY, hover_color=BLUE_LIGHT,
            )

    # ──────────────────────────────────────────────
    # Navigation
    # ──────────────────────────────────────────────

    def _show_step(self, n):
        for w in self._content.winfo_children():
            w.destroy()
        self._step = n
        if n < 3:
            self._step_done = 0  # Reset si on revient en arrière
        self._refresh_stepper()
        self._update_nav_buttons()

        if n == 0:
            self._s1 = Step1Operator(self._content, lang=self._lang)
            self._s1.pack(fill="both", expand=True)
            self._s1.bind("<<LangChanged>>",
                lambda e: self._switch_lang(
                    "FR" if self._s1.get_lang()=="fr" else "EN"))
            self._s1.bind("<<NextStep>>", lambda e: self._go_next())
            # Raccourci clavier global Entrée
            self.bind("<Return>", lambda e: self._go_next())

        elif n == 1:
            self.unbind("<Return>")  # Plus de navigation par Entrée après step1
            self._s2 = Step2Disk(self._content)
            self._s2.pack(fill="both", expand=True)

        elif n == 2:
            profile = None
            if self._disk:
                try:
                    from core.crypto_detect import analyse_disk_crypto
                    profile = analyse_disk_crypto(self._disk)
                except Exception:
                    pass
            self._profile = profile
            self._s3 = Step3Method(self._content, disk=self._disk,
                crypto_profile=profile)
            self._s3.pack(fill="both", expand=True)

        elif n == 3:
            self._s4 = Step4Wipe(self._content, app_ref=self)
            self._s4.pack(fill="both", expand=True)
            self._s4.load_data(self._operator, self._disk,
                               self._config, self._profile)
            self._s4.bind("<<WipeDone>>", self._on_wipe_done)

    def _go_next(self):
        if self._step == 0:
            op = self._s1.validate()
            if not op: return
            self._operator = op
            # Sync langue
            new_lang = self._s1.get_lang()
            if new_lang != self._lang:
                self._lang = new_lang
                from core import i18n as im
                im._translations = im._load(self._lang)
                self._lang_var.set("FR" if self._lang=="fr" else "EN")
            self._show_step(1)

        elif self._step == 1:
            if not self._s2.validate(): return
            self._disk = self._s2.get_selected()
            self._show_step(2)

        elif self._step == 2:
            if not self._s3.validate(): return
            self._config = self._s3.get_config()
            self._show_step(3)

        elif self._step == 3:
            # Confirmation puis lancement
            self._confirm_and_wipe()

    def _go_back(self):
        if self._step > 0:
            self._show_step(self._step - 1)

    def _confirm_and_wipe(self):
        """Fenêtre de confirmation avant effacement."""
        from core.i18n import t
        dialog = ctk.CTkToplevel(self)
        dialog.title("Confirmation")
        dialog.geometry("520x300")
        dialog.configure(fg_color=BG_DARK)
        dialog.grab_set()
        dialog.resizable(False, False)

        ctk.CTkLabel(dialog,
            text=t("confirm_warn").replace("[bold red]","").replace("[/bold red]",""),
            font=FONT_HEADING, text_color=RED_DANGER,
            wraplength=460).pack(pady=(24,8), padx=20)

        ctk.CTkLabel(dialog,
            text=f"{self._disk.device} — {self._disk.model}\n{self._disk.size_human} — {self._config['mode_label']}",
            font=FONT_BODY, text_color=TEXT_PRIMARY).pack(pady=8)

        ctk.CTkLabel(dialog,
            text=f"Tapez  {t('confirm_word')}  pour confirmer :",
            font=FONT_SMALL, text_color=TEXT_SECOND).pack(pady=(16,4))

        confirm_var = ctk.StringVar()
        entry = ctk.CTkEntry(dialog, textvariable=confirm_var,
            font=FONT_HEADING, fg_color=BG_INPUT, text_color=RED_DANGER,
            border_color=RED_DANGER, height=BTN_H, width=220,
            justify="center")
        entry.pack(pady=4)
        entry.focus()

        err_lbl = ctk.CTkLabel(dialog, text="", font=FONT_SMALL,
            text_color=RED_DANGER)
        err_lbl.pack()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=16)

        def _do():
            if confirm_var.get().strip() == t("confirm_word"):
                dialog.destroy()
                self._btn_next.configure(state="disabled")
                self._btn_back.configure(state="disabled")
                self._s4.start_wipe()
            else:
                err_lbl.configure(
                    text=f"Tapez exactement :  {t('confirm_word')}")

        ctk.CTkButton(btn_frame, text=t("confirm_word"),
            font=FONT_BTN, fg_color=RED_DANGER, hover_color=RED_LIGHT,
            height=BTN_H, corner_radius=RADIUS_SM, command=_do
            ).pack(side="left", padx=8)
        ctk.CTkButton(btn_frame, text="Annuler",
            font=FONT_BTN, fg_color=BG_CARD, hover_color=BG_HOVER,
            border_width=1, border_color=BORDER,
            height=BTN_H, corner_radius=RADIUS_SM,
            command=dialog.destroy).pack(side="left", padx=8)

        entry.bind("<Return>", lambda e: _do())

    def quit_app(self):
        """Ferme le GUI ET le process Python (ferme aussi le terminal)."""
        import sys, os
        self.destroy()
        os._exit(0)

    def _on_wipe_done(self, event=None):
        """Marque le stepper final en vert."""
        self._btn_back.configure(state="disabled")
        self._btn_next.configure(state="disabled")
        self._step_done = 4
        self._refresh_stepper()

    # ──────────────────────────────────────────────
    # Changement de langue
    # ──────────────────────────────────────────────

    def _switch_lang(self, val):
        # Bloque si un effacement est en cours
        if self._step == 3 and hasattr(self, "_s4") and getattr(self._s4, "_running", False):
            self._lang_var.set("FR" if self._lang == "fr" else "EN")  # Remet l'ancienne valeur
            return
        self._lang = "fr" if val == "FR" else "en"
        from core import i18n as im
        im._translations = im._load(self._lang)
        self._lang_var.set(val)
        self._show_step(self._step)


def run_gui(lang: str = "fr"):
    """Point d'entrée GUI."""
    app = SecureWipeApp(lang=lang)
    app.mainloop()
