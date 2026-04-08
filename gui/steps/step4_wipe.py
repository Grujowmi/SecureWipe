"""SecureWipe GUI — Step 4 : Effacement + résultat"""
import threading, time, os, sys
from pathlib import Path
import customtkinter as ctk
from gui.theme import *
from core.i18n import t
from core.wipe_engine import run_wipe, WipeMode, WipeStatus

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent

class Step4Wipe(ctk.CTkFrame):
    def __init__(self, master, app_ref, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._app      = app_ref
        self._result   = None
        self._running  = False
        self._total    = 0
        self._start_ts = 0
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text=t("confirm_title"),
            font=FONT_TITLE, text_color=TEXT_PRIMARY).pack(pady=(20,4))

        # ── Card récap ──
        self._recap = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS,
            border_width=1, border_color=RED_DANGER)
        self._recap.pack(fill="x", padx=60, pady=6)
        self._recap_lbl = ctk.CTkLabel(self._recap, text="",
            font=FONT_BODY, text_color=TEXT_PRIMARY,
            justify="left", anchor="w", wraplength=700)
        self._recap_lbl.pack(padx=20, pady=14, fill="x")

        self._warn_lbl = ctk.CTkLabel(self,
            text=t("confirm_warn").replace("[bold red]","").replace("[/bold red]",""),
            font=FONT_HEADING, text_color=RED_DANGER)
        self._warn_lbl.pack(pady=2)

        # ── Progression ──
        prog_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS,
            border_width=1, border_color=BORDER)
        prog_frame.pack(fill="x", padx=60, pady=6)

        self._bar = ctk.CTkProgressBar(prog_frame,
            progress_color=BLUE_PRIMARY, fg_color=BG_INPUT,
            corner_radius=RADIUS_SM, height=16)
        self._bar.pack(fill="x", padx=16, pady=(14,4))
        self._bar.set(0)

        stats_row = ctk.CTkFrame(prog_frame, fg_color="transparent")
        stats_row.pack(fill="x", padx=16, pady=(0,12))
        self._pct_lbl   = ctk.CTkLabel(stats_row, text="0%",
            font=FONT_HEADING, text_color=TEXT_PRIMARY, width=60)
        self._pct_lbl.pack(side="left")
        self._speed_lbl = ctk.CTkLabel(stats_row, text="",
            font=FONT_BODY, text_color=TEXT_SECOND)
        self._speed_lbl.pack(side="left", padx=16)
        self._eta_lbl   = ctk.CTkLabel(stats_row, text="",
            font=FONT_BODY, text_color=TEXT_SECOND)
        self._eta_lbl.pack(side="right")

        # ── Barre de vérification ──
        self._verify_frame = ctk.CTkFrame(self, fg_color=BG_CARD,
            corner_radius=RADIUS, border_width=1, border_color=BORDER)
        # Cachée jusqu'à la phase de vérification

        self._verify_bar = ctk.CTkProgressBar(self._verify_frame,
            progress_color=CYAN, fg_color=BG_INPUT,
            corner_radius=RADIUS_SM, height=10)
        self._verify_bar.pack(fill="x", padx=16, pady=(12,4))
        self._verify_bar.set(0)

        self._verify_lbl = ctk.CTkLabel(self._verify_frame, text="",
            font=FONT_SMALL, text_color=TEXT_SECOND)
        self._verify_lbl.pack(pady=(0,10))

        # ── Résultat ──
        self._result_lbl = ctk.CTkLabel(self, text="",
            font=FONT_HEADING, text_color=TEXT_PRIMARY, wraplength=700)
        self._result_lbl.pack(pady=6)

        # ── Boutons post-effacement ──
        self._post_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._post_frame.pack(pady=4)

        BTN_W = 220  # Même largeur pour tous les boutons post-effacement
        self._pdf_btn = ctk.CTkButton(self._post_frame,
            text="📄  Certificat PDF",
            font=FONT_BTN, height=BTN_H, width=BTN_W, corner_radius=RADIUS,
            fg_color=BLUE_PRIMARY, hover_color=BLUE_LIGHT,
            text_color="#ffffff", command=self._save_pdf)

        self._new_btn = ctk.CTkButton(self._post_frame,
            text="🔄  Autre disque",
            font=FONT_BTN, height=BTN_H, width=BTN_W, corner_radius=RADIUS,
            fg_color=BLUE_PRIMARY, hover_color=BLUE_LIGHT,
            text_color="#ffffff",
            command=lambda: self._app._show_step(1))

        self._quit_btn = ctk.CTkButton(self._post_frame,
            text="✕  Quitter",
            font=FONT_BTN, height=BTN_H, width=BTN_W, corner_radius=RADIUS,
            fg_color=RED_DANGER, hover_color=RED_LIGHT,
            text_color="#ffffff",
            command=self._app.quit_app)

        self._pdf_status = ctk.CTkLabel(self, text="",
            font=FONT_SMALL, text_color=GREEN_OK, wraplength=700)
        self._pdf_status.pack()

    def load_data(self, operator, disk, config, crypto_profile):
        self._operator = operator
        self._disk     = disk
        self._config   = config
        self._profile  = crypto_profile
        self._result   = None
        self._running  = False

        # Reset UI
        self._bar.set(0)
        self._bar.configure(progress_color=BLUE_PRIMARY, mode="determinate")
        self._pct_lbl.configure(text="0%")
        self._speed_lbl.configure(text="")
        self._eta_lbl.configure(text="")
        self._result_lbl.configure(text="")
        self._pdf_status.configure(text="")
        self._warn_lbl.pack()
        self._recap.configure(border_color=RED_DANGER)
        self._verify_frame.pack_forget()
        self._verify_bar.set(0)
        self._verify_lbl.configure(text="")
        for w in [self._pdf_btn, self._new_btn, self._quit_btn]:
            w.pack_forget()

        letters = getattr(disk,"drive_letters",[]) or getattr(disk,"mountpoints",[])
        vol_txt = f"\n  Volumes : {', '.join(letters)}" if letters else ""
        self._recap_lbl.configure(text=(
            f"  {t('report_device')} : {disk.device} — {disk.model}\n"
            f"  {t('report_size')}   : {disk.size_human}\n"
            f"  {t('report_method')} : {config['mode_label']}\n"
            f"  {t('report_verify_pct')} : {config['verify_pct']}%"
            + vol_txt
        ))

    def start_wipe(self):
        if self._running: return
        self._running  = True
        self._start_ts = time.time()
        self._total    = self._disk.size_bytes
        self._warn_lbl.pack_forget()
        self._result_lbl.configure(text=t("wipe_starting"))
        self._pct_lbl.configure(text="0%")

        def _progress_cb(done, total, elapsed):
            """
            Callback unique pour effacement ET vérification.
            elapsed == 0 → phase vérification (done=blocs faits, total=blocs total)
            elapsed  > 0 → phase effacement (done/total en bytes)
            """
            if total <= 0: return
            if elapsed == 0:
                # Phase vérification
                pct = min(done / total, 1.0)
                self.after(0, lambda p=pct, d=int(done), t2=int(total):
                    self._update_verify(p, d, t2))
            else:
                # Phase effacement
                pct       = min(done / total, 1.0)
                speed     = done / elapsed if elapsed > 0.1 else 0
                remaining = (total - done) / speed if speed > 0 else 0
                self.after(0, lambda p=pct, sp=speed, r=remaining:
                    self._update_progress(p, sp, r))

        def _worker():
            try:
                result = run_wipe(
                    disk           = self._disk,
                    mode           = self._config["mode"],
                    custom_passes  = self._config["custom_passes"],
                    verify_pct     = self._config["verify_pct"],
                    crypto_profile = self._profile,
                    gui_progress_cb= _progress_cb,
                )

            except Exception as e:
                from core.wipe_engine import WipeResult, WipeStatus, WipeMode
                result = WipeResult(
                    status=WipeStatus.FAILED, mode=self._config["mode"],
                    device=self._disk.device, error_msg=str(e))
            self.after(0, lambda: self._on_done(result))

        threading.Thread(target=_worker, daemon=True).start()

    def _update_progress(self, pct, speed_bps, remaining_sec):
        """Met à jour la barre et les stats — appelé dans le thread UI."""
        # Garde-fou : le widget peut avoir été détruit (changement de langue, navigation)
        try:
            if not self.winfo_exists() or not self._bar.winfo_exists():
                return
        except Exception:
            return
        self._bar.set(pct)
        self._pct_lbl.configure(text=f"{pct*100:.1f}%")

        # Vitesse
        if speed_bps >= 1024**3:
            speed_str = f"{speed_bps/1024**3:.1f} GB/s"
        elif speed_bps >= 1024**2:
            speed_str = f"{speed_bps/1024**2:.1f} MB/s"
        elif speed_bps >= 1024:
            speed_str = f"{speed_bps/1024:.0f} KB/s"
        else:
            speed_str = ""
        self._speed_lbl.configure(text=speed_str)

        # ETA
        if remaining_sec > 0 and pct > 0.001:
            h, rem = divmod(int(remaining_sec), 3600)
            m, s   = divmod(rem, 60)
            if h > 0:
                eta_str = f"ETA {h}h {m:02d}min"
            else:
                eta_str = f"ETA {m}:{s:02d}"
        else:
            eta_str = ""
        self._eta_lbl.configure(text=eta_str)

        # Temps écoulé dans le label résultat
        elapsed = int(time.time() - self._start_ts)
        h2, r2 = divmod(elapsed, 3600)
        m2, s2 = divmod(r2, 60)
        elapsed_str = f"{h2:02d}:{m2:02d}:{s2:02d}"
        self._result_lbl.configure(
            text=f"⠿ {t('wipe_progress_label')} — {elapsed_str}",
            text_color=TEXT_SECOND)

        # Quand effacement atteint 100%, prépare la barre de vérification
        if pct >= 1.0:
            self._bar.configure(progress_color=GREEN_OK)
            self._pct_lbl.configure(text="100%", text_color=GREEN_OK)
            self._speed_lbl.configure(text="")
            self._eta_lbl.configure(text="✓")
            if not self._verify_frame.winfo_ismapped():
                self._verify_frame.pack(fill="x", padx=60, pady=4,
                    before=self._result_lbl)
                self._verify_lbl.configure(
                    text=f"⠿ {t('wipe_verify_label')} ({self._config['verify_pct']}%)...")

    def _update_verify(self, pct, done, total):
        """Met à jour la barre de vérification."""
        try:
            if not self.winfo_exists(): return
        except Exception:
            return
        self._verify_bar.set(pct)
        self._verify_lbl.configure(
            text=f"{t('wipe_verify_label')} — {done}/{total} blocs  ({pct*100:.0f}%)")

    def _on_done(self, result):
        self._running = False
        self._result  = result

        # Widget peut avoir été détruit entre-temps
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return

        if result.status == WipeStatus.SUCCESS:
            self._bar.set(1.0)
            self._bar.configure(progress_color=GREEN_OK)
            self._recap.configure(border_color=GREEN_OK)
            self._pct_lbl.configure(text="100%", text_color=GREEN_OK)
            self._speed_lbl.configure(text="")
            self._eta_lbl.configure(text="✓ Terminé")

            verify_txt = ""
            if result.verify_ok is True:
                verify_txt = f"\n✓ Vérification OK ({result.verify_pct}%)"
            elif result.verify_ok is False:
                verify_txt = f"\n✗ Vérification échouée"

            dur = int(result.duration_sec)
            h,r = divmod(dur,3600); m,s = divmod(r,60)
            dur_str = f"{h}h {m:02d}min {s:02d}s" if h else f"{m}min {s:02d}s"

            self._result_lbl.configure(
                text=f"✓ Effacement réussi — {dur_str}" + verify_txt,
                text_color=GREEN_OK)

            # Boutons post-effacement
            self._pdf_btn.pack(side="left", padx=8, pady=4)
            self._new_btn.pack(side="left", padx=8, pady=4)
            self._quit_btn.pack(side="left", padx=8, pady=4)
        else:
            self._bar.set(0)
            self._bar.configure(progress_color=RED_DANGER)
            self._recap.configure(border_color=RED_DANGER)
            self._pct_lbl.configure(text="✗", text_color=RED_DANGER)
            err = result.error_msg or "Erreur inconnue"
            self._result_lbl.configure(text=f"✗ Échec : {err}", text_color=RED_DANGER)
            self._new_btn.pack(side="left", padx=8, pady=4)
            self._quit_btn.pack(side="left", padx=8, pady=4)

        self.event_generate("<<WipeDone>>")

    def _save_pdf(self):
        """Dialogue de sauvegarde + génération PDF."""
        import tkinter.filedialog as fd
        ts  = self._operator["datetime"].strftime("%Y-%m-%d_%H-%M-%S")
        sn  = self._disk.serial.replace("/","_").replace("\\","_")
        default_name = f"SW-{ts}_{sn}.pdf"

        out_path = fd.asksaveasfilename(
            title         = "Enregistrer le certificat",
            defaultextension=".pdf",
            filetypes     = [("PDF", "*.pdf"), ("Tous les fichiers", "*.*")],
            initialfile   = default_name,
            initialdir    = str(Path.home()),
        )
        if not out_path: return

        out_dir  = Path(out_path).parent
        out_name = Path(out_path).stem

        try:
            from cert.generator import generate_certificate
            pdf, txt = generate_certificate(
                operator   = self._operator,
                disk       = self._disk,
                result     = self._result,
                mode_label = self._config["mode_label"],
                verify_pct = self._config["verify_pct"],
                output_dir = out_dir,
                script_dir = SCRIPT_DIR,
            )
            # Renomme si nécessaire
            target = out_dir / (out_name + ".pdf")
            if pdf != target and pdf.exists():
                pdf.rename(target)
                pdf = target

            self._pdf_status.configure(
                text=f"✓ Certificat enregistré : {pdf}", text_color=GREEN_OK)

            # Ouvre le dossier dans l'explorateur
            import subprocess
            if sys.platform == "win32":
                subprocess.Popen(f'explorer /select,"{pdf}"')
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "--reveal", str(pdf)])
            else:
                subprocess.Popen(["xdg-open", str(pdf.parent)])
        except Exception as e:
            self._pdf_status.configure(
                text=f"✗ Erreur : {e}", text_color=RED_DANGER)

    def get_result(self): return self._result
