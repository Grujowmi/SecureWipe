# Changelog — SecureWipe

All notable changes to SecureWipe are documented here.

---

## [v2.0.0] — 2026-03-29

### Added
- `--test-disk FILE` CLI argument : inject a file as a fake disk for testing (Linux/WSL)
- `--mock` CLI argument : load fictional disks to test the UI without hardware
- `--help` with usage examples
- Post-wipe verification now active on **Windows** (direct read on `\\.\PhysicalDriveX`)
- Volume dismount sequence before writing on Windows (`FSCTL_LOCK_VOLUME` + `FSCTL_DISMOUNT_VOLUME`)
- Warning in final confirmation panel showing which drive letters will be disconnected
- NIST Purge automatically blocked on USB/removable disks with explicit message
- Improved removable disk detection: `Get-Disk.IsRemovable`, `BusType=USB`, model keywords
- Sequential report ID replaced by timestamp format `YYYYMMDDHHmm` (portable across machines)
- QR code note fully translated (was hardcoded in French)
- All verification detail messages moved to i18n (`verify_detail_zeros`, `verify_detail_write`, etc.)
- Author information: `Grujowmi <grujowmi@proton.me>`

### Fixed
- `DiskInfo` object not subscriptable in `confirm_wipe` (dict syntax → dot notation)
- Windows 11 detected as Windows 10 (now reads `CurrentBuildNumber` via `winreg`)
- NVMe detection on Windows: extended heuristics for Micron, Samsung (MZV), WD SN series
- `[Errno 9] Bad file descriptor` on Windows raw disk write → replaced `open()` with `ctypes CreateFile API`
- `WriteFile` error code 5 (Access Denied) → volume dismount sequence before writing
- PDF generating 3 pages instead of 2 (reduced spacers and padding)
- Double section title "Wipe Method Selection" in menu
- Rich markup `[/dim]` closing tag without matching open tag (crash)
- `_verify_wipe_linux` renamed to `_verify_wipe` (works on Windows too)
- All hardcoded French strings in `wipe_engine.py` and `ui.py` moved to i18n

### Changed
- `diskpart clean all` removed for overwrite modes → replaced by direct Python write via `ctypes CreateFile`
- `diskpart` now only used for NIST Purge on **internal** disks
- Reformat post-wipe feature removed (too fragile on Windows, not portable to Linux)
- Organisation field removed from operator prompt and PDF certificate
- `_get_next_report_id()` no longer requires a counter file

---

## [v2.0.0] — 2026-03-28

### Initial Release
- Bilingual interface FR/EN with automatic locale detection
- Automatic disk detection: HDD / SSD / NVMe (Linux via `lsblk`, Windows via `Get-PhysicalDisk`)
- Encryption detection: LUKS, BitLocker, SED
- Wipe modes: ANSSI Level 1, ANSSI Level 2 / NIST Clear, NIST Purge, Crypto Erase, Custom
- SSD/NVMe overwrite protection (overwrite modes blocked, only firmware erase allowed)
- System disk protection (cannot wipe the active OS disk)
- Real-time progress bar with MB/s and ETA
- Post-wipe verification by random sector sampling
- PDF certificate with watermark, QR code (SHA-256), sequential ID, logo
- Raw `.txt` log alongside PDF
- Multi-disk session (one certificate per disk)
- `--mock` mode for interface testing
- `install.sh` (Linux) and `install.ps1` (Windows) installers
- GPL v3 license
