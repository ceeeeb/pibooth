#!/usr/bin/env python3
"""Display network info, optionally edit pibooth settings, then exit.

A fullscreen window shows the active WiFi SSID and IP address. The operator
can either touch the screen to continue (pibooth launches) or tap the
"Paramètres" button to edit a small subset of pibooth settings (directory,
footer texts, text color, Nextcloud album name) in place in pibooth.cfg.
"""

import re
import time
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

CONFIG_PATH = Path.home() / ".config" / "pibooth" / "pibooth.cfg"

EDITABLE_FIELDS = [
    {"section": "GENERAL", "key": "directory", "label": "Dossier des photos", "type": "text"},
    {"section": "PICTURE", "key": "footer_text1", "label": "Texte pied 1", "type": "quoted"},
    {"section": "PICTURE", "key": "footer_text2", "label": "Texte pied 2", "type": "quoted"},
    {"section": "PICTURE", "key": "text_colors", "label": "Couleur des textes", "type": "color"},
    {"section": "NEXTCLOUD", "key": "album_name", "label": "Nom de l'album Nextcloud", "type": "text"},
]


def get_wifi_ssid() -> str:
    """Return the network the client radio is on, ignoring the guest hotspot."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            fields = _split_nmcli(line)
            # The hotspot on wlan1 is also an active 802-11-wireless connection:
            # matching on the device keeps it from being reported as "our" network.
            if len(fields) >= 3 and fields[1] == "802-11-wireless" \
                    and fields[2] == CLIENT_IFACE:
                return fields[0]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return "Non connecté"


def get_ip_address() -> str:
    try:
        result = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=5,
        )
        addresses = result.stdout.split()
        if addresses:
            return addresses[0]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return "Adresse IP indisponible"


def parse_color(raw: str) -> tuple[int, int, int]:
    nums = re.findall(r"\d+", raw)
    if len(nums) >= 3:
        return tuple(int(n) for n in nums[:3])
    return (255, 255, 255)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _build_palette_image(width: int, height: int, value: float):
    """Generate a hue×saturation palette image at the given brightness (0..1)."""
    import colorsys
    from PIL import Image
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    for x in range(width):
        h = x / max(1, width - 1)
        for y in range(height):
            s = 1.0 - (y / max(1, height - 1))
            r, g, b = colorsys.hsv_to_rgb(h, s, value)
            pixels[x, y] = (int(r * 255), int(g * 255), int(b * 255))
    return img


def pick_color_touch(parent: tk.Misc, initial: tuple[int, int, int]) -> tuple[int, int, int] | None:
    """Touch-friendly color picker with a HSV palette and a brightness slider."""
    from PIL import ImageTk

    dlg = tk.Toplevel(parent)
    dlg.title("Couleur")
    dlg.configure(bg="#1e1e1e")
    dlg.attributes("-fullscreen", True)
    dlg.transient(parent)
    dlg.grab_set()

    state = {"rgb": tuple(initial), "result": None, "value": 1.0,
             "palette_img": None, "tk_img": None}

    tk.Label(dlg, text="Choisir la couleur", font=("DejaVu Sans", 36, "bold"),
             fg="#9ad1ff", bg="#1e1e1e").pack(pady=(30, 15))

    top = tk.Frame(dlg, bg="#1e1e1e")
    top.pack(pady=(0, 15))

    preview = tk.Label(top, text="", bg=rgb_to_hex(state["rgb"]),
                       width=8, height=3, relief="solid", borderwidth=2)
    preview.pack(side="left", padx=20)

    value_label = tk.Label(top, text=f"RGB {state['rgb'][0]}, {state['rgb'][1]}, {state['rgb'][2]}",
                           font=("DejaVu Sans Mono", 26, "bold"),
                           fg="#ffffff", bg="#1e1e1e")
    value_label.pack(side="left", padx=20)

    PALETTE_W, PALETTE_H = 900, 360

    canvas = tk.Canvas(dlg, width=PALETTE_W, height=PALETTE_H,
                       bg="#1e1e1e", highlightthickness=0, cursor="cross")
    canvas.pack(pady=(0, 15))

    def refresh_preview():
        preview.configure(bg=rgb_to_hex(state["rgb"]))
        value_label.configure(text=f"RGB {state['rgb'][0]}, {state['rgb'][1]}, {state['rgb'][2]}")

    def repaint_palette():
        img = _build_palette_image(PALETTE_W, PALETTE_H, state["value"])
        state["palette_img"] = img
        state["tk_img"] = ImageTk.PhotoImage(img)
        canvas.delete("palette")
        canvas.create_image(0, 0, image=state["tk_img"], anchor="nw", tags="palette")

    def on_palette_tap(event):
        x = max(0, min(PALETTE_W - 1, event.x))
        y = max(0, min(PALETTE_H - 1, event.y))
        if state["palette_img"] is not None:
            state["rgb"] = state["palette_img"].getpixel((x, y))
            refresh_preview()

    canvas.bind("<Button-1>", on_palette_tap)
    canvas.bind("<B1-Motion>", on_palette_tap)

    bright_row = tk.Frame(dlg, bg="#1e1e1e")
    bright_row.pack(fill="x", padx=80, pady=(0, 10))
    tk.Label(bright_row, text="Luminosité", font=("DejaVu Sans", 24, "bold"),
             fg="#ffffff", bg="#1e1e1e", width=12, anchor="w").pack(side="left")

    def on_brightness(v):
        state["value"] = int(float(v)) / 100
        repaint_palette()

    tk.Scale(bright_row, from_=10, to=100, orient="horizontal",
             length=600, sliderlength=80, width=50, showvalue=False,
             bg="#1e1e1e", fg="#ffffff", troughcolor="#444444",
             highlightthickness=0, command=on_brightness).pack(side="left", fill="x", expand=True)

    btns = tk.Frame(dlg, bg="#1e1e1e")
    btns.pack(side="bottom", pady=30)

    def cancel():
        state["result"] = None
        dlg.destroy()

    def confirm():
        state["result"] = state["rgb"]
        dlg.destroy()

    tk.Button(btns, text="Annuler", font=("DejaVu Sans", 26),
              command=cancel, padx=40, pady=18, bg="#444444", fg="#ffffff",
              activebackground="#666666", activeforeground="#ffffff",
              borderwidth=0).pack(side="left", padx=20)
    tk.Button(btns, text="Valider", font=("DejaVu Sans", 26, "bold"),
              command=confirm, padx=40, pady=18, bg="#2d6cdf", fg="#ffffff",
              activebackground="#1f4fa8", activeforeground="#ffffff",
              borderwidth=0).pack(side="left", padx=20)

    repaint_palette()
    parent.wait_window(dlg)
    return state["result"]


class ConfigFile:
    """In-place editor preserving comments, blank lines, and unrelated values."""

    def __init__(self, path: Path):
        self.path = path
        self.lines = path.read_text(encoding="utf-8").splitlines()

    def _section_bounds(self, section: str) -> tuple[int, int]:
        header = f"[{section}]"
        start = next((i for i, l in enumerate(self.lines) if l.strip() == header), -1)
        if start == -1:
            raise KeyError(f"Section [{section}] introuvable")
        end = len(self.lines)
        for i in range(start + 1, len(self.lines)):
            if self.lines[i].lstrip().startswith("[") and self.lines[i].rstrip().endswith("]"):
                end = i
                break
        return start, end

    def get(self, section: str, key: str) -> str:
        start, end = self._section_bounds(section)
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*)$")
        for i in range(start + 1, end):
            m = pattern.match(self.lines[i])
            if m:
                return m.group(1)
        return ""

    def set(self, section: str, key: str, raw_value: str) -> None:
        start, end = self._section_bounds(section)
        pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*).*$")
        for i in range(start + 1, end):
            m = pattern.match(self.lines[i])
            if m:
                self.lines[i] = f"{m.group(1)}{raw_value}"
                return
        insert_at = end
        while insert_at > start + 1 and self.lines[insert_at - 1].strip() == "":
            insert_at -= 1
        self.lines.insert(insert_at, f"{key} = {raw_value}")

    def save(self) -> None:
        self.path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def open_settings_window(parent: tk.Tk) -> None:
    try:
        cfg = ConfigFile(CONFIG_PATH)
    except (OSError, KeyError) as exc:
        messagebox.showerror("Erreur", f"Impossible de lire la configuration:\n{exc}")
        return

    win = tk.Toplevel(parent)
    win.title("Paramètres pibooth")
    win.configure(bg="#1e1e1e")
    win.attributes("-fullscreen", True)
    win.config(cursor="arrow")

    container = tk.Frame(win, bg="#1e1e1e", padx=40, pady=30)
    container.pack(expand=True, fill="both")

    tk.Label(
        container, text="Paramètres pibooth",
        font=("DejaVu Sans", 36, "bold"), fg="#9ad1ff", bg="#1e1e1e",
    ).pack(pady=(0, 25))

    entries: dict[str, dict] = {}

    for field in EDITABLE_FIELDS:
        row = tk.Frame(container, bg="#1e1e1e")
        row.pack(fill="x", pady=8)

        tk.Label(
            row, text=field["label"], font=("DejaVu Sans", 22),
            fg="#ffffff", bg="#1e1e1e", width=22, anchor="w",
        ).pack(side="left")

        raw = cfg.get(field["section"], field["key"])
        state = {"field": field, "raw": raw}

        if field["type"] == "color":
            rgb = parse_color(raw)
            state["rgb"] = rgb
            swatch = tk.Label(
                row, text=f"  RGB {rgb[0]}, {rgb[1]}, {rgb[2]}  ",
                font=("DejaVu Sans Mono", 22), bg=rgb_to_hex(rgb),
                fg="#000000" if sum(rgb) > 380 else "#ffffff",
                padx=20, pady=8,
            )
            swatch.pack(side="left", fill="x", expand=True, padx=(0, 10))
            state["widget"] = swatch

            def pick_color(s=state):
                new_rgb = pick_color_touch(win, s["rgb"])
                if new_rgb is not None:
                    s["rgb"] = new_rgb
                    s["widget"].configure(
                        text=f"  RGB {new_rgb[0]}, {new_rgb[1]}, {new_rgb[2]}  ",
                        bg=rgb_to_hex(new_rgb),
                        fg="#000000" if sum(new_rgb) > 380 else "#ffffff",
                    )

            tk.Button(
                row, text="Choisir…", font=("DejaVu Sans", 18),
                command=pick_color, padx=15, pady=6,
            ).pack(side="left")
        else:
            value = raw
            if field["type"] == "quoted":
                value = raw.strip()
                if len(value) >= 2 and value[0] == value[-1] == '"':
                    value = value[1:-1]
            entry = tk.Entry(row, font=("DejaVu Sans", 22), bg="#2e2e2e", fg="#ffffff",
                             insertbackground="#ffffff")
            entry.insert(0, value)
            entry.pack(side="left", fill="x", expand=True)
            state["widget"] = entry

        entries[f"{field['section']}.{field['key']}"] = state

    buttons = tk.Frame(container, bg="#1e1e1e")
    buttons.pack(pady=(40, 0))

    def save_and_close():
        try:
            for state in entries.values():
                field = state["field"]
                if field["type"] == "color":
                    r, g, b = state["rgb"]
                    cfg.set(field["section"], field["key"], f"({r}, {g}, {b})")
                elif field["type"] == "quoted":
                    text = state["widget"].get()
                    cfg.set(field["section"], field["key"], f'"{text}"')
                else:
                    cfg.set(field["section"], field["key"], state["widget"].get())
            cfg.save()
        except OSError as exc:
            messagebox.showerror("Erreur", f"Échec de l'enregistrement:\n{exc}", parent=win)
            return
        win.destroy()
        parent.destroy()

    def cancel():
        win.destroy()

    tk.Button(
        buttons, text="Annuler", font=("DejaVu Sans", 22),
        command=cancel, padx=30, pady=12,
    ).pack(side="left", padx=10)

    tk.Button(
        buttons, text="Enregistrer et lancer pibooth", font=("DejaVu Sans", 22, "bold"),
        command=save_and_close, padx=30, pady=12, bg="#2d6cdf", fg="#ffffff",
        activebackground="#1f4fa8", activeforeground="#ffffff",
    ).pack(side="left", padx=10)


# The panel is touch-only: there is no physical keyboard, and squeekboard cannot
# help since the session runs on Xorg while squeekboard is Wayland-only. Text
# input therefore goes through the on-screen keyboard below.
KEYBOARD_LAYOUTS = {
    "lower": ["1234567890", "azertyuiop", "qsdfghjklm", "wxcvbn-_."],
    "upper": ["1234567890", "AZERTYUIOP", "QSDFGHJKLM", "WXCVBN-_."],
    "symbols": ["@#$%&*+=/", "!?:;,'\"()", "[]{}<>~^|", "\\`\u00b0\u20ac\u00a3\u00a7"],
}

# Guests connect the Pi's built-in radio only: wlan1 carries the hotspot and
# must never be taken over by a client connection.
CLIENT_IFACE = "wlan0"
MAX_SSID_BYTES = 32
MAX_PSK_LENGTH = 63
SCAN_SETTLE_SECONDS = 4


def ask_text_touch(parent, title, secret=False):
    """Prompt for a string with an on-screen keyboard. Returns None if cancelled."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg="#1e1e1e")
    win.attributes("-fullscreen", True)
    win.grab_set()

    result = {"value": None}
    state = {"layout": "lower"}

    tk.Label(win, text=title, font=("DejaVu Sans", 30, "bold"),
             fg="#9ad1ff", bg="#1e1e1e").pack(pady=(30, 15))

    entry = tk.Entry(win, font=("DejaVu Sans Mono", 34), bg="#2e2e2e", fg="#ffffff",
                     insertbackground="#ffffff", justify="center",
                     show="\u2022" if secret else "")
    entry.pack(fill="x", padx=80, ipady=12)
    entry.focus_set()

    keys_frame = tk.Frame(win, bg="#1e1e1e")
    keys_frame.pack(expand=True, fill="both", padx=40, pady=20)

    def type_char(char):
        entry.insert("end", char)

    def backspace():
        current = entry.get()
        entry.delete(0, "end")
        entry.insert(0, current[:-1])

    def toggle_case():
        state["layout"] = "upper" if state["layout"] == "lower" else "lower"
        render_keys()

    def toggle_symbols():
        state["layout"] = "lower" if state["layout"] == "symbols" else "symbols"
        render_keys()

    def render_keys():
        for child in keys_frame.winfo_children():
            child.destroy()
        for row_index, row in enumerate(KEYBOARD_LAYOUTS[state["layout"]]):
            row_frame = tk.Frame(keys_frame, bg="#1e1e1e")
            row_frame.pack(expand=True, fill="both", pady=3)
            for char in row:
                tk.Button(
                    row_frame, text=char, font=("DejaVu Sans", 26, "bold"),
                    bg="#3a3a3a", fg="#ffffff", activebackground="#5a5a5a",
                    borderwidth=0, command=lambda c=char: type_char(c),
                ).pack(side="left", expand=True, fill="both", padx=3)
            if row_index == len(KEYBOARD_LAYOUTS[state["layout"]]) - 1:
                tk.Button(
                    row_frame, text="\u232b", font=("DejaVu Sans", 26, "bold"),
                    bg="#7a3a3a", fg="#ffffff", activebackground="#9a5a5a",
                    borderwidth=0, command=backspace,
                ).pack(side="left", expand=True, fill="both", padx=3)

        bottom = tk.Frame(keys_frame, bg="#1e1e1e")
        bottom.pack(expand=True, fill="both", pady=3)
        for text, command, width in (
            ("\u21e7 Maj", toggle_case, 1),
            ("?123", toggle_symbols, 1),
            ("Espace", lambda: type_char(" "), 3),
        ):
            tk.Button(
                bottom, text=text, font=("DejaVu Sans", 24, "bold"),
                bg="#3a3a3a", fg="#ffffff", activebackground="#5a5a5a",
                borderwidth=0, command=command,
            ).pack(side="left", expand=True, fill="both", padx=3)

    def confirm():
        result["value"] = entry.get()
        win.destroy()

    def cancel():
        win.destroy()

    actions = tk.Frame(win, bg="#1e1e1e")
    actions.pack(side="bottom", fill="x", pady=(0, 30), padx=80)
    tk.Button(actions, text="Annuler", font=("DejaVu Sans", 26),
              bg="#444444", fg="#ffffff", borderwidth=0, command=cancel,
              padx=30, pady=14).pack(side="left", expand=True, fill="x", padx=10)
    tk.Button(actions, text="Valider", font=("DejaVu Sans", 26, "bold"),
              bg="#2d6cdf", fg="#ffffff", borderwidth=0, command=confirm,
              padx=30, pady=14).pack(side="left", expand=True, fill="x", padx=10)

    render_keys()
    win.wait_window()
    return result["value"]


def _split_nmcli(line):
    """Split an nmcli terse line, honouring its backslash-escaped colons."""
    return [field.replace("\\:", ":") for field in re.split(r"(?<!\\):", line)]


def hotspot_ssid():
    """Return the SSID our own guest hotspot broadcasts, or None."""
    result = subprocess.run(
        ["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", "pibooth-ap"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    return result.stdout.strip() or None


def scan_networks():
    """Return [(ssid, signal, secured)] seen on the client radio, strongest first.

    Our own hotspot is filtered out: the client radio sees it loud and clear, and
    offering it would invite the Pi to connect to itself.
    """
    # Without sudo the rescan is refused and the list comes straight from a stale
    # cache, showing only the network already associated. It also fails when a
    # scan is already running, which is harmless: the sleep still lets it finish.
    subprocess.run(
        ["sudo", "nmcli", "device", "wifi", "rescan", "ifname", CLIENT_IFACE],
        capture_output=True, check=False, timeout=30,
    )
    time.sleep(SCAN_SETTLE_SECONDS)
    result = subprocess.run(
        ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list",
         "ifname", CLIENT_IFACE],
        capture_output=True, text=True, check=False, timeout=20,
    )
    own_ssid = hotspot_ssid()
    networks, seen = [], set()
    for line in result.stdout.strip().splitlines():
        fields = _split_nmcli(line)
        if len(fields) < 3 or not fields[0] or fields[0] in seen:
            continue
        if own_ssid and fields[0] == own_ssid:
            continue
        seen.add(fields[0])
        try:
            signal = int(fields[1])
        except ValueError:
            signal = 0
        networks.append((fields[0], signal, bool(fields[2].strip())))
    networks.sort(key=lambda item: -item[1])
    return networks


def known_ssids():
    """Return the SSIDs NetworkManager already has a profile for."""
    result = subprocess.run(
        ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    names = set()
    for line in result.stdout.strip().splitlines():
        fields = _split_nmcli(line)
        if len(fields) >= 2 and fields[1] == "802-11-wireless":
            names.add(fields[0])
    return names


def connect_to_network(ssid, password):
    """Connect the client radio to ssid. Returns (success, message)."""
    # nmcli has no "--" end-of-options sentinel, so a leading dash would be
    # parsed as an option: reject those values instead of trying to escape them.
    if ssid.startswith("-") or password.startswith("-"):
        return False, "SSID et mot de passe ne peuvent pas commencer par un tiret."
    if len(ssid.encode("utf-8")) > MAX_SSID_BYTES:
        return False, f"SSID trop long (maximum {MAX_SSID_BYTES} octets)."
    if len(password) > MAX_PSK_LENGTH:
        return False, f"Mot de passe trop long (maximum {MAX_PSK_LENGTH} caracteres)."

    command = ["sudo", "nmcli", "device", "wifi", "connect", ssid,
               "ifname", CLIENT_IFACE]
    if password:
        command += ["password", password]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                check=False, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "Delai depasse lors de la connexion."
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def open_wifi_window(parent, on_connected):
    """Let the operator pick a Wi-Fi network and connect the client radio to it."""
    win = tk.Toplevel(parent)
    win.title("Choisir un reseau Wi-Fi")
    win.configure(bg="#1e1e1e")
    win.attributes("-fullscreen", True)
    win.grab_set()

    tk.Label(win, text="Choisir un réseau Wi-Fi", font=("DejaVu Sans", 36, "bold"),
             fg="#9ad1ff", bg="#1e1e1e").pack(pady=(30, 10))

    status = tk.Label(win, text="Recherche des réseaux…", font=("DejaVu Sans", 22),
                      fg="#cccccc", bg="#1e1e1e")
    status.pack(pady=(0, 15))

    list_frame = tk.Frame(win, bg="#1e1e1e")
    list_frame.pack(expand=True, fill="both", padx=60)

    def attempt(ssid, secured, is_known):
        password = ""
        if secured and not is_known:
            password = ask_text_touch(win, f"Mot de passe — {ssid}", secret=True)
            if password is None:
                return
        status.configure(text=f"Connexion à {ssid}…", fg="#ffd479")
        win.update_idletasks()
        success, message = connect_to_network(ssid, password)
        if success:
            status.configure(text=f"Connecté à {ssid}", fg="#7ddf7d")
            on_connected()
            win.after(1200, win.destroy)
        else:
            status.configure(text=f"Échec : {message[:80]}", fg="#ff8c8c")

    def render(networks):
        for child in list_frame.winfo_children():
            child.destroy()
        if not networks:
            tk.Label(list_frame, text="Aucun réseau détecté",
                     font=("DejaVu Sans", 24), fg="#ff8c8c", bg="#1e1e1e").pack(pady=30)
            return
        known = known_ssids()
        for ssid, signal, secured in networks[:7]:
            is_known = ssid in known
            label = f"{ssid}   {signal}%"
            if secured:
                label += "  \U0001f512"
            if is_known:
                label += "  \u2713 connu"
            tk.Button(
                list_frame, text=label, font=("DejaVu Sans", 26, "bold"),
                bg="#2e2e2e" if not is_known else "#2c4a2c", fg="#ffffff",
                activebackground="#4a4a4a", borderwidth=0, anchor="w", padx=30,
                command=lambda s=ssid, sec=secured, k=is_known: attempt(s, sec, k),
            ).pack(fill="x", pady=4, ipady=14)

    def refresh():
        status.configure(text="Recherche des réseaux…", fg="#cccccc")
        win.update_idletasks()
        try:
            networks = scan_networks()
        except (subprocess.SubprocessError, OSError) as exc:
            status.configure(text=f"Échec du scan : {exc}", fg="#ff8c8c")
            return
        status.configure(text=f"{len(networks)} réseau(x) détecté(s)", fg="#cccccc")
        render(networks)

    actions = tk.Frame(win, bg="#1e1e1e")
    actions.pack(side="bottom", fill="x", pady=(0, 40), padx=60)
    tk.Button(actions, text="Actualiser", font=("DejaVu Sans", 26),
              bg="#444444", fg="#ffffff", borderwidth=0, command=refresh,
              padx=30, pady=14).pack(side="left", expand=True, fill="x", padx=10)
    tk.Button(actions, text="Fermer", font=("DejaVu Sans", 26, "bold"),
              bg="#2d6cdf", fg="#ffffff", borderwidth=0, command=win.destroy,
              padx=30, pady=14).pack(side="left", expand=True, fill="x", padx=10)

    win.after(100, refresh)
    win.wait_window()


def build_window(ssid: str, ip: str) -> tk.Tk:
    root = tk.Tk()
    root.title("Informations réseau")
    root.configure(bg="#1e1e1e")
    root.attributes("-fullscreen", True)
    root.config(cursor="arrow")

    info = tk.Frame(root, bg="#1e1e1e")
    info.pack(expand=True, fill="both", pady=(80, 0))

    def add_label(parent, text, font, fg, pady):
        tk.Label(parent, text=text, font=font, fg=fg, bg="#1e1e1e").pack(pady=pady)

    add_label(info, "Réseau Wi-Fi", ("DejaVu Sans", 48, "bold"), "#9ad1ff", (0, 10))

    # Tapping the SSID opens the network picker: without it, an operator on a new
    # venue has no way in, since the web portal lives on an address the Pi does
    # not have yet.
    connected = ssid != "Non connecté"
    ssid_label = tk.Label(
        info, text=ssid if connected else "Non connecté  \u25b8 toucher pour choisir",
        font=("DejaVu Sans", 72 if connected else 44, "bold"),
        fg="#ffffff" if connected else "#ffd479", bg="#1e1e1e", cursor="arrow",
    )
    ssid_label.pack(pady=(0, 50))

    add_label(info, "Adresse IP", ("DejaVu Sans", 48, "bold"), "#9ad1ff", (0, 10))
    ip_label = tk.Label(info, text=ip, font=("DejaVu Sans Mono", 72, "bold"),
                        fg="#ffffff", bg="#1e1e1e")
    ip_label.pack(pady=(0, 50))

    def refresh_network_info():
        current_ssid = get_wifi_ssid()
        is_connected = current_ssid != "Non connecté"
        ssid_label.configure(
            text=current_ssid if is_connected else "Non connecté  \u25b8 toucher pour choisir",
            font=("DejaVu Sans", 72 if is_connected else 44, "bold"),
            fg="#ffffff" if is_connected else "#ffd479",
        )
        ip_label.configure(text=get_ip_address())

    def choose_wifi(_event=None):
        try:
            open_wifi_window(root, refresh_network_info)
        except Exception as exc:
            messagebox.showerror("Erreur", str(exc), parent=root)

    ssid_label.bind("<Button-1>", choose_wifi)

    def launch_pibooth():
        root.destroy()

    def open_settings():
        root.config(cursor="arrow")
        try:
            open_settings_window(root)
        except Exception as exc:
            messagebox.showerror("Erreur", str(exc), parent=root)

    action_bar = tk.Frame(root, bg="#1e1e1e")
    action_bar.pack(side="bottom", fill="x", pady=(0, 80))

    tk.Button(
        action_bar, text="Wi-Fi", font=("DejaVu Sans", 32, "bold"),
        bg="#444444", fg="#ffffff",
        activebackground="#666666", activeforeground="#ffffff",
        command=choose_wifi, padx=40, pady=20, borderwidth=0,
    ).pack(side="left", expand=True, fill="x", padx=(80, 10), ipady=15)

    tk.Button(
        action_bar, text="Paramètres", font=("DejaVu Sans", 32, "bold"),
        bg="#444444", fg="#ffffff",
        activebackground="#666666", activeforeground="#ffffff",
        command=open_settings, padx=40, pady=20, borderwidth=0,
    ).pack(side="left", expand=True, fill="x", padx=(10, 10), ipady=15)

    tk.Button(
        action_bar, text="Continuer ▶", font=("DejaVu Sans", 32, "bold"),
        bg="#2d6cdf", fg="#ffffff",
        activebackground="#1f4fa8", activeforeground="#ffffff",
        command=launch_pibooth, padx=40, pady=20, borderwidth=0,
    ).pack(side="left", expand=True, fill="x", padx=(10, 80), ipady=15)

    root.bind("<Key>", lambda e: launch_pibooth())
    root.focus_force()
    return root


def main() -> None:
    ssid = get_wifi_ssid()
    ip = get_ip_address()
    window = build_window(ssid, ip)
    window.mainloop()


if __name__ == "__main__":
    main()
