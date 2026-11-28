#!/usr/bin/env python3
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

"""Construye NovoPDF.app para macOS (Apple Silicon y/o Intel) desde Linux.

Estructura del paquete:
  NovoPDF.app/Contents/
    Info.plist
    MacOS/NovoPDF            lanzador (bash)  ->  exec MacOS/python3
    MacOS/python3            intérprete de python-build-standalone
    lib/libpython3.12.dylib  (@executable_path/../lib)
    lib/python3.12/          biblioteca estándar + site-packages
    Resources/app/           código de NovoPDF
    Resources/recursos/      datos del OCR
    Resources/NovoPDF.icns

Uso: build_macos.py [arm64] [x86_64]
"""
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
MB = os.environ.get("MAC_BUILD", "/home/claude/mac_build")
OUT = os.path.join(HERE, "out_mac")
import re
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', open(os.path.join(SRC, "novopdf", "__init__.py")).read()).group(1)
PBS = {"arm64": "aarch64", "x86_64": "x86_64"}
WINE_PY = os.environ.get("WINE_PY", os.path.join(HERE, "out", "NovoPDF", "runtime", "python.exe"))

LAUNCHER = """#!/bin/bash
# NovoPDF para macOS: lanzador del paquete .app
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTENTS="$(dirname "$HERE")"
export NOVOPDF_HOME="$CONTENTS/Resources"
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH
exec "$HERE/python3" -E -s -B "$CONTENTS/Resources/app/novopdf_inicio.pyw" "$@"
"""


def run(cmd, **kw):
    print("  $", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def macho_deps(path):
    from macholib.MachO import MachO
    from macholib import mach_o
    out, rpaths = [], []
    try:
        m = MachO(path)
    except Exception:
        return out, rpaths
    for h in m.headers:
        for lc, cmd, data in h.commands:
            n = mach_o.LC_NAMES.get(lc.cmd, "")
            if n in ("LC_LOAD_DYLIB", "LC_LOAD_WEAK_DYLIB", "LC_REEXPORT_DYLIB"):
                out.append(data.rstrip(b"\0").decode())
            elif n == "LC_RPATH":
                rpaths.append(data.rstrip(b"\0").decode())
    return sorted(set(out)), sorted(set(rpaths))


def is_macho(p):
    try:
        with open(p, "rb") as fh:
            magic = fh.read(4)
        return magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca")
    except OSError:
        return False


def resolve(dep, loader, exe_dir, rpaths):
    if dep.startswith("/System/") or dep.startswith("/usr/lib/"):
        return "system"
    cands = []
    if dep.startswith("@loader_path/"):
        cands.append(os.path.join(os.path.dirname(loader), dep[len("@loader_path/"):]))
    elif dep.startswith("@executable_path/"):
        cands.append(os.path.join(exe_dir, dep[len("@executable_path/"):]))
    elif dep.startswith("@rpath/"):
        for rp in rpaths:
            rp = rp.replace("@loader_path", os.path.dirname(loader)).replace("@executable_path", exe_dir)
            cands.append(os.path.join(rp, dep[len("@rpath/"):]))
    else:
        cands.append(dep)
    for c in cands:
        if os.path.exists(c):
            return os.path.normpath(c)
    return None


def build(arch):
    print(f"== {arch}")
    app = os.path.join(OUT, arch, "NovoPDF.app")
    shutil.rmtree(os.path.join(OUT, arch), ignore_errors=True)
    C = os.path.join(app, "Contents")
    os.makedirs(os.path.join(C, "MacOS"))
    os.makedirs(os.path.join(C, "Resources"))
    py = os.path.join(MB, "dl", PBS[arch], "python")

    # --- intérprete y biblioteca estándar
    shutil.copy2(os.path.join(py, "bin", "python3.12"), os.path.join(C, "MacOS", "python3"))
    shutil.copytree(os.path.join(py, "lib", "python3.12"), os.path.join(C, "lib", "python3.12"), symlinks=True)
    shutil.copy2(os.path.join(py, "lib", "libpython3.12.dylib"), os.path.join(C, "lib", "libpython3.12.dylib"))
    L = os.path.join(C, "lib", "python3.12")
    for d in ("test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "pydoc_data",
              "config-3.12-darwin", "site-packages/pip"):
        shutil.rmtree(os.path.join(L, d), ignore_errors=True)
    for f in os.listdir(os.path.join(L, "lib-dynload")):
        if f.startswith(("_tkinter", "_test", "xxlimited", "_xxtestfuzz", "_ctypes_test")):
            os.remove(os.path.join(L, "lib-dynload", f))
    for root, dirs, files in os.walk(L):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d))
                dirs.remove(d)

    # --- dependencias
    SP = os.path.join(L, "site-packages")
    for item in os.listdir(os.path.join(MB, f"sp_{arch}")):
        s = os.path.join(MB, f"sp_{arch}", item)
        d = os.path.join(SP, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
    P = os.path.join(SP, "PySide6")
    keep_py = {"QtCore", "QtGui", "QtWidgets", "QtSvg", "QtPrintSupport"}
    for f in os.listdir(P):
        full = os.path.join(P, f)
        base = f.split(".")[0]
        if f.endswith(".abi3.so") and base not in keep_py:
            os.remove(full)
        elif f.endswith((".pyi", ".app")):
            shutil.rmtree(full) if os.path.isdir(full) else os.remove(full)
        elif f in ("include", "typesystems", "glue", "scripts", "doc", "examples", "metatypes", "lupdate",
                   "lrelease", "designer", "assistant", "linguist", "qmllint", "qmlformat", "qmlls",
                   "uic", "rcc", "libpyside6qml.abi3.6.9.dylib", "svgtoqml", "balsam", "balsamui",
                   "qsb", "androiddeployqt", "Assistant.app", "Designer.app", "Linguist.app"):
            shutil.rmtree(full) if os.path.isdir(full) else os.remove(full)
    Q = os.path.join(P, "Qt")
    for d in ("qml", "libexec", "metatypes"):
        shutil.rmtree(os.path.join(Q, d), ignore_errors=True)
    plug = os.path.join(Q, "plugins")
    for d in os.listdir(plug):
        if d not in ("platforms", "imageformats", "iconengines", "styles"):
            shutil.rmtree(os.path.join(plug, d))
    for f in os.listdir(os.path.join(plug, "platforms")):
        if f != "libqcocoa.dylib":
            os.remove(os.path.join(plug, "platforms", f))
    keep_img = {"libqjpeg.dylib", "libqico.dylib", "libqsvg.dylib", "libqgif.dylib", "libqtiff.dylib",
                "libqwebp.dylib", "libqmacheif.dylib", "libqmacjp2.dylib"}
    for f in os.listdir(os.path.join(plug, "imageformats")):
        if f not in keep_img:
            os.remove(os.path.join(plug, "imageformats", f))
    tr = os.path.join(Q, "translations")
    if os.path.isdir(tr):
        for f in os.listdir(tr):
            if f not in ("qtbase_es.qm", "qt_es.qm"):
                p = os.path.join(tr, f)
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    # Frameworks de Qt: conservar solo los que se usan (cierre de dependencias)
    exe_dir = os.path.join(C, "MacOS")
    roots = [os.path.join(P, f) for f in os.listdir(P) if f.endswith(".so") or f.endswith(".dylib")]
    for root, _, files in os.walk(plug):
        roots += [os.path.join(root, f) for f in files if f.endswith(".dylib")]
    needed, todo = set(), list(roots)
    while todo:
        f = todo.pop()
        deps, rps = macho_deps(f)
        for dep in deps:
            r = resolve(dep, f, exe_dir, rps)
            if r and r != "system" and r not in needed:
                needed.add(r)
                todo.append(r)
    libdir = os.path.join(Q, "lib")
    for fw in os.listdir(libdir):
        full = os.path.join(libdir, fw)
        if not any(n.startswith(full + os.sep) for n in needed):
            shutil.rmtree(full) if os.path.isdir(full) else os.remove(full)
    print("  frameworks de Qt:", sorted(os.listdir(libdir)))
    shutil.rmtree(os.path.join(SP, "shiboken6", "include"), ignore_errors=True)
    for root, dirs, files in os.walk(SP):
        for f in files:
            if f.endswith((".pyi", ".a")):
                os.remove(os.path.join(root, f))
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d))
                dirs.remove(d)

    # --- aplicación
    R = os.path.join(C, "Resources")
    shutil.copytree(os.path.join(SRC, "novopdf"), os.path.join(R, "app", "novopdf"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(os.path.join(HERE, "novopdf_inicio.pyw"), os.path.join(R, "app", "novopdf_inicio.pyw"))
    shutil.copytree(os.path.join(SRC, "recursos", "tessdata"), os.path.join(R, "recursos", "tessdata"))
    shutil.copy2(os.path.join(HERE, "mac", "NovoPDF.icns"), os.path.join(R, "NovoPDF.icns"))
    # --- licencia y avisos (los abre «Acerca de NovoPDF»)
    ROOT = os.path.join(HERE, "..")
    for f in ("LICENSE", "AVISOS_TERCEROS.txt"):
        shutil.copy2(os.path.join(ROOT, f), os.path.join(R, f))
    shutil.copytree(os.path.join(ROOT, "licencias"), os.path.join(R, "licencias"))

    with open(os.path.join(C, "MacOS", "NovoPDF"), "w", newline="\n") as fh:
        fh.write(LAUNCHER)
    os.chmod(os.path.join(C, "MacOS", "NovoPDF"), 0o755)

    plist = {
        "CFBundleName": "NovoPDF",
        "CFBundleDisplayName": "NovoPDF",
        "CFBundleIdentifier": "es.unex.novopdf",
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "CFBundleExecutable": "NovoPDF",
        "CFBundleIconFile": "NovoPDF",
        "CFBundlePackageType": "APPL",
        "CFBundleSignature": "NPDF",
        "CFBundleDevelopmentRegion": "es",
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": "12.0",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHighResolutionCapable": True,
        "NSSupportsAutomaticGraphicsSwitching": True,
        "NSRequiresAquaSystemAppearance": True,
        "NSHumanReadableCopyright": "NovoPDF " + VERSION,
        "NSDocumentsFolderUsageDescription": "NovoPDF necesita acceder a Documentos para abrir y guardar PDF y recoger las páginas escaneadas.",
        "NSDesktopFolderUsageDescription": "NovoPDF necesita acceder al Escritorio para abrir y guardar PDF.",
        "NSDownloadsFolderUsageDescription": "NovoPDF necesita acceder a Descargas para abrir y guardar PDF.",
        "NSRemovableVolumesUsageDescription": "NovoPDF necesita acceder a discos externos para abrir y guardar PDF.",
        "NSNetworkVolumesUsageDescription": "NovoPDF necesita acceder a unidades de red para abrir y guardar PDF.",
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "Documento PDF",
            "CFBundleTypeRole": "Editor",
            "LSHandlerRank": "Alternate",
            "LSItemContentTypes": ["com.adobe.pdf"],
            "CFBundleTypeIconFile": "NovoPDF",
        }, {
            "CFBundleTypeName": "Imagen",
            "CFBundleTypeRole": "Viewer",
            "LSHandlerRank": "Alternate",
            "LSItemContentTypes": ["public.jpeg", "public.png", "public.tiff"],
        }],
    }
    if arch == "x86_64":
        plist["LSArchitecturePriority"] = ["x86_64"]
    else:
        plist["LSArchitecturePriority"] = ["arm64"]
    with open(os.path.join(C, "Info.plist"), "wb") as fh:
        plistlib.dump(plist, fh)
    with open(os.path.join(C, "PkgInfo"), "w") as fh:
        fh.write("APPLNPDF")

    # --- .pyc precompilados (versión 3.12, válidos en cualquier plataforma)
    if os.path.exists(WINE_PY):
        env = dict(os.environ, WINEDEBUG="-all", WINEPREFIX=os.environ.get("WINEPREFIX", "/tmp/claude-0/wine"))
        subprocess.run(["wine", WINE_PY, "-E", "-s", "-m", "compileall", "-q", "-j", "0",
                        "--invalidation-mode", "unchecked-hash", L, os.path.join(R, "app")],
                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)

    # --- comprobación de dependencias Mach-O
    missing = []
    for root, _, files in os.walk(C):
        for f in files:
            p = os.path.join(root, f)
            if os.path.islink(p) or not is_macho(p):
                continue
            deps, rps = macho_deps(p)
            for dep in deps:
                if resolve(dep, p, exe_dir, rps) is None:
                    missing.append((os.path.relpath(p, C), dep))
    if missing:
        print("  AVISO dependencias no resueltas:")
        for m in missing[:30]:
            print("   ", m)
    else:
        print("  dependencias Mach-O: todas resueltas")
    return app


def zip_app(app, dest, extra_files=()):
    """ZIP que conserva permisos de ejecución y enlaces simbólicos (Utilidad de Archivos)."""
    base = os.path.dirname(app)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=7) as z:
        for root, dirs, files in os.walk(app):
            for name in dirs + files:
                p = os.path.join(root, name)
                arc = os.path.relpath(p, base)
                st = os.lstat(p)
                if os.path.islink(p):
                    zi = zipfile.ZipInfo(arc)
                    zi.create_system = 3
                    zi.external_attr = (stat.S_IFLNK | 0o755) << 16
                    z.writestr(zi, os.readlink(p))
                elif os.path.isdir(p):
                    if os.listdir(p):
                        continue
                    zi = zipfile.ZipInfo(arc + "/")
                    zi.create_system = 3
                    zi.external_attr = (stat.S_IFDIR | 0o755) << 16
                    z.writestr(zi, b"")
                else:
                    zi = zipfile.ZipInfo.from_file(p, arc)
                    zi.create_system = 3
                    mode = 0o755 if (st.st_mode & 0o111) or is_macho(p) else 0o644
                    zi.external_attr = (stat.S_IFREG | mode) << 16
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    with open(p, "rb") as fh:
                        z.writestr(zi, fh.read(), compresslevel=7)
        for src, arc in extra_files:
            zi = zipfile.ZipInfo.from_file(src, arc)
            zi.create_system = 3
            mode = 0o755 if arc.endswith(".command") else 0o644
            zi.external_attr = (stat.S_IFREG | mode) << 16
            with open(src, "rb") as fh:
                z.writestr(zi, fh.read(), compress_type=zipfile.ZIP_DEFLATED)


if __name__ == "__main__":
    archs = sys.argv[1:] or ["arm64", "x86_64"]
    os.makedirs(OUT, exist_ok=True)
    for a in archs:
        app = build(a)
        label = {"arm64": "AppleSilicon", "x86_64": "Intel"}[a]
        dest = os.path.join(OUT, f"NovoPDF_{VERSION}_macOS_{label}.zip")
        zip_app(app, dest, extra_files=[
            (os.path.join(HERE, "mac", "LEEME_macOS.txt"), "LEEME_macOS.txt"),
            (os.path.join(HERE, "mac", "Instalar NovoPDF.command"), "Instalar NovoPDF.command"),
            (os.path.join(HERE, "..", "LICENSE"), "LICENSE"),
            (os.path.join(HERE, "..", "AVISOS_TERCEROS.txt"), "AVISOS_TERCEROS.txt"),
        ])
        print("  ->", dest, os.path.getsize(dest) // (1024 * 1024), "MB")
