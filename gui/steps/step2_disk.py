"""SecureWipe GUI — Step 2 : Sélection du disque"""
import sys
import customtkinter as ctk
from gui.theme import *
from core.i18n import t

class Step2Disk(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._disks = []
        self._selected = None
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text=t("disk_title"),
            font=FONT_TITLE, text_color=TEXT_PRIMARY).pack(pady=(28,4))

        # Toolbar : bouton refresh
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=24, pady=(0,8))
        self._status_lbl = ctk.CTkLabel(toolbar, text=t("disk_scanning"),
            font=FONT_SMALL, text_color=TEXT_SECOND)
        self._status_lbl.pack(side="left")
        ctk.CTkButton(toolbar, text="↻  Actualiser",
            font=FONT_SMALL, height=28, corner_radius=RADIUS_SM,
            fg_color=BG_CARD, hover_color=BG_HOVER,
            text_color=TEXT_SECOND, border_width=1, border_color=BORDER,
            command=self.refresh).pack(side="right")

        # Zone défilante pour la liste de disques
        self._scroll = ctk.CTkScrollableFrame(self, fg_color=BG_CARD,
            corner_radius=RADIUS, border_width=1, border_color=BORDER,
            scrollbar_button_color=BLUE_DARK,
            scrollbar_button_hover_color=BLUE_PRIMARY)
        self._scroll.pack(fill="both", expand=True, padx=24, pady=(0,8))

        # En-tête colonnes
        hdr = ctk.CTkFrame(self._scroll, fg_color=BLUE_DARK, corner_radius=RADIUS_SM)
        hdr.pack(fill="x", padx=4, pady=(4,2))
        for txt, w in [("#", 40), (t("disk_col_dev"), 130), (t("disk_col_model"), 220),
                       (t("disk_col_serial"), 150), (t("disk_col_type"), 120),
                       (t("disk_col_size"), 90), (t("disk_col_enc"), 90)]:
            ctk.CTkLabel(hdr, text=txt, font=FONT_SMALL, text_color=TEXT_SECOND,
                width=w, anchor="w").pack(side="left", padx=6)

        self._rows_frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._rows_frame.pack(fill="both", expand=True)

        # Avertissement disque système
        self._warn_lbl = ctk.CTkLabel(self, text="", font=FONT_SMALL,
            text_color=YELLOW_WARN, wraplength=700)
        self._warn_lbl.pack(pady=4)

        self.refresh()

    def refresh(self):
        self._status_lbl.configure(text=t("disk_scanning"))
        self._selected = None
        for w in self._rows_frame.winfo_children():
            w.destroy()
        self._disks = self._load_disks()
        self._render_rows()
        n = len(self._disks)
        self._status_lbl.configure(
            text=f"{n} disque(s) détecté(s)" if n else t("disk_none_found"))

    def _load_disks(self):
        try:
            if sys.platform == "win32":
                from core.disk_windows import list_disks
            else:
                from core.disk_linux import list_disks
            return list_disks()
        except Exception as e:
            return []

    def _render_rows(self):
        TYPE_COLORS = {"hdd": YELLOW_WARN, "ssd": BLUE_LIGHT,
                       "nvme": CYAN, "unknown": TEXT_SECOND}
        ENC_COLORS  = {"luks": GREEN_OK, "bitlocker": GREEN_OK,
                       "sed": GREEN_OK, "none": TEXT_DIM}

        for i, disk in enumerate(self._disks):
            row = ctk.CTkFrame(self._rows_frame,
                fg_color=BG_INPUT if i%2==0 else BG_CARD,
                corner_radius=RADIUS_SM, cursor="hand2")
            row.pack(fill="x", padx=4, pady=1)
            row.bind("<Button-1>", lambda e, d=disk, r=row: self._select(d, r))

            bg = BG_INPUT if i%2==0 else BG_CARD
            num_color = RED_DANGER if disk.is_system else TEXT_SECOND
            sys_tag = " ⚠" if disk.is_system else ""

            for txt, w, color in [
                (str(i+1)+sys_tag,   40,  num_color),
                (disk.device,        130, TEXT_PRIMARY if not disk.is_system else RED_LIGHT),
                (disk.model[:28],    220, TEXT_PRIMARY),
                (disk.serial[:18],   150, TEXT_SECOND),
                (disk.disk_type.upper(), 120, TYPE_COLORS.get(disk.disk_type, TEXT_SECOND)),
                (disk.size_human,    90,  TEXT_SECOND),
                (disk.encryption.upper() if disk.encryption != "none" else "—",
                 90, ENC_COLORS.get(disk.encryption, TEXT_SECOND)),
            ]:
                lbl = ctk.CTkLabel(row, text=txt, font=FONT_SMALL,
                    text_color=color, width=w, anchor="w")
                lbl.pack(side="left", padx=6, pady=8)
                lbl.bind("<Button-1>", lambda e, d=disk, r=row: self._select(d, r))

    def _select(self, disk, row):
        if disk.is_system:
            self._warn_lbl.configure(
                text=f"⚠  {disk.device} est le disque système — impossible de l'effacer depuis l'OS actif.")
            return
        self._warn_lbl.configure(text="")
        self._selected = disk
        # Highlight
        for w in self._rows_frame.winfo_children():
            w.configure(fg_color=BG_CARD)
        for i, d in enumerate(self._disks):
            child = self._rows_frame.winfo_children()[i]
            if d is disk:
                child.configure(fg_color=BLUE_DARK)
                break

    def get_selected(self):
        return self._selected

    def validate(self):
        if not self._selected:
            self._warn_lbl.configure(text="Sélectionnez un disque avant de continuer.")
            return False
        return True
