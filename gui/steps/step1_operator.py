"""SecureWipe GUI — Step 1 : Opérateur"""
import sys, socket, platform
from datetime import datetime
import customtkinter as ctk
from gui.theme import *
from core.i18n import t

class Step1Operator(ctk.CTkFrame):
    def __init__(self, master, lang="fr", **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._lang = lang
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text=t("prompt_operator_title"),
            font=FONT_TITLE, text_color=TEXT_PRIMARY).pack(pady=(32,4))
        ctk.CTkLabel(self, text="Renseignez vos informations avant de commencer.",
            font=FONT_BODY, text_color=TEXT_SECOND).pack(pady=(0,28))

        card = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS,
                            border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=60, pady=4)
        card.columnconfigure(1, weight=1)

        # Nom
        ctk.CTkLabel(card, text=t("prompt_operator_name"),
            font=FONT_BODY, text_color=TEXT_SECOND, anchor="w"
            ).grid(row=0, column=0, padx=(24,12), pady=(24,8), sticky="w")
        self._name_var = ctk.StringVar()
        self._name_entry = ctk.CTkEntry(card, textvariable=self._name_var,
            placeholder_text="Ex : Pierre Antoine", font=FONT_BODY,
            fg_color=BG_INPUT, border_color=BORDER, text_color=TEXT_PRIMARY,
            height=BTN_H, corner_radius=RADIUS_SM)
        self._name_entry.grid(row=0, column=1, padx=(0,24), pady=(24,8), sticky="ew")

        # Langue
        ctk.CTkLabel(card, text="Langue / Language",
            font=FONT_BODY, text_color=TEXT_SECOND, anchor="w"
            ).grid(row=1, column=0, padx=(24,12), pady=8, sticky="w")
        self._lang_var = ctk.StringVar(value="Français" if self._lang=="fr" else "English")
        ctk.CTkOptionMenu(card, values=["Français","English"],
            variable=self._lang_var, command=self._on_lang,
            fg_color=BLUE_DARK, button_color=BLUE_PRIMARY,
            button_hover_color=BLUE_LIGHT, text_color=TEXT_PRIMARY,
            font=FONT_BODY, height=BTN_H, corner_radius=RADIUS_SM
            ).grid(row=1, column=1, padx=(0,24), pady=8, sticky="w")

        self._err = ctk.CTkLabel(card, text="", font=FONT_SMALL, text_color=RED_DANGER)
        self._err.grid(row=2, column=0, columnspan=2, padx=24, pady=(0,16))
        self._name_entry.focus()
        # Entrée → valide et passe à l'étape suivante
        self._name_entry.bind("<Return>", lambda e: self.event_generate("<<NextStep>>"))

    def _on_lang(self, val):
        self._lang = "fr" if val == "Français" else "en"
        self.event_generate("<<LangChanged>>")

    def get_lang(self): return self._lang

    def validate(self):
        name = self._name_var.get().strip()
        if not name:
            self._err.configure(text="Ce champ est obligatoire.")
            self._name_entry.configure(border_color=RED_DANGER)
            return None
        self._err.configure(text="")
        self._name_entry.configure(border_color=BORDER)

        def _os():
            if sys.platform == "win32":
                try:
                    import winreg
                    k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
                    build = int(winreg.QueryValueEx(k,"CurrentBuildNumber")[0])
                    nm = winreg.QueryValueEx(k,"ProductName")[0]
                    ubr = winreg.QueryValueEx(k,"UBR")[0]
                    winreg.CloseKey(k)
                    if build >= 22000: nm = nm.replace("Windows 10","Windows 11")
                    return f"{nm} (Build {build}.{ubr})"
                except: return f"Windows {platform.version()}"
            try:
                with open("/etc/os-release") as f:
                    info = {k:v.strip('"') for line in f if "=" in line
                            for k,v in [line.strip().split("=",1)]}
                return info.get("PRETTY_NAME",platform.system())+f" {platform.machine()}"
            except: return platform.platform()

        return {"name":name,"org":"","machine":socket.gethostname(),
                "os":_os(),"datetime":datetime.now()}
