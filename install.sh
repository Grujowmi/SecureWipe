#!/usr/bin/env bash
# =============================================================================
# SecureWipe — install.sh
# Installation des dépendances Linux
# Usage : sudo bash install.sh
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║       SecureWipe — Installation          ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Vérification root ──
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}ERREUR : Ce script doit être exécuté en root.${NC}"
    echo "  → sudo bash install.sh"
    exit 1
fi

# ── Détection distro ──
if command -v apt-get &>/dev/null; then
    PKG_MANAGER="apt"
elif command -v dnf &>/dev/null; then
    PKG_MANAGER="dnf"
elif command -v yum &>/dev/null; then
    PKG_MANAGER="yum"
elif command -v pacman &>/dev/null; then
    PKG_MANAGER="pacman"
else
    echo -e "${YELLOW}⚠ Gestionnaire de paquets non détecté. Installation Python uniquement.${NC}"
    PKG_MANAGER="none"
fi

echo -e "  Gestionnaire de paquets : ${CYAN}${PKG_MANAGER}${NC}"
echo ""

# ── Outils système ──
install_sys_tools() {
    echo -e "${BOLD}[1/3] Installation des outils système...${NC}"

    PKGS_APT="python3 python3-pip hdparm nvme-cli smartmontools util-linux"
    PKGS_DNF="python3 python3-pip hdparm nvme-cli smartmontools util-linux"
    PKGS_PAC="python python-pip hdparm nvme-cli smartmontools util-linux"

    case $PKG_MANAGER in
        apt)
            apt-get update -qq
            apt-get install -y $PKGS_APT 2>/dev/null || \
                echo -e "  ${YELLOW}Certains paquets optionnels non disponibles (ignoré)${NC}"
            ;;
        dnf|yum)
            $PKG_MANAGER install -y $PKGS_DNF 2>/dev/null || true
            ;;
        pacman)
            pacman -Sy --noconfirm $PKGS_PAC 2>/dev/null || true
            ;;
        none)
            echo -e "  ${YELLOW}Ignoré (pas de gestionnaire de paquets)${NC}"
            ;;
    esac

    echo -e "  ${GREEN}✓${NC} Outils système"
}

# ── Python ──
check_python() {
    echo -e "${BOLD}[2/3] Vérification Python...${NC}"

    if command -v python3 &>/dev/null; then
        PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
        PY_MAJOR=$(echo $PY_VER | cut -d. -f1)
        PY_MINOR=$(echo $PY_VER | cut -d. -f2)

        if [[ $PY_MAJOR -ge 3 && $PY_MINOR -ge 10 ]]; then
            echo -e "  ${GREEN}✓${NC} Python ${PY_VER} (OK)"
        else
            echo -e "  ${YELLOW}⚠ Python ${PY_VER} — SecureWipe nécessite Python 3.10+${NC}"
            echo "  → Mettez à jour Python si des erreurs apparaissent."
        fi
    else
        echo -e "  ${RED}✗ Python3 non trouvé. Installez Python 3.10+${NC}"
        exit 1
    fi
}

# ── Dépendances Python ──
install_python_deps() {
    echo -e "${BOLD}[3/3] Installation des dépendances Python...${NC}"

    # Essaie pip3 standard puis --break-system-packages si nécessaire
    if python3 -m pip install -r "${SCRIPT_DIR}/requirements.txt" --quiet 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} Dépendances Python installées"
    elif python3 -m pip install -r "${SCRIPT_DIR}/requirements.txt" \
            --break-system-packages --quiet 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} Dépendances Python installées (--break-system-packages)"
    else
        # Fallback virtualenv
        echo -e "  ${YELLOW}Tentative via virtualenv...${NC}"
        python3 -m venv "${SCRIPT_DIR}/.venv"
        "${SCRIPT_DIR}/.venv/bin/pip" install -r "${SCRIPT_DIR}/requirements.txt" --quiet
        echo -e "  ${GREEN}✓${NC} Dépendances installées dans .venv"
        echo -e "  ${YELLOW}ℹ Pour utiliser le venv : source ${SCRIPT_DIR}/.venv/bin/activate${NC}"
    fi
}

# ── Permissions ──
set_permissions() {
    chmod +x "${SCRIPT_DIR}/securewipe.py"
    chmod +x "${SCRIPT_DIR}/install.sh"
    echo -e "  ${GREEN}✓${NC} Permissions définies"
}

# ── Vérification finale ──
verify_install() {
    echo ""
    echo -e "${BOLD}Vérification de l'installation :${NC}"

    for tool in python3 hdparm nvme smartctl dd shred lsblk; do
        if command -v $tool &>/dev/null; then
            echo -e "  ${GREEN}✓${NC} ${tool}"
        else
            echo -e "  ${YELLOW}✗${NC} ${tool} (optionnel)"
        fi
    done

    echo ""
    if python3 -c "import rich, reportlab, qrcode, PIL" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} Dépendances Python OK"
    else
        echo -e "  ${RED}✗ Dépendances Python manquantes — relancez install.sh${NC}"
        exit 1
    fi
}

# ── Main ──
install_sys_tools
echo ""
check_python
echo ""
install_python_deps
echo ""
set_permissions
verify_install

echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║   Installation terminée avec succès !    ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Lancement : ${CYAN}sudo python3 securewipe.py${NC}"
echo ""
