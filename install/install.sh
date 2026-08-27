#!/usr/bin/env bash
#
# Installation complète du photobooth pibooth sur un Raspberry Pi neuf.
#
# Part d'une installation fraîche de Raspberry Pi OS Bookworm (64 bits, Desktop)
# et reconstruit l'intégralité du poste : application, plugins, services web,
# hotspot Wi-Fi invités, portail captif, affichage et démarrage automatique.
#
# Usage :
#   ./install.sh                 installation complète
#   ./install.sh --skip-network  tout sauf la configuration réseau
#   ./install.sh --only network  une seule étape (voir STEPS plus bas)
#
# Le script est idempotent : il peut être relancé sans dommage.

set -euo pipefail

# --- Configuration ---------------------------------------------------------
# Surchargeable par variable d'environnement : HOTSPOT_SSID=Fete ./install.sh

PIBOOTH_USER="${PIBOOTH_USER:-pi}"
PIBOOTH_HOME="${PIBOOTH_HOME:-/home/${PIBOOTH_USER}}"
VENV_DIR="${VENV_DIR:-${PIBOOTH_HOME}/pibooth/pibooth}"

HOTSPOT_SSID="${HOTSPOT_SSID:-Pibooth}"
HOTSPOT_PASSWORD="${HOTSPOT_PASSWORD:-}"
HOTSPOT_IFACE="${HOTSPOT_IFACE:-wlan1}"
HOTSPOT_CHANNEL="${HOTSPOT_CHANNEL:-11}"
HOTSPOT_ADDRESS="${HOTSPOT_ADDRESS:-10.42.0.1}"
CLIENT_IFACE="${CLIENT_IFACE:-wlan0}"
HOTSPOT_SHARE_INTERNET="${HOTSPOT_SHARE_INTERNET:-no}"

GALLERY_PORT="${GALLERY_PORT:-8081}"
WIFI_PORTAL_PORT="${WIFI_PORTAL_PORT:-8080}"
DISPLAY_ROTATE="${DISPLAY_ROTATE:-2}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FILES_DIR="${SCRIPT_DIR}/files"

STEPS=(packages python scripts services network display autostart config)

# --- Sortie ----------------------------------------------------------------

readonly RED=$'\033[0;31m' GREEN=$'\033[0;32m' YELLOW=$'\033[0;33m'
readonly BLUE=$'\033[0;34m' BOLD=$'\033[1m' RESET=$'\033[0m'

step()  { printf '\n%s==> %s%s\n' "${BOLD}${BLUE}" "$*" "${RESET}"; }
info()  { printf '    %s\n' "$*"; }
ok()    { printf '    %s✓%s %s\n' "${GREEN}" "${RESET}" "$*"; }
warn()  { printf '    %s!%s %s\n' "${YELLOW}" "${RESET}" "$*"; }
fail()  { printf '\n%sÉchec :%s %s\n' "${RED}${BOLD}" "${RESET}" "$*" >&2; exit 1; }

# Installe un fichier depuis files/ avec propriétaire et droits explicites.
install_file() {
    local source="$1" target="$2" owner="$3" mode="$4"
    [[ -f "${FILES_DIR}/${source}" ]] || fail "fichier manquant : files/${source}"
    sudo install -D -o "${owner%%:*}" -g "${owner##*:}" -m "${mode}" \
        "${FILES_DIR}/${source}" "${target}"
    ok "${target}"
}

# --- Vérifications ---------------------------------------------------------

check_prerequisites() {
    step "Vérifications préalables"

    [[ $EUID -ne 0 ]] || fail "à lancer en utilisateur normal (le script appelle sudo lui-même)"
    sudo -n true 2>/dev/null || sudo true || fail "sudo requis"

    id "${PIBOOTH_USER}" &>/dev/null || fail "utilisateur ${PIBOOTH_USER} inexistant"
    ok "utilisateur ${PIBOOTH_USER}"

    if [[ -f /proc/device-tree/model ]]; then
        ok "$(tr -d '\0' < /proc/device-tree/model)"
    else
        warn "matériel non Raspberry Pi : GPIO et caméra seront indisponibles"
    fi

    local codename
    codename="$(. /etc/os-release && echo "${VERSION_CODENAME:-inconnu}")"
    [[ "${codename}" == "bookworm" ]] || warn "testé sur Bookworm, détecté : ${codename}"

    curl -fsS --max-time 10 -o /dev/null https://pypi.org/simple/ \
        || fail "pas d'accès à PyPI — vérifier la connexion réseau"
    ok "accès réseau à PyPI"

    [[ -d "${FILES_DIR}" ]] || fail "répertoire files/ introuvable à côté du script"
}

# --- 1. Paquets système ----------------------------------------------------

step_packages() {
    step "Paquets système"

    # SDL2 : rendu pygame. gphoto2 : reflex USB. picamera2 : module caméra CSI.
    # CUPS : impression. nftables/NetworkManager : hotspot et portail captif.
    local packages=(
        git python3-venv python3-pip
        libsdl2-2.0-0 libsdl2-image-2.0-0 libsdl2-mixer-2.0-0
        libsdl2-ttf-2.0-0 libsdl2-gfx-1.0-0
        libgphoto2-6 libgphoto2-dev libgphoto2-port12
        python3-picamera2 python3-gpiozero python3-libgpiod
        python3-numpy python3-opencv python3-flask
        cups libcups2-dev
        network-manager nftables dnsmasq-base
        ffmpeg fonts-liberation2 fonts-noto-color-emoji
    )

    info "mise à jour de l'index APT…"
    sudo apt-get update -qq

    info "installation de ${#packages[@]} paquets (peut prendre plusieurs minutes)…"
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${packages[@]}"
    ok "paquets installés"

    # lpadmin : gestion CUPS. gpio/spi/i2c : accès matériel sans root.
    local groups=(lpadmin gpio spi i2c input video render dialout plugdev)
    for group in "${groups[@]}"; do
        getent group "${group}" >/dev/null || continue
        sudo adduser "${PIBOOTH_USER}" "${group}" >/dev/null 2>&1 || true
    done
    ok "utilisateur ${PIBOOTH_USER} ajouté aux groupes matériels"
}

# --- 2. Environnement Python ----------------------------------------------

step_python() {
    step "Environnement Python et application"

    # --system-site-packages : picamera2 et python3-opencv viennent d'APT,
    # ils ne s'installent pas correctement via pip sur Raspberry Pi OS.
    if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
        sudo -u "${PIBOOTH_USER}" python3 -m venv --system-site-packages "${VENV_DIR}"
        ok "venv créé : ${VENV_DIR}"
    else
        ok "venv déjà présent : ${VENV_DIR}"
    fi

    local pip="${VENV_DIR}/bin/pip"
    sudo -u "${PIBOOTH_USER}" "${pip}" install --quiet --upgrade pip setuptools wheel

    # Fork personnalisé publié sur PyPI, puis les plugins.
    local packages=(
        pibooth-ceeeeb
        pibooth-picamera2
        pibooth-nextcloud
        pibooth-pcloud
        pibooth-gallery-qr
        pibooth-extra-lights
        pibooth-forget-button
    )

    info "installation de pibooth et des ${#packages[@]} paquets Python…"
    sudo -u "${PIBOOTH_USER}" "${pip}" install --quiet --upgrade "${packages[@]}" \
        || fail "installation pip échouée"

    for package in "${packages[@]}"; do
        local version
        version="$("${pip}" show "${package}" 2>/dev/null | awk '/^Version:/{print $2}')"
        [[ -n "${version}" ]] && ok "${package} ${version}" || warn "${package} absent"
    done

    # rembg (remplacement de fond) télécharge son modèle au premier lancement.
    if "${pip}" show rembg &>/dev/null; then
        info "rembg présent : le modèle silueta (~45 Mo) sera téléchargé au 1er usage"
    fi
}

# --- 3. Scripts auxiliaires ------------------------------------------------

step_scripts() {
    step "Scripts auxiliaires"

    local owner="${PIBOOTH_USER}:${PIBOOTH_USER}"
    install_file gallery.py           "${PIBOOTH_HOME}/gallery.py"           "${owner}" 755
    install_file wifi-portal.py       "${PIBOOTH_HOME}/wifi-portal.py"       "${owner}" 755
    install_file captive-portal.py    "${PIBOOTH_HOME}/captive-portal.py"    "${owner}" 755
    install_file wifi-info-display.py "${PIBOOTH_HOME}/wifi-info-display.py" "${owner}" 755
    install_file start-pibooth.sh     "${PIBOOTH_HOME}/start-pibooth.sh"     "${owner}" 755

    # Le portail Wi-Fi pilote NetworkManager sans mot de passe.
    echo "${PIBOOTH_USER} ALL=(ALL) NOPASSWD: /usr/bin/nmcli" \
        | sudo tee /etc/sudoers.d/wifi-portal >/dev/null
    sudo chmod 440 /etc/sudoers.d/wifi-portal
    sudo visudo -cqf /etc/sudoers.d/wifi-portal || fail "sudoers wifi-portal invalide"
    ok "/etc/sudoers.d/wifi-portal"

    # Les adresses et ports diffèrent si la configuration a été surchargée.
    sudo sed -i \
        -e "s|^LISTEN_ADDRESS = .*|LISTEN_ADDRESS = \"${HOTSPOT_ADDRESS}\"|" \
        -e "s|^GALLERY_URL = .*|GALLERY_URL = \"http://${HOTSPOT_ADDRESS}:${GALLERY_PORT}/\"|" \
        "${PIBOOTH_HOME}/captive-portal.py"
    sudo sed -i "s|^CLIENT_IFACE = .*|CLIENT_IFACE = \"${CLIENT_IFACE}\"|" \
        "${PIBOOTH_HOME}/wifi-portal.py"
    ok "scripts adaptés à la configuration"
}

# --- 4. Services systemd ---------------------------------------------------

step_services() {
    step "Services systemd"

    install_file systemd/gallery.service        /etc/systemd/system/gallery.service        root:root 644
    install_file systemd/wifi-portal.service    /etc/systemd/system/wifi-portal.service    root:root 644
    install_file systemd/captive-portal.service /etc/systemd/system/captive-portal.service root:root 644

    sudo sed -i "s|^Environment=GALLERY_PORT=.*|Environment=GALLERY_PORT=${GALLERY_PORT}|" \
        /etc/systemd/system/gallery.service

    sudo systemctl daemon-reload

    local services=(gallery wifi-portal captive-portal)
    for service in "${services[@]}"; do
        sudo systemctl enable --now "${service}.service" >/dev/null 2>&1 || true
    done

    sleep 2
    for service in "${services[@]}"; do
        local state
        state="$(systemctl is-active "${service}.service" || true)"
        if [[ "${state}" == "active" ]]; then
            ok "${service} : ${state}"
        else
            # captive-portal ne démarre qu'une fois le hotspot monté.
            warn "${service} : ${state} (normal si le hotspot n'est pas encore actif)"
        fi
    done
}

# --- 5. Réseau : hotspot invités et portail captif -------------------------

step_network() {
    step "Configuration réseau"

    if [[ -z "${HOTSPOT_PASSWORD}" ]]; then
        warn "HOTSPOT_PASSWORD vide : hotspot non configuré"
        info "relancer avec : HOTSPOT_PASSWORD='motdepasse' ./install.sh --only network"
        return 0
    fi
    if (( ${#HOTSPOT_PASSWORD} < 8 )); then
        fail "HOTSPOT_PASSWORD doit faire au moins 8 caractères (contrainte WPA2)"
    fi

    # Sans épinglage, NetworkManager peut activer une connexion client sur
    # l'interface du hotspot et couper ce dernier.
    local pinned=0
    while IFS=: read -r name _; do
        [[ -n "${name}" ]] || continue
        sudo nmcli connection modify "${name}" connection.interface-name "${CLIENT_IFACE}" \
            2>/dev/null && ((pinned++)) || true
    done < <(nmcli -t -f NAME,TYPE connection show 2>/dev/null | grep ':802-11-wireless$')
    ok "${pinned} connexion(s) client épinglée(s) sur ${CLIENT_IFACE}"

    if [[ ! -d "/sys/class/net/${HOTSPOT_IFACE}" ]]; then
        warn "interface ${HOTSPOT_IFACE} absente : dongle USB non détecté"
        info "le hotspot exige une seconde radio (voir README, section matériel)"
        return 0
    fi

    if ! iw list 2>/dev/null | grep -q '\* AP$'; then
        warn "aucune radio n'annonce le mode AP — le hotspot risque de ne pas démarrer"
    fi

    sudo nmcli connection delete pibooth-ap >/dev/null 2>&1 || true
    sudo nmcli connection add type wifi ifname "${HOTSPOT_IFACE}" con-name pibooth-ap \
        autoconnect yes \
        ssid "${HOTSPOT_SSID}" \
        connection.interface-name "${HOTSPOT_IFACE}" \
        connection.autoconnect-priority 50 \
        802-11-wireless.mode ap \
        802-11-wireless.band bg \
        802-11-wireless.channel "${HOTSPOT_CHANNEL}" \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.proto rsn \
        wifi-sec.pairwise ccmp \
        wifi-sec.group ccmp \
        wifi-sec.psk "${HOTSPOT_PASSWORD}" \
        ipv4.method shared \
        ipv4.addresses "${HOTSPOT_ADDRESS}/24" \
        ipv6.method ignore >/dev/null
    ok "connexion pibooth-ap créée (SSID ${HOTSPOT_SSID}, canal ${HOTSPOT_CHANNEL})"

    # Portail captif : tout domaine résout vers le Pi, toute requête HTTP est
    # redirigée vers la galerie. dnsmasq est celui que NetworkManager lance déjà.
    sudo install -D -o root -g root -m 644 /dev/stdin \
        /etc/NetworkManager/dnsmasq-shared.d/captive-portal.conf << CONF
# Resolve every domain to the Pi so guest connectivity checks land on our redirector.
address=/#/${HOTSPOT_ADDRESS}

# RFC 8910: advertise the portal URL directly in the DHCP lease, so recent
# clients open it without waiting for their connectivity probe to fail.
dhcp-option=114,http://${HOTSPOT_ADDRESS}/
CONF
    ok "/etc/NetworkManager/dnsmasq-shared.d/captive-portal.conf"

    if [[ "${HOTSPOT_SHARE_INTERNET}" == "no" ]]; then
        install_file network/50-pibooth-ap-local \
            /etc/NetworkManager/dispatcher.d/50-pibooth-ap-local root:root 755
        sudo sed -i "s|^INTERFACE_NAME=.*|INTERFACE_NAME=${HOTSPOT_IFACE}|" \
            /etc/NetworkManager/dispatcher.d/50-pibooth-ap-local 2>/dev/null || true
        ok "accès invités restreint au réseau local (pas d'internet partagé)"
    else
        sudo rm -f /etc/NetworkManager/dispatcher.d/50-pibooth-ap-local
        ok "accès internet partagé avec les invités (NAT)"
    fi

    sudo nmcli connection up pibooth-ap >/dev/null 2>&1 \
        && ok "hotspot actif sur ${HOTSPOT_ADDRESS}" \
        || warn "hotspot non démarré — vérifier 'journalctl -u NetworkManager'"

    sudo systemctl restart captive-portal.service 2>/dev/null || true
}

# --- 6. Affichage ----------------------------------------------------------

step_display() {
    step "Affichage"

    local config_file=/boot/firmware/config.txt
    [[ -f "${config_file}" ]] || config_file=/boot/config.txt
    [[ -f "${config_file}" ]] || { warn "config.txt introuvable"; return 0; }

    # L'écran du photobooth est monté à l'envers : rotation par le firmware.
    if grep -q "^display_hdmi_rotate=" "${config_file}"; then
        sudo sed -i "s/^display_hdmi_rotate=.*/display_hdmi_rotate=${DISPLAY_ROTATE}/" "${config_file}"
    else
        echo "display_hdmi_rotate=${DISPLAY_ROTATE}" | sudo tee -a "${config_file}" >/dev/null
    fi
    ok "rotation écran : ${DISPLAY_ROTATE} (redémarrage requis)"

    # Mémoire GPU suffisante pour l'aperçu caméra plein écran.
    if ! grep -q "^gpu_mem=" "${config_file}"; then
        echo "gpu_mem=128" | sudo tee -a "${config_file}" >/dev/null
    fi
    ok "gpu_mem=128"

    apply_touch_flip
}

# L'écran est monté à l'envers : le firmware retourne l'affichage, mais SDL lit
# le tactile en coordonnées brutes, non pivotées. Le paquet publié sur PyPI ne
# porte pas ce retournement, propre à ce montage, d'où ce correctif appliqué
# après installation. Sans lui, chaque appui atterrit à l'opposé de la cible.
apply_touch_flip() {
    local straight='finger_pos = (event.x * display_size[0], event.y * display_size[1])'
    local flipped='finger_pos = ((1 - event.x) * display_size[0], (1 - event.y) * display_size[1])'

    local package_dir
    package_dir="$("${VENV_DIR}/bin/python" -c \
        'import os, pibooth; print(os.path.dirname(pibooth.__file__))' 2>/dev/null)" || {
        warn "pibooth introuvable dans le venv : retournement tactile non appliqué"
        return 0
    }
    local utils="${package_dir}/utils.py"

    if [[ "${DISPLAY_ROTATE}" != "2" ]]; then
        info "rotation ${DISPLAY_ROTATE} : retournement tactile non applicable"
        return 0
    fi

    if grep -qF "${flipped}" "${utils}"; then
        ok "retournement tactile déjà appliqué"
        return 0
    fi
    if ! grep -qF "${straight}" "${utils}"; then
        warn "motif tactile introuvable dans ${utils}"
        info "vérifier get_event_pos() si le tactile répond à l'envers"
        return 0
    fi

    sudo python3 - "${utils}" "${straight}" "${flipped}" << 'PATCH'
import sys

path, straight, flipped = sys.argv[1], sys.argv[2], sys.argv[3]
source = open(path, encoding="utf-8").read()
assert source.count(straight) == 1, "motif absent ou ambigu"
open(path, "w", encoding="utf-8").write(source.replace(straight, flipped))
PATCH
    ok "retournement tactile appliqué (${utils})"
}

# --- 7. Démarrage automatique ---------------------------------------------

step_autostart() {
    step "Démarrage automatique"

    local autostart_dir="${PIBOOTH_HOME}/.config/autostart"
    sudo -u "${PIBOOTH_USER}" mkdir -p "${autostart_dir}"
    install_file autostart/pibooth.desktop "${autostart_dir}/pibooth.desktop" \
        "${PIBOOTH_USER}:${PIBOOTH_USER}" 644

    info "pibooth démarre avec la session graphique via start-pibooth.sh"
}

# --- 8. Configuration pibooth ---------------------------------------------

step_config() {
    step "Configuration pibooth"

    local config_dir="${PIBOOTH_HOME}/.config/pibooth"
    local config_file="${config_dir}/pibooth.cfg"

    sudo -u "${PIBOOTH_USER}" mkdir -p "${config_dir}"

    if [[ -f "${config_file}" ]]; then
        warn "configuration existante conservée : ${config_file}"
        info "modèle de référence : ${FILES_DIR}/pibooth.cfg.template"
    else
        install_file pibooth.cfg.template "${config_file}" \
            "${PIBOOTH_USER}:${PIBOOTH_USER}" 600
        warn "identifiants Nextcloud et pCloud à renseigner (champs A_RENSEIGNER)"
        info "éditer avec : nano ${config_file}"
    fi

    local pictures_dir="${PIBOOTH_HOME}/Pictures/pibooth"
    sudo -u "${PIBOOTH_USER}" mkdir -p "${pictures_dir}"
    ok "répertoire photos : ${pictures_dir}"
}

# --- Résumé ----------------------------------------------------------------

print_summary() {
    local ip
    ip="$(hostname -I | awk '{print $1}')"

    cat << SUMMARY

${BOLD}${GREEN}Installation terminée.${RESET}

  Galerie locale      http://${ip}:${GALLERY_PORT}/
  Portail Wi-Fi       http://${ip}:${WIFI_PORTAL_PORT}/
  Hotspot invités     ${HOTSPOT_SSID} → http://${HOTSPOT_ADDRESS}:${GALLERY_PORT}/

${BOLD}À faire avant utilisation :${RESET}

  1. Renseigner les identifiants Nextcloud / pCloud :
       nano ${PIBOOTH_HOME}/.config/pibooth/pibooth.cfg
  2. Configurer l'imprimante si présente :
       ${VENV_DIR}/bin/pibooth-printcfg
  3. Redémarrer pour appliquer la rotation d'écran :
       sudo reboot

${BOLD}Vérification après redémarrage :${RESET}

       ${VENV_DIR}/bin/pibooth-diag
       systemctl status gallery wifi-portal captive-portal

SUMMARY
}

# --- Point d'entrée --------------------------------------------------------

main() {
    local only="" skip=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --only)        only="$2"; shift 2 ;;
            --skip-network) skip="network"; shift ;;
            --help|-h)
                sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
                exit 0 ;;
            *) fail "option inconnue : $1 (voir --help)" ;;
        esac
    done

    check_prerequisites

    for step_name in "${STEPS[@]}"; do
        [[ -n "${only}" && "${only}" != "${step_name}" ]] && continue
        [[ "${skip}" == "${step_name}" ]] && { warn "étape ${step_name} ignorée"; continue; }
        "step_${step_name}"
    done

    [[ -z "${only}" ]] && print_summary
    return 0
}

main "$@"
