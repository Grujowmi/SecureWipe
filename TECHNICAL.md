# SecureWipe — Documentation Technique / Technical Documentation

**FR [Français](#français) | EN [English](#english)**

---

## Français

### Pourquoi un simple formatage ne suffit pas ?

Quand vous supprimez un fichier ou formatez un disque, le système d'exploitation **retire uniquement le pointeur** vers les données — comme arracher l'index d'un livre sans en déchirer les pages. Les données restent physiquement présentes sur le disque et sont récupérables avec des outils spécialisés (TestDisk, PhotoRec, Recuva, etc.) en quelques minutes.

SecureWipe écrase les données réelles, rendant toute récupération impossible.

---

### Les 5 modes d'effacement

---

#### Mode 1 — ANSSI Palier 1 : 1 passe de zéros

**Ce que ça fait :**
Le programme écrit des `0x00` (octets nuls) sur chaque secteur du disque, de bout en bout, en une seule passe. Ensuite il lit 10% des secteurs au hasard pour vérifier qu'ils contiennent bien des zéros.

**Niveau de sécurité :** ⭐⭐⭐☆☆
**Vitesse :** Rapide (limitée par la vitesse du disque)
**Cas d'usage :** Réaffectation interne dans une même organisation. Un collaborateur reçoit le poste d'un autre.

**Ce que dit l'ANSSI :**
Ce niveau correspond au Palier 1 du guide ANSSI de destruction des données. Suffisant pour les transferts internes où le niveau de confiance entre les parties est établi.

**Limites :**
Un adversaire très déterminé disposant de matériel de laboratoire (microscope à force magnétique) pourrait théoriquement lire des traces résiduelles sur un HDD. En pratique, aucune attaque réelle n'a été documentée sur des disques modernes.

---

#### Mode 2 — ANSSI Palier 2 / NIST Clear : 1 passe aléatoire

**Ce que ça fait :**
Le programme écrit des données **pseudo-aléatoires cryptographiquement sûres** (`/dev/urandom` sur Linux, `secrets.token_bytes()` sur Windows) sur chaque secteur, en une seule passe. La vérification confirme que les données écrites ne sont pas uniformément nulles.

**Niveau de sécurité :** ⭐⭐⭐⭐☆
**Vitesse :** Légèrement plus lent que le Palier 1 (génération de l'aléatoire)
**Cas d'usage :** Transfert vers un tiers, revente de matériel, mise au rebut standard.

**Ce que disent l'ANSSI et le NIST :**
- ANSSI Palier 2 : obligatoire dès que le matériel quitte le périmètre de l'organisation.
- NIST SP 800-88 "Clear" : niveau recommandé pour les données de faible à moyenne sensibilité.

**Pourquoi une seule passe suffit sur un disque moderne ?**
Les disques fabriqués après les années 2000 ont une densité d'enregistrement tellement élevée que les traces résiduelles après une seule passe aléatoire sont indétectables même en laboratoire. La méthode Gutmann (35 passes) a été conçue pour les disques des années 1980–1990 et est aujourd'hui obsolète — son propre auteur le reconnaît.

---

#### Mode 3 — NIST Purge : ATA Secure Erase / NVMe Format

**Ce que ça fait :**
Au lieu d'écrire des données depuis le système d'exploitation, ce mode envoie une **commande directement au firmware du disque** pour qu'il s'efface lui-même.

**Sur HDD/SSD SATA** (`hdparm --security-erase`) :
Le firmware du disque réinitialise toutes ses cellules, y compris les zones **normalement inaccessibles depuis l'OS** : secteurs de remplacement (reallocated sectors), zones HPA (Host Protected Area), DCO (Device Configuration Overlay). Un effacement logiciel classique ne peut pas atteindre ces zones.

**Sur NVMe** (`nvme format --ses=2`) :
Le contrôleur NVMe régénère sa clé de chiffrement interne. Toutes les données existantes, y compris dans les zones réservées au wear-leveling, deviennent **mathématiquement inaccessibles** instantanément.

**Niveau de sécurité :** ⭐⭐⭐⭐⭐
**Vitesse :** Variable (quelques secondes à plusieurs heures selon le modèle)
**Cas d'usage :** Données sensibles, données de santé, données classifiées. Recommandé comme méthode par défaut sur tout SSD/NVMe.

**Ce que dit le NIST :**
NIST SP 800-88 "Purge" : niveau recommandé avant toute sortie du périmètre pour les données de haute sensibilité. Seul niveau garantissant l'effacement des zones inaccessibles.

**Pourquoi ce mode est indispensable pour les SSD ?**
Sur un SSD, l'écriture ne se fait jamais deux fois au même endroit physique (wear-leveling). Si vous écrasez un fichier, l'ancienne version reste sur une cellule différente que l'OS ne peut pas adresser. Seul le firmware connaît la localisation réelle de toutes les données — d'où l'obligation de passer par lui.

**Limite :**
Non disponible sur les disques connectés en USB. Le bridge USB-SATA bloque les commandes ATA Security dans 95% des cas — limitation hardware, pas logicielle.

---

#### Mode 4 — Crypto Erase : destruction de la clé de chiffrement

**Ce que ça fait :**
Si le disque est chiffré (LUKS sous Linux, BitLocker sous Windows, SED), SecureWipe détruit la **clé de chiffrement** plutôt que d'écraser les données.

**LUKS** (`cryptsetup erase`) :
Détruit tous les key slots. La clé maître AES-256 disparaît. Les données sur le disque restent physiquement présentes mais sont du bruit aléatoire sans la clé — récupération impossible, même en laboratoire.

**BitLocker** (`manage-bde -off`) :
Supprime la VMK (Volume Master Key) et la FVEK (Full Volume Encryption Key) du TPM et du disque.

**SED — Self-Encrypting Drive** (`hdparm --security-erase`) :
Le disque chiffre en permanence toutes ses données avec une clé interne. La commande Secure Erase régénère cette clé — l'intégralité du disque devient instantanément illisible.

**Niveau de sécurité :** ⭐⭐⭐⭐⭐
**Vitesse :** Instantané (quelques secondes)
**Cas d'usage :** Tout disque déjà chiffré. C'est la méthode la plus rapide et la plus sûre dès lors que le chiffrement est en place.

**Pourquoi c'est aussi sûr que NIST Purge ?**
La sécurité d'AES-256 est telle que sans la clé, casser le chiffrement par force brute prendrait plus de temps que l'âge de l'univers avec l'ensemble des supercalculateurs actuels.

**Recommandation :**
Chiffrez systématiquement vos disques dès leur mise en service (BitLocker, LUKS). L'effacement futur sera instantané et irréversible.

---

#### Mode 5 — Custom : N passes configurables

**Ce que ça fait :**
Effectue entre 2 et 7 passes alternant zéros et données aléatoires. Exemple pour 3 passes : zéros → aléatoire → zéros.

**Niveau de sécurité :** ⭐⭐⭐⭐☆ (identique au Palier 2 en pratique)
**Vitesse :** Lent (N fois plus long qu'une seule passe)
**Cas d'usage :** Conformité documentaire imposant plusieurs passes. Ou tranquillité d'esprit.

**Note importante :**
SecureWipe affiche un avertissement explicite : plusieurs passes n'apportent **aucun bénéfice de sécurité mesurable** sur les disques modernes par rapport à une seule passe aléatoire. Ce mode existe uniquement pour se conformer à des politiques internes qui l'exigent explicitement (ex: certaines normes bancaires ou de défense anciennes).

---

### Tableau récapitulatif

| Mode | Méthode | Support | Zones inaccessibles | Vitesse | Usage recommandé |
|------|---------|---------|---------------------|---------|-----------------|
| ANSSI Palier 1 | 1 passe zéros | HDD | Non | Rapide | Transfert interne |
| ANSSI Palier 2 | 1 passe aléatoire | HDD | Non | Rapide | Transfert externe, revente |
| NIST Purge | Firmware Secure Erase | HDD + SSD + NVMe | **Oui** | Variable | Données sensibles |
| Crypto Erase | Destruction clé AES | LUKS / BitLocker / SED | **Oui** | Instantané | Disque chiffré |
| Custom | N passes | HDD | Non | Lent | Conformité documentaire |

---

### Le certificat PDF

Après chaque effacement, SecureWipe génère un certificat incluant :

- **Identifiant unique** horodaté (format `YYYYMMDDHHmm`)
- **Informations du support** : modèle, numéro de série, capacité, type
- **Méthode appliquée** et référentiel de conformité
- **Résultat de la vérification** post-effacement
- **Durée de l'opération**
- **SHA-256 du certificat** + QR code vérifiable hors-ligne
- **Filigrane anti-falsification**

Ce document constitue une preuve de diligence raisonnable opposable lors d'un audit RGPD, HDS ou NIS2.

---
---

## English

### Why a simple format is not enough?

When you delete a file or format a disk, the operating system **only removes the pointer** to the data — like tearing out a book's index without destroying the pages. The data remains physically present on the disk and can be recovered with specialized tools (TestDisk, PhotoRec, Recuva, etc.) within minutes.

SecureWipe overwrites the actual data, making any recovery impossible.

---

### The 5 wipe modes

---

#### Mode 1 — ANSSI Level 1: 1 zero pass

**What it does:**
The program writes `0x00` (null bytes) over every sector of the disk from end to end in a single pass. It then reads 10% of sectors at random to verify they contain zeros.

**Security level:** ⭐⭐⭐☆☆
**Speed:** Fast (limited by disk speed)
**Use case:** Internal transfers within the same organization.

**ANSSI says:**
This corresponds to ANSSI Level 1 of the data destruction guide. Sufficient for internal transfers where the trust level between parties is established.

**Limits:**
A highly motivated adversary with laboratory equipment (magnetic force microscope) could theoretically read residual traces on an HDD. In practice, no real attack has been documented on modern drives.

---

#### Mode 2 — ANSSI Level 2 / NIST Clear: 1 random pass

**What it does:**
The program writes **cryptographically secure pseudo-random data** (`/dev/urandom` on Linux, `secrets.token_bytes()` on Windows) over every sector in a single pass. Verification confirms the written data is not uniformly null.

**Security level:** ⭐⭐⭐⭐☆
**Speed:** Slightly slower than Level 1 (random generation)
**Use case:** Transfer to a third party, hardware resale, standard disposal.

**ANSSI and NIST say:**
- ANSSI Level 2: mandatory when hardware leaves the organization's perimeter.
- NIST SP 800-88 "Clear": recommended level for low to medium sensitivity data.

**Why is one pass enough on modern drives?**
Drives manufactured after 2000 have such high recording density that residual traces after a single random pass are undetectable even in a lab. The Gutmann method (35 passes) was designed for 1980–1990 drives and is now obsolete — its own author acknowledges this.

---

#### Mode 3 — NIST Purge: ATA Secure Erase / NVMe Format

**What it does:**
Instead of writing data from the OS, this mode sends a **command directly to the disk firmware** to erase itself.

**On HDD/SSD SATA** (`hdparm --security-erase`):
The disk firmware resets all its cells, including zones **normally inaccessible from the OS**: replacement sectors (reallocated sectors), HPA (Host Protected Area), DCO (Device Configuration Overlay). Standard software erasure cannot reach these zones.

**On NVMe** (`nvme format --ses=2`):
The NVMe controller regenerates its internal encryption key. All existing data, including in wear-leveling reserved zones, becomes **mathematically inaccessible** instantly.

**Security level:** ⭐⭐⭐⭐⭐
**Speed:** Variable (seconds to several hours depending on model)
**Use case:** Sensitive data, health records, classified data. Recommended default method for all SSD/NVMe.

**NIST says:**
NIST SP 800-88 "Purge": recommended level before any perimeter exit for high sensitivity data. Only level guaranteeing erasure of inaccessible zones.

**Why is this mode essential for SSDs?**
On an SSD, writes never go to the same physical location twice (wear-leveling). If you overwrite a file, the old version remains on a different cell that the OS cannot address. Only the firmware knows the actual location of all data — hence the need to go through it.

**Limit:**
Not available on USB-connected drives. The USB-SATA bridge blocks ATA Security commands in 95% of cases — a hardware limitation, not a software one.

---

#### Mode 4 — Crypto Erase: encryption key destruction

**What it does:**
If the disk is encrypted (LUKS on Linux, BitLocker on Windows, SED), SecureWipe destroys the **encryption key** rather than overwriting the data.

**LUKS** (`cryptsetup erase`):
Destroys all key slots. The AES-256 master key disappears. Data on the disk remains physically present but is random noise without the key — recovery impossible, even in a lab.

**BitLocker** (`manage-bde -off`):
Removes the VMK (Volume Master Key) and FVEK (Full Volume Encryption Key) from the TPM and disk.

**SED — Self-Encrypting Drive** (`hdparm --security-erase`):
The drive permanently encrypts all its data with an internal key. The Secure Erase command regenerates this key — the entire disk becomes instantly unreadable.

**Security level:** ⭐⭐⭐⭐⭐
**Speed:** Instant (a few seconds)
**Use case:** Any already-encrypted disk. Fastest and most secure method when encryption is in place.

**Why is it as secure as NIST Purge?**
The security of AES-256 is such that without the key, brute-forcing the encryption would take longer than the age of the universe with all current supercomputers combined.

**Recommendation:**
Systematically encrypt your disks from day one (BitLocker, LUKS). Future erasure will be instant and irreversible.

---

#### Mode 5 — Custom: configurable N passes

**What it does:**
Performs between 2 and 7 passes alternating zeros and random data. Example for 3 passes: zeros → random → zeros.

**Security level:** ⭐⭐⭐⭐☆ (identical to Level 2 in practice)
**Speed:** Slow (N times longer than a single pass)
**Use case:** Documentary compliance requiring multiple passes, or peace of mind.

**Important note:**
SecureWipe displays an explicit warning: multiple passes provide **no measurable security benefit** on modern drives compared to a single random pass. This mode exists solely to comply with internal policies that explicitly require it.

---

### Summary table

| Mode | Method | Media | Inaccessible zones | Speed | Recommended use |
|------|--------|-------|--------------------|-------|----------------|
| ANSSI Level 1 | 1 zero pass | HDD | No | Fast | Internal transfer |
| ANSSI Level 2 | 1 random pass | HDD | No | Fast | External transfer, resale |
| NIST Purge | Firmware Secure Erase | HDD + SSD + NVMe | **Yes** | Variable | Sensitive data |
| Crypto Erase | AES key destruction | LUKS / BitLocker / SED | **Yes** | Instant | Encrypted disk |
| Custom | N passes | HDD | No | Slow | Documentary compliance |

---

### The PDF certificate

After each wipe, SecureWipe generates a certificate including:

- **Unique timestamped ID** (format `YYYYMMDDHHmm`)
- **Device information**: model, serial number, capacity, type
- **Method applied** and compliance standard
- **Post-wipe verification result**
- **Operation duration**
- **Certificate SHA-256** + offline-verifiable QR code
- **Anti-falsification watermark**

This document constitutes reasonable due diligence evidence for GDPR, HDS or NIS2 audits.
