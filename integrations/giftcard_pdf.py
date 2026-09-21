"""
Génération du bon cadeau Lymphatic Care en PDF — sans dépendance externe.

PDF 1.4 écrit à la main : format A5 paysage, polices standard (Helvetica,
Courier) en WinAnsiEncoding (accents français OK), logo JPEG embarqué tel quel
(DCTDecode). Si un fond d'image est fourni (export Canva en JPEG), il est posé
en pleine page sous le texte.
"""

from __future__ import annotations

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


def _approx_width(text: str, size: float, bold: bool = False) -> float:
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
) -> bytes:
    images: dict[str, tuple[bytes, int, int, int]] = {}
    if background_path and os.path.exists(background_path):
        d = open(background_path, "rb").read()
        images["Bg"] = (d, *_jpeg_size(d))
    if logo_path and os.path.exists(logo_path):
        d = open(logo_path, "rb").read()
        images["Logo"] = (d, *_jpeg_size(d))

    c = _Canvas()
    panel_w = 200
    if "Bg" in images:
        c.image("Bg", 0, 0, W, H)
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

    x = panel_w + 28 if "Bg" not in images else 60
    right = W - 28

    c.text(x, H - 52, "BON CADEAU", font="F2", size=11, color=SAUGE, spacing=2.2)

    # Titre du soin (sur 1 ou 2 lignes)
    title_lines = textwrap.wrap(soin, 24) or [soin]
    y = H - 88
    for tl in title_lines[:2]:
        c.text(x, y, tl, font="F2", size=24, color=VERT_FONCE)
        y -= 28
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
        for ml in textwrap.wrap(f"« {message.strip()} »", 62)[:4]:
            c.text(x, y, ml, font="F3", size=10.5, color=VERT_FONCE)
            y -= 14

    # Encadré code + validité
    box_y, box_h = 62, 46
    c.rect(x, box_y, right - x, box_h, BLANC)
    c.rounded_border(x, box_y, right - x, box_h, SAUGE, 0.9)
    c.text(x + 14, box_y + 29, "CODE", font="F2", size=7.5, color=GRIS, spacing=1.2)
    c.text(x + 14, box_y + 11, code, font="F4", size=15, color=VERT_FONCE)
    vx = x + (right - x) / 2 + 10
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
    for key, base in [("F1", "Helvetica"), ("F2", "Helvetica-Bold"),
                      ("F3", "Helvetica-Oblique"), ("F4", "Courier-Bold")]:
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
