# NovoPDF - aplicación sencilla para trabajar con documentos PDF
# Copyright (C) 2026 Jesús Punzón Suero
#
# Este programa es software libre: puede redistribuirlo y/o modificarlo bajo
# los términos de la Licencia Pública General Affero de GNU publicada por la
# Free Software Foundation, ya sea la versión 3 de la Licencia o (a su
# elección) cualquier versión posterior.
#
# Este programa se distribuye con la esperanza de que sea útil, pero SIN
# NINGUNA GARANTÍA; ni siquiera la garantía implícita de COMERCIABILIDAD o
# IDONEIDAD PARA UN PROPÓSITO PARTICULAR. Consulte la Licencia Pública
# General Affero de GNU (archivo LICENSE) para más detalles.
#
# Código fuente: https://github.com/JPS63/NovoPDF
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Elección de la fuente al editar texto.

Orden de preferencia para que el texto editado se parezca al original:
  1. La fuente incrustada en el propio PDF, si contiene todos los caracteres
     necesarios (en fuentes «subconjunto» solo se usan caracteres que ya
     aparecían en el documento, que son los únicos garantizados).
  2. La misma fuente instalada en el equipo (p. ej. Calibri, Arial, Garamond).
  3. Una fuente equivalente en métricas (Liberation, Carlito...) o del mismo
     estilo (con serifa, sin serifa, monoespaciada).
  4. Las fuentes estándar del PDF (Helvetica, Times, Courier).
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field

import pymupdf

_STYLE_WORDS = {"regular", "bold", "italic", "oblique", "bolditalic", "boldoblique", "book",
                "normal", "roman", "medium", "semibold", "demibold", "light", "black", "heavy",
                "condensed", "narrow", "it", "bd", "bi"}

# Nombres PDF habituales -> familia equivalente en Windows
SYNONYMS = {
    "helvetica": "arial", "arialmt": "arial", "helveticaneue": "arial", "helv": "arial",
    "swiss": "arial", "arimo": "arial", "liberationsans": "arial",
    "times": "timesnewroman", "timesroman": "timesnewroman", "timesnewromanps": "timesnewroman",
    "tiro": "timesnewroman", "tinos": "timesnewroman", "liberationserif": "timesnewroman",
    "courier": "couriernew", "couriernewps": "couriernew", "cour": "couriernew",
    "cousine": "couriernew", "liberationmono": "couriernew",
    "carlito": "calibri", "caladea": "cambria", "symbol": "symbol",
}
# Equivalentes con las mismas medidas (por si la original no está instalada)
METRIC_ALTS = {
    "arial": ["liberationsans", "arimo", "helvetica", "nimbussans"],
    "timesnewroman": ["liberationserif", "tinos", "nimbusroman"],
    "couriernew": ["liberationmono", "cousine", "nimbusmonops"],
    "calibri": ["carlito"], "cambria": ["caladea"],
    "arialnarrow": ["liberationsansnarrow"],
}
GENERIC = {"sans": ["arial", "liberationsans", "dejavusans", "segoeui", "verdana"],
           "serif": ["timesnewroman", "liberationserif", "dejavuserif", "georgia", "cambria"],
           "mono": ["couriernew", "liberationmono", "dejavusansmono", "consolas"]}
BASE14 = {("sans", False, False): "helv", ("sans", True, False): "hebo",
          ("sans", False, True): "heit", ("sans", True, True): "hebi",
          ("serif", False, False): "tiro", ("serif", True, False): "tibo",
          ("serif", False, True): "tiit", ("serif", True, True): "tibi",
          ("mono", False, False): "cour", ("mono", True, False): "cobo",
          ("mono", False, True): "coit", ("mono", True, True): "cobi"}

# Fuentes que se ofrecen siempre en el desplegable (si están instaladas)
COMMON = ["Arial", "Calibri", "Cambria", "Times New Roman", "Garamond", "Georgia", "Verdana",
          "Tahoma", "Segoe UI", "Century Gothic", "Book Antiqua", "Courier New", "Consolas",
          "Helvetica Neue", "Helvetica", "Times", "Avenir Next", "Palatino", "Baskerville", "Menlo"]


def key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _strip_style(k: str) -> str:
    changed = True
    while changed:
        changed = False
        for w in sorted(_STYLE_WORDS, key=len, reverse=True):
            if k.endswith(w) and len(k) > len(w) + 2:
                k = k[: -len(w)]
                changed = True
                break
    return k


def pdf_font_family(fontname: str) -> tuple[str, str]:
    """'ABCDEF+TimesNewRomanPS-BoldMT' -> ('timesnewroman', 'Times New Roman')."""
    n = fontname.split("+", 1)[-1]
    fam = re.split(r"[-,]", n, 1)[0]
    fam = re.sub(r"(PSMT|PS|MT)$", "", fam)
    disp = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", fam).strip() or n
    k = key(fam)
    known = set(SYNONYMS) | set(METRIC_ALTS) | {"timesnewroman", "arial", "couriernew"}
    if k not in known:
        k2 = _strip_style(k)
        if k2 != k:
            words = disp.split()
            while len(words) > 1 and key(words[-1]) in _STYLE_WORDS:
                words.pop()
            disp = " ".join(words)
        k = k2
    return k, disp


def name_style(fontname: str) -> tuple[bool, bool]:
    n = fontname.split("+", 1)[-1].lower()
    tail = re.split(r"[-,]", n, 1)[1] if re.search(r"[-,]", n) else n
    bold = any(w in tail for w in ("bold", "black", "heavy", "semibold", "demi"))
    italic = any(w in tail for w in ("italic", "oblique"))
    return bold, italic


def font_dirs() -> list[str]:
    if sys.platform.startswith("win"):
        dirs = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]
        la = os.environ.get("LOCALAPPDATA")
        if la:
            dirs.append(os.path.join(la, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        dirs = ["/System/Library/Fonts", "/Library/Fonts",
                os.path.expanduser("~/Library/Fonts"),
                # Fuentes de Microsoft Office para Mac (Calibri, Cambria...)
                "/Applications/Microsoft Word.app/Contents/Resources/DFonts",
                "/Applications/Microsoft PowerPoint.app/Contents/Resources/DFonts",
                "/Applications/Microsoft Excel.app/Contents/Resources/DFonts"]
    else:
        dirs = ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
                os.path.expanduser("~/.local/share/fonts")]
    return [d for d in dirs if os.path.isdir(d)]


# ---------------------------------------------------------------- índice de fuentes instaladas
_INDEX = None


def _read_faces(path: str):
    """Lee solo las tablas 'name', 'OS/2' y 'post' (rápido, sin cargar la fuente)."""
    import struct
    out = []
    with open(path, "rb") as fh:
        head = fh.read(12)
        if len(head) < 12:
            return out
        offsets = [0]
        if head[:4] == b"ttcf":
            n = struct.unpack(">I", head[8:12])[0]
            offsets = list(struct.unpack(f">{n}I", fh.read(4 * n)))[:4]
        for off in offsets:
            fh.seek(off)
            hdr = fh.read(12)
            if len(hdr) < 12:
                continue
            ntab = struct.unpack(">H", hdr[4:6])[0]
            tables = {}
            for _ in range(ntab):
                tag, _, toff, tlen = struct.unpack(">4sIII", fh.read(16))
                tables[tag] = (toff, tlen)
            if b"name" not in tables:
                continue
            toff, tlen = tables[b"name"]
            fh.seek(toff)
            data = fh.read(tlen)
            _, count, soff = struct.unpack(">HHH", data[:6])
            names = {}
            for k in range(count):
                pid, eid, lid, nid, ln, o = struct.unpack(">HHHHHH", data[6 + 12 * k: 18 + 12 * k])
                if nid not in (1, 2):
                    continue
                raw = data[soff + o: soff + o + ln]
                if pid == 3:
                    try:
                        s = raw.decode("utf-16-be")
                    except UnicodeDecodeError:
                        continue
                    prio = 0 if lid in (0x409, 0x0C0A, 0x040A) else 1
                elif pid == 1 and eid == 0:
                    s = raw.decode("latin-1")
                    prio = 2
                else:
                    continue
                if nid not in names or prio < names[nid][1]:
                    names[nid] = (s, prio)
            if 1 not in names:
                continue
            fam = names[1][0].strip()
            sub = names.get(2, ("Regular", 0))[0].lower()
            bold = "bold" in sub or "black" in sub
            italic = "italic" in sub or "oblique" in sub
            serif, mono = False, False
            if b"OS/2" in tables:
                fh.seek(tables[b"OS/2"][0])
                os2 = fh.read(78)
                if len(os2) >= 64:
                    sel = struct.unpack(">H", os2[62:64])[0]
                    bold = bold or bool(sel & 0x20)
                    italic = italic or bool(sel & 0x01)
                    panose = os2[32:42]
                    if panose[0] == 2:
                        serif = panose[1] in range(2, 11)
                        mono = panose[3] == 9
            if b"post" in tables:
                fh.seek(tables[b"post"][0] + 12)
                pf = fh.read(4)
                if len(pf) == 4 and struct.unpack(">I", pf)[0]:
                    mono = True
            out.append((fam, bold, italic, serif, mono, sub))
    return out


def _scan() -> dict:
    families: dict[str, dict] = {}
    seen_dirs = set()
    for d in font_dirs():
        if d in seen_dirs:
            continue
        seen_dirs.add(d)
        for root, _, files in os.walk(d):
            for f in files:
                if not f.lower().endswith((".ttf", ".otf", ".ttc")):
                    continue
                p = os.path.join(root, f)
                try:
                    faces = _read_faces(p)
                except Exception:
                    continue
                for fam, bold, italic, serif, mono, sub in faces[:1]:
                    k = key(fam)
                    e = families.setdefault(k, {"name": fam, "styles": {}, "serif": serif, "mono": mono})
                    sk = f"{int(bold)}{int(italic)}"
                    if sk not in e["styles"] or len(sub) < len(e["styles"][sk][1]):
                        e["styles"][sk] = [p, sub]
    return families


def _signature() -> str:
    parts = []
    for d in font_dirs():
        try:
            parts.append(f"{d}:{os.stat(d).st_mtime_ns}:{len(os.listdir(d))}")
        except OSError:
            pass
    return "|".join(parts)


def installed() -> dict:
    """Índice {clave familia: {...}} (se guarda en caché en la carpeta de datos)."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    from ..paths import data_dir
    cache = os.path.join(data_dir(), "fuentes.json")
    sig = _signature()
    try:
        with open(cache, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("sig") == sig:
            _INDEX = data["families"]
            return _INDEX
    except Exception:
        pass
    _INDEX = _scan()
    try:
        with open(cache, "w", encoding="utf-8") as fh:
            json.dump({"sig": sig, "families": _INDEX}, fh)
    except OSError:
        pass
    return _INDEX


def _system_file(fam_key: str, bold: bool, italic: bool) -> tuple[str, str] | None:
    e = installed().get(fam_key)
    if not e:
        return None
    st = e["styles"]
    for sk in (f"{int(bold)}{int(italic)}", f"{int(bold)}0", f"0{int(italic)}", "00"):
        if sk in st:
            return st[sk][0], e["name"]
    any_ = next(iter(st.values()), None)
    return (any_[0], e["name"]) if any_ else None


def common_families() -> list[str]:
    idx = installed()
    return [n for n in COMMON if key(n) in idx]


# ---------------------------------------------------------------- elección
@dataclass
class FontChoice:
    label: str                 # texto para el usuario
    kind: str                  # embedded | system | similar | standard
    family: str                # nombre de familia mostrado
    buffer: bytes | None = None
    path: str | None = None
    base14: str | None = None
    allowed: set = field(default_factory=set)   # caracteres válidos (fuentes subconjunto)

    def font(self) -> pymupdf.Font:
        if self.buffer is not None:
            return pymupdf.Font(fontbuffer=self.buffer)
        if self.path:
            return pymupdf.Font(fontfile=self.path)
        return pymupdf.Font(self.base14 or "helv")

    def covers(self, text: str) -> bool:
        chars = {c for c in text if not c.isspace()}
        if self.kind == "embedded" and self.allowed:
            return chars <= self.allowed
        try:
            f = self.font()
            return all(f.has_glyph(ord(c)) for c in chars)
        except Exception:
            return False


def _embedded(page: pymupdf.Page, span_font: str) -> FontChoice | None:
    doc = page.parent
    target = span_font.split("+", 1)[-1]
    tkey = pdf_font_family(target)[0]
    tstyle = name_style(target)
    for xref, ext, ftype, basefont, *_ in page.get_fonts(full=True):
        bf = basefont.split("+", 1)[-1]
        if bf != target and not (pdf_font_family(bf)[0] == tkey and name_style(bf) == tstyle):
            continue
        if ext not in ("ttf", "otf", "cff", "pfa", "pfb"):
            continue
        try:
            _, ext2, _, content = doc.extract_font(xref)
            if not content:
                continue
            f = pymupdf.Font(fontbuffer=content)
            if f.glyph_count < 2:
                continue
        except Exception:
            continue
        subset = "+" in basefont
        allowed = set()
        if subset:
            # Solo son seguros los caracteres que ya aparecen con esta fuente
            for p in doc:
                for b in p.get_text("dict", flags=0).get("blocks", []):
                    for ln in b.get("lines", []):
                        for s in ln.get("spans", []):
                            sf = s.get("font", "").split("+", 1)[-1]
                            if sf == target or (pdf_font_family(sf)[0] == tkey and name_style(sf) == tstyle):
                                allowed.update(c for c in s["text"] if not c.isspace())
            allowed = {c for c in allowed if f.has_glyph(ord(c))}
            if not allowed:
                continue
        fam = pdf_font_family(target)[1]
        return FontChoice(label=f"{fam} (la del documento)", kind="embedded", family=fam,
                          buffer=content, allowed=allowed)
    return None


def candidates(page: pymupdf.Page, span_font: str, kind: str, bold: bool, italic: bool,
               use_embedded: bool = True) -> list[FontChoice]:
    """Fuentes posibles para un texto, de mejor a peor parecido.
    use_embedded=False cuando el usuario cambia negrita/cursiva respecto al original."""
    out: list[FontChoice] = []
    emb = _embedded(page, span_font) if (span_font and use_embedded and page is not None) else None
    if emb:
        out.append(emb)
    fam_key, disp = pdf_font_family(span_font or "")
    exact = _system_file(fam_key, bold, italic) if fam_key else None
    if exact:
        out.append(FontChoice(label=f"{exact[1]} (instalada en el equipo)", kind="system",
                              family=exact[1], path=exact[0]))
    else:
        syn = SYNONYMS.get(fam_key, fam_key)
        alts = ([syn] if syn != fam_key else []) + METRIC_ALTS.get(syn, []) + GENERIC.get(kind, GENERIC["sans"])
        for a in alts:
            h = _system_file(a, bold, italic)
            if h:
                out.append(FontChoice(label=f"{h[1]} (la más parecida a «{disp}»)" if disp else h[1],
                                      kind="similar", family=h[1], path=h[0]))
                break
    b14 = BASE14.get((kind, bool(bold), bool(italic)), "helv")
    std = {"sans": "Helvetica", "serif": "Times", "mono": "Courier"}.get(kind, "Helvetica")
    out.append(FontChoice(label=f"{std} (estándar PDF)", kind="standard", family=std, base14=b14))
    return out


def choice_for_family(family: str, bold: bool, italic: bool) -> FontChoice | None:
    """Fuente instalada elegida por el usuario en el desplegable."""
    h = _system_file(key(family), bold, italic)
    if h:
        return FontChoice(label=h[1], kind="system", family=h[1], path=h[0])
    for kind, std, b in (("sans", "Helvetica", "helv"), ("serif", "Times", "tiro"), ("mono", "Courier", "cour")):
        if key(family) in (key(std), b):
            return FontChoice(label=std, kind="standard", family=std,
                              base14=BASE14[(kind, bool(bold), bool(italic))])
    return None


def best_for_text(choices: list[FontChoice], text: str) -> FontChoice:
    for c in choices:
        if c.covers(text):
            return c
    return choices[-1]
