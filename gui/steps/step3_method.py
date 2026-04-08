"""SecureWipe GUI — Step 3 : Méthode d'effacement"""
import customtkinter as ctk
from gui.theme import *
from core.i18n import t
from core.wipe_engine import WipeMode

MODES = [
    ("anssi1",  "wipe_m1_name", "wipe_m1_desc", "wipe_m1_compat",  ["hdd"],             False),
    ("anssi2",  "wipe_m2_name", "wipe_m2_desc", "wipe_m2_compat",  ["hdd"],             False),
    ("purge",   "wipe_m3_name", "wipe_m3_desc", "wipe_m3_compat",  ["hdd","ssd","nvme"],False),
    ("crypto",  "wipe_m4_name", "wipe_m4_desc", "wipe_m4_compat",  ["hdd","ssd","nvme"],True),
    ("custom",  "wipe_m5_name", "wipe_m5_desc", "wipe_m5_compat",  ["hdd"],             False),
]
MODE_MAP = {
    "anssi1": WipeMode.ANSSI_P1,
    "anssi2": WipeMode.ANSSI_P2,
    "purge":  WipeMode.NIST_PURGE,
    "crypto": WipeMode.CRYPTO_ERASE,
    "custom": WipeMode.CUSTOM,
}

class Step3Method(ctk.CTkFrame):
    def __init__(self, master, disk=None, crypto_profile=None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._disk    = disk
        self._profile = crypto_profile
        self._selected_key = None
        self._passes_var = ctk.IntVar(value=3)
        self._verify_var = ctk.IntVar(value=10)
        self._build()

    def update_disk(self, disk, profile):
        self._disk    = disk
        self._profile = profile
        for w in self.winfo_children(): w.destroy()
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text=t("wipe_mode_title"),
            font=FONT_TITLE, text_color=TEXT_PRIMARY).pack(pady=(24,4))

        dtype = getattr(self._disk,"disk_type","hdd") if self._disk else "hdd"
        is_removable = getattr(self._disk,"transport","") in ("usb","removable") if self._disk else False
        has_crypto   = getattr(self._profile,"has_crypto_option",False) if self._profile else False

        if is_removable:
            ctk.CTkLabel(self, text=f"⚠  {t('removable_warning')} — NIST Purge indisponible",
                font=FONT_SMALL, text_color=YELLOW_WARN).pack(pady=(0,4))

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
            scrollbar_button_color=BLUE_DARK,
            scrollbar_button_hover_color=BLUE_PRIMARY)
        scroll.pack(fill="both", expand=True, padx=24, pady=(4,0))

        self._radio_var = ctk.StringVar(value="")
        self._cards = {}

        for key, name_k, desc_k, compat_k, compatible_types, needs_crypto in MODES:
            # Disponibilité
            ok = dtype in compatible_types
            if needs_crypto and not has_crypto: ok = False
            if key == "purge" and is_removable: ok = False
            if not needs_crypto and key == "crypto": continue  # Masque si pas de chiffrement

            card = ctk.CTkFrame(scroll, fg_color=BG_CARD if ok else BG_INPUT,
                corner_radius=RADIUS, border_width=1,
                border_color=BORDER, cursor="hand2" if ok else "")
            card.pack(fill="x", pady=4)

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=16, pady=(12,4))

            rb = ctk.CTkRadioButton(top, text=t(name_k),
                variable=self._radio_var, value=key,
                font=FONT_HEADING,
                text_color=TEXT_PRIMARY if ok else TEXT_DIM,
                fg_color=BLUE_PRIMARY, hover_color=BLUE_LIGHT,
                state="normal" if ok else "disabled",
                command=lambda k=key: self._on_select(k))
            rb.pack(side="left")

            compat_lbl = ctk.CTkLabel(top, text=t(compat_k),
                font=FONT_SMALL, text_color=BLUE_LIGHT if ok else TEXT_DIM)
            compat_lbl.pack(side="right")

            ctk.CTkLabel(card, text=t(desc_k), font=FONT_SMALL,
                text_color=TEXT_SECOND if ok else TEXT_DIM,
                anchor="w", wraplength=640).pack(fill="x", padx=40, pady=(0,12))

            if ok:
                def _bind_card(widget, k=key, r=rb):
                    """Bind le clic sur le card ET tous ses enfants."""
                    widget.bind("<Button-1>", lambda e, _k=k, _r=r: (
                        self._radio_var.set(_k),
                        self._on_select(_k),
                    ))
                    for child in widget.winfo_children():
                        _bind_card(child, k, r)
                _bind_card(card)

            self._cards[key] = card

        # ── Custom passes ──
        self._custom_frame = ctk.CTkFrame(scroll, fg_color=BG_CARD,
            corner_radius=RADIUS, border_width=1, border_color=BORDER)
        ctk.CTkLabel(self._custom_frame, text=t("wipe_m5_passes"),
            font=FONT_BODY, text_color=TEXT_SECOND).pack(side="left", padx=16, pady=12)
        ctk.CTkSlider(self._custom_frame, from_=2, to=7, number_of_steps=5,
            variable=self._passes_var,
            button_color=BLUE_PRIMARY, button_hover_color=BLUE_LIGHT,
            progress_color=BLUE_DARK, width=180).pack(side="left", padx=8)
        self._passes_lbl = ctk.CTkLabel(self._custom_frame, text="3 passes",
            font=FONT_BODY, text_color=TEXT_PRIMARY, width=70)
        self._passes_lbl.pack(side="left", padx=4)
        self._passes_var.trace_add("write", lambda *_:
            self._passes_lbl.configure(text=f"{self._passes_var.get()} passes"))

        # ── Fin du scroll ──

        # ── Vérification (hors scroll — toujours visible) ──
        sep = ctk.CTkFrame(self, height=1, fg_color=BORDER)
        sep.pack(fill="x", padx=24, pady=(4,0))

        ver_frame = ctk.CTkFrame(self, fg_color=BG_CARD,
            corner_radius=RADIUS, border_width=1, border_color=BORDER)
        ver_frame.pack(fill="x", padx=24, pady=4)
        ctk.CTkLabel(ver_frame, text=t("verify_title"),
            font=FONT_BODY, text_color=TEXT_SECOND).pack(side="left", padx=16, pady=10)
        ctk.CTkSlider(ver_frame, from_=1, to=100, number_of_steps=99,
            variable=self._verify_var,
            button_color=BLUE_PRIMARY, button_hover_color=BLUE_LIGHT,
            progress_color=BLUE_DARK, width=180).pack(side="left", padx=8)
        self._verify_lbl = ctk.CTkLabel(ver_frame, text="10%",
            font=FONT_BODY, text_color=TEXT_PRIMARY, width=50)
        self._verify_lbl.pack(side="left", padx=4)
        self._verify_var.trace_add("write", lambda *_:
            self._verify_lbl.configure(text=f"{self._verify_var.get()}%"))

        self._err_lbl = ctk.CTkLabel(self, text="", font=FONT_SMALL,
            text_color=RED_DANGER)
        self._err_lbl.pack(pady=2)

    def _on_select(self, key):
        self._selected_key = key
        self._err_lbl.configure(text="")
        # Affiche/masque custom passes
        if key == "custom":
            self._custom_frame.pack(fill="x", pady=4, after=self._cards["custom"])
        else:
            if self._custom_frame.winfo_ismapped():
                self._custom_frame.pack_forget()

    def validate(self):
        if not self._selected_key:
            self._err_lbl.configure(text="Sélectionnez une méthode.")
            return False
        return True

    def get_config(self):
        return {
            "mode":          MODE_MAP.get(self._selected_key, WipeMode.ANSSI_P2),
            "mode_label":    t({"anssi1":"wipe_m1_name","anssi2":"wipe_m2_name",
                                "purge":"wipe_m3_name","crypto":"wipe_m4_name",
                                "custom":"wipe_m5_name"}.get(self._selected_key,"wipe_m2_name")),
            "custom_passes": self._passes_var.get(),
            "verify_pct":    self._verify_var.get(),
        }
