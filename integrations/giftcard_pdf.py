"""
Génération du bon cadeau Lymphatic Care en PDF — sans dépendance externe.

PDF 1.4 écrit à la main : format A5 paysage, polices standard (Helvetica,
Courier) en WinAnsiEncoding (accents français OK), logo JPEG embarqué tel quel
(DCTDecode). Si un fond d'image est fourni (export Canva en JPEG), il est posé
en pleine page sous le texte.
"""

from __future__ import annotations

import json
import os
import textwrap
import zlib

W, H = 595.28, 419.53  # A5 paysage, en points

VERT = (0x3A, 0x61, 0x55)
VERT_FONCE = (0x2B, 0x4A, 0x41)
SAUGE = (0x7A, 0xB5, 0x97)
CREME = (0xF5, 0xFA, 0xF0)
GRIS = (0x5A, 0x6B, 0x65)
BLANC = (0xFF, 0xFF, 0xFF)

# Fonds Canva : la photo occupe la partie gauche du bon (proportion de la largeur)
PHOTO_FRAC = 0.4835
# La zone blanche démarre un peu avant, pour masquer toute bordure du modèle
WHITE_FROM = 0.47


def _rgb(c):
    return " ".join(f"{v / 255:.3f}" for v in c)


def _enc(s: str) -> bytes:
    """Texte → octets WinAnsi échappés pour une chaîne PDF."""
    s = (s or "").replace("\r", " ").replace("\n", " ")
    b = s.encode("cp1252", errors="replace")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _jpeg_size(data: bytes) -> tuple[int, int, int]:
    """Largeur, hauteur, nombre de composantes d'un JPEG (lecture du SOF)."""
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            comps = data[i + 9]
            return w, h, comps
        seg_len = int.from_bytes(data[i + 2:i + 4], "big")
        i += 2 + seg_len
    raise ValueError("JPEG illisible")


DEFAULT_FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fonts")

# Police du logo Lymphatic Care (Josefin Sans), embarquée si présente ; sinon polices PDF standard.
_FONT_KEYS = {"F1": "regular", "F2": "bold", "F3": "italic", "F4": "bold"}
_TYPE1 = {"F1": "Helvetica", "F2": "Helvetica-Bold", "F3": "Helvetica-Oblique", "F4": "Courier-Bold"}


def _load_fonts(fonts_dir: str | None) -> dict | None:
    fonts_dir = fonts_dir or DEFAULT_FONTS_DIR
    metrics_path = os.path.join(fonts_dir, "josefin_metrics.json")
    if not os.path.exists(metrics_path):
        return None
    metrics = json.load(open(metrics_path))
    if not all(os.path.exists(os.path.join(fonts_dir, m["file"])) for m in metrics.values()):
        return None
    for m in metrics.values():
        m["data"] = open(os.path.join(fonts_dir, m["file"]), "rb").read()
    return metrics


_ACTIVE_FONTS: dict | None = None


def _approx_width(text: str, size: float, bold: bool = False, italic: bool = False) -> float:
    if _ACTIVE_FONTS:
        style = "bold" if bold else ("italic" if italic and "italic" in _ACTIVE_FONTS else "regular")
        widths = _ACTIVE_FONTS[style]["widths"]
        total = 0
        for b in (text or "").encode("cp1252", errors="replace"):
            total += widths[b - 32] if 32 <= b <= 255 else 500
        return total * size / 1000
    return len(text) * size * (0.56 if bold else 0.52)


class _Canvas:
    def __init__(self):
        self.ops: list[bytes] = []

    def rect(self, x, y, w, h, color):
        self.ops.append(f"{_rgb(color)} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f".encode())

    def rounded_border(self, x, y, w, h, color, width=0.8):
        self.ops.append(f"{_rgb(color)} RG {width} w {x:.2f} {y:.2f} {w:.2f} {h:.2f} re S".encode())

    def line(self, x1, y1, x2, y2, color, width=0.6):
        self.ops.append(f"{_rgb(color)} RG {width} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S".encode())

    def text(self, x, y, s, font="F1", size=11, color=VERT_FONCE, spacing=0.0):
        self.ops.append(
            b"BT /" + font.encode() + f" {size} Tf {_rgb(color)} rg {spacing:.2f} Tc {x:.2f} {y:.2f} Td (".encode()
            + _enc(s) + b") Tj ET"
        )

    def text_center(self, cx, y, s, font="F1", size=11, color=VERT_FONCE, spacing=0.0):
        w = _approx_width(s, size, bold=font in ("F2", "F4"), italic=font == "F3") + spacing * max(len(s) - 1, 0)
        self.text(cx - w / 2, y, s, font=font, size=size, color=color, spacing=spacing)

    def image(self, name, x, y, w, h, inset: float = 0.0):
        """Pose une image ; `inset` rogne ses bords (évite le liseré de compression JPEG)."""
        clip = ""
        if inset:
            clip = f"{x + inset:.2f} {y + inset:.2f} {w - 2 * inset:.2f} {h - 2 * inset:.2f} re W n "
        self.ops.append(f"q {clip}{w:.2f} 0 0 {h:.2f} {x:.2f} {y:.2f} cm /{name} Do Q".encode())

    def stream(self) -> bytes:
        return b"\n".join(self.ops)


def build_giftcard_pdf(
    *,
    soin: str,
    duree: str,
    beneficiaire: str,
    de_la_part_de: str,
    message: str,
    code: str,
    valable_jusqu_au: str,
    cabinet_ligne1: str,
    cabinet_ligne2: str,
    logo_path: str | None = None,
    background_path: str | None = None,
    fonts_dir: str | None = None,
    badge_path: str | None = None,
) -> bytes:
    global _ACTIVE_FONTS
    _ACTIVE_FONTS = _load_fonts(fonts_dir)
    images: dict[str, tuple[bytes, int, int, int]] = {}
    if background_path and os.path.exists(background_path):
        d = open(background_path, "rb").read()
        images["Bg"] = (d, *_jpeg_size(d))
    if logo_path and os.path.exists(logo_path):
        d = open(logo_path, "rb").read()
        images["Logo"] = (d, *_jpeg_size(d))
    badge_path = badge_path or (os.path.join(os.path.dirname(logo_path), "giftcard_logo_badge.jpg") if logo_path else None)
    if badge_path and os.path.exists(badge_path):
        d = open(badge_path, "rb").read()
        images["Badge"] = (d, *_jpeg_size(d))

    c = _Canvas()
    panel_w = 200
    if "Bg" in images:
        c.image("Bg", 0, 0, W, H)
        # Zone texte uniformément blanche, quel que soit le fond du modèle Canva
        c.rect(W * WHITE_FROM, 0, W - W * WHITE_FROM, H, BLANC)
    else:
        c.rect(0, 0, W, H, CREME)
        c.rect(0, 0, panel_w, H, SAUGE)
        if "Logo" in images:
            c.image("Logo", 16, H - 16 - 168, 168, 168, inset=6)
        # Bandeau gauche : texte blanc centré
        for i, (label, size, bold) in enumerate([
            ("DRAINAGE LYMPHATIQUE", 9, True),
            ("Soins manuels", 10, False),
            ("Soignants diplômés", 10, False),
        ]):
            tw = _approx_width(label, size, bold) + (len(label) * 0.8 if i == 0 else 0)
            c.text(max(12, (panel_w - tw) / 2), 150 - i * 16, label,
                   font="F2" if bold else "F1", size=size, color=BLANC,
                   spacing=0.8 if i == 0 else 0)
        c.line(40, 96, panel_w - 40, 96, BLANC, 0.5)
        c.text(max(12, (panel_w - _approx_width("lymphaticcare.fr", 10)) / 2), 76,
               "lymphaticcare.fr", font="F2", size=10, color=BLANC)

    if "Bg" in images:
        # Fond Canva : photo à gauche ; tout le texte est centré dans la zone blanche de droite
        zl = W * PHOTO_FRAC
        cx = (zl + W) / 2
        zone_w = W - zl - 44

        def _bloc(c, y):
            if "Badge" in images:
                logo = 66
                c.image("Badge", cx - logo / 2, y - logo, logo, logo)
                y -= logo + 22
            else:
                y -= 30
            c.text_center(cx, y, "BON CADEAU", font="F2", size=10, color=SAUGE, spacing=2.6)
            y -= 26

            title_size = 20
            while title_size > 15 and _approx_width(soin, title_size, True) > zone_w:
                title_size -= 0.5
            title_lines = [soin] if _approx_width(soin, title_size, True) <= zone_w else textwrap.wrap(soin, 20)
            for tl in title_lines[:2]:
                c.text_center(cx, y, tl, font="F2", size=title_size, color=VERT_FONCE)
                y -= title_size + 3
            if duree:
                c.text_center(cx, y + 2, duree, font="F1", size=10, color=GRIS)
                y -= 14

            c.line(cx - 16, y, cx + 16, y, SAUGE, 0.8)
            y -= 20
            c.text_center(cx, y, "OFFERT À", font="F2", size=7.5, color=GRIS, spacing=1.6)
            y -= 20
            c.text_center(cx, y, beneficiaire or "—", font="F2", size=16, color=VERT)
            y -= 16
            if de_la_part_de:
                c.text_center(cx, y, f"De la part de {de_la_part_de}", font="F1", size=10, color=GRIS)
                y -= 17
            if message:
                texte = f"« {message.strip()} »"
                nb = len(textwrap.wrap(texte, 46))
                largeur = 46 if nb <= 1 else min(46, -(-len(texte) // nb) + 6)  # lignes équilibrées
                for ml in textwrap.wrap(texte, largeur)[:3]:
                    c.text_center(cx, y, ml, font="F3", size=10, color=VERT_FONCE)
                    y -= 13.5
            return y

        class _Mesure:
            def __getattr__(self, _):
                return lambda *a, **k: None

        haut, bas = H - 16, 72  # zone disponible au-dessus du pied de bon
        hauteur = haut - _bloc(_Mesure(), haut)
        _bloc(c, haut - max(0, (haut - bas - hauteur) / 2))

        # Pied de bon : code et validité en petit, puis le cabinet
        c.line(zl + 30, 62, W - 30, 62, SAUGE, 0.5)
        c.text_center(cx, 48, f"Code {code}   ·   Valable jusqu'au {valable_jusqu_au}", font="F2", size=8, color=VERT_FONCE, spacing=0.3)
        c.text_center(cx, 36, cabinet_ligne1, font="F1", size=7, color=VERT)
        c.text_center(cx, 26, cabinet_ligne2, font="F1", size=6.8, color=GRIS)
        c.text_center(cx, 14, "Bon nominatif, à présenter au cabinet. Non remboursable, non échangeable.", font="F1", size=6, color=GRIS)
    else:
        x = panel_w + 28
        right = W - 28
        label_y, title_size, title_wrap, msg_wrap = H - 52, 24, 24, 62

        c.text(x, label_y, "BON CADEAU", font="F2", size=11, color=SAUGE, spacing=2.2)

        # Titre du soin (sur 1 ou 2 lignes)
        title_lines = textwrap.wrap(soin, title_wrap) or [soin]
        y = label_y - 34
        for tl in title_lines[:2]:
            c.text(x, y, tl, font="F2", size=title_size, color=VERT_FONCE)
            y -= title_size + 4
        if duree:
            c.text(x, y + 6, duree, font="F1", size=11, color=GRIS)
            y -= 14

        y -= 14
        c.text(x, y, "OFFERT À", font="F2", size=8, color=GRIS, spacing=1.2)
        y -= 20
        c.text(x, y, beneficiaire or "—", font="F2", size=17, color=VERT)
        y -= 18
        if de_la_part_de:
            c.text(x, y, f"De la part de {de_la_part_de}", font="F1", size=10.5, color=GRIS)
            y -= 16

        if message:
            y -= 4
            for ml in textwrap.wrap(f"« {message.strip()} »", msg_wrap)[:4]:
                c.text(x, y, ml, font="F3", size=10.5, color=VERT_FONCE)
                y -= 14

        # Encadré code + validité
        box_y, box_h = 62, 46
        c.rect(x, box_y, right - x, box_h, BLANC)
        c.rounded_border(x, box_y, right - x, box_h, SAUGE, 0.9)
        c.text(x + 14, box_y + 29, "CODE", font="F2", size=7.5, color=GRIS, spacing=1.2)
        vx = x + (right - x) / 2 + 16
        code_size = 14
        while code_size > 8 and _approx_width(code, code_size, True) + len(code) * 1.0 > vx - (x + 14) - 8:
            code_size -= 0.5
        c.text(x + 14, box_y + 11, code, font="F4", size=code_size, color=VERT_FONCE, spacing=1.0)
        c.text(vx, box_y + 29, "VALABLE JUSQU'AU", font="F2", size=7.5, color=GRIS, spacing=1.2)
        c.text(vx, box_y + 11, valable_jusqu_au, font="F2", size=13, color=VERT_FONCE)

        c.text(x, 44, cabinet_ligne1, font="F2", size=8.5, color=VERT)
        c.text(x, 32, cabinet_ligne2, font="F1", size=7.5, color=GRIS)
        c.text(x, 20, "Bon nominatif, à présenter au cabinet. Non remboursable, non échangeable contre des espèces.",
               font="F1", size=6.5, color=GRIS)

    content = zlib.compress(c.stream())

    # --- Assemblage des objets PDF ---
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)

    font_ids = {}
    if _ACTIVE_FONTS:
        embedded: dict[str, int] = {}
        for style, m in _ACTIVE_FONTS.items():
            ff = zlib.compress(m["data"])
            file_id = add(f"<< /Length {len(ff)} /Length1 {len(m['data'])} /Filter /FlateDecode >>\nstream\n".encode()
                          + ff + b"\nendstream")
            bbox = " ".join(str(v) for v in m["bbox"])
            flags = 32 + (64 if m["italic"] else 0)
            desc_id = add(
                f"<< /Type /FontDescriptor /FontName /{m['name']} /Flags {flags} /FontBBox [{bbox}] "
                f"/ItalicAngle {m['italic']} /Ascent {m['ascent']} /Descent {m['descent']} "
                f"/CapHeight {m['cap']} /StemV 80 /FontFile2 {file_id} 0 R >>".encode()
            )
            widths = " ".join(str(w) for w in m["widths"])
            embedded[style] = add(
                f"<< /Type /Font /Subtype /TrueType /BaseFont /{m['name']} /FirstChar 32 /LastChar 255 "
                f"/Widths [{widths}] /Encoding /WinAnsiEncoding /FontDescriptor {desc_id} 0 R >>".encode()
            )
        for key, style in _FONT_KEYS.items():
            font_ids[key] = embedded[style]
    else:
        for key, base in _TYPE1.items():
            font_ids[key] = add(
                f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} /Encoding /WinAnsiEncoding >>".encode()
            )
    img_ids = {}
    for name, (data, w, h, comps) in images.items():
        cs = "/DeviceRGB" if comps == 3 else ("/DeviceGray" if comps == 1 else "/DeviceCMYK")
        img_ids[name] = add(
            f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace {cs} "
            f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(data)} >>\nstream\n".encode()
            + data + b"\nendstream"
        )
    content_id = add(f"<< /Length {len(content)} /Filter /FlateDecode >>\nstream\n".encode()
                     + content + b"\nendstream")
    fonts = " ".join(f"/{k} {v} 0 R" for k, v in font_ids.items())
    xobjs = " ".join(f"/{k} {v} 0 R" for k, v in img_ids.items())
    resources = f"<< /Font << {fonts} >>" + (f" /XObject << {xobjs} >>" if xobjs else "") + " >>"
    pages_id = len(objs) + 2
    page_id = add(
        f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {W} {H}] "
        f"/Resources {resources} /Contents {content_id} 0 R >>".encode()
    )
    add(f"<< /Type /Pages /Kids [{page_id} 0 R] /Count 1 >>".encode())
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    info_id = add(b"<< /Title (Bon cadeau Lymphatic Care) /Producer (Lymphatic Care) >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root {catalog_id} 0 R /Info {info_id} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)
