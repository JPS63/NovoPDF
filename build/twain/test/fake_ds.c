/*
 * NovoPDF - aplicación sencilla para trabajar con documentos PDF
 * Copyright (C) 2026 Jesús Punzón Suero
 *
 * Este programa es software libre: puede redistribuirlo y/o modificarlo bajo
 * los términos de la Licencia Pública General Affero de GNU publicada por la
 * Free Software Foundation, ya sea la versión 3 de la Licencia o (a su
 * elección) cualquier versión posterior.
 *
 * Este programa se distribuye con la esperanza de que sea útil, pero SIN
 * NINGUNA GARANTÍA; ni siquiera la garantía implícita de COMERCIABILIDAD o
 * IDONEIDAD PARA UN PROPÓSITO PARTICULAR. Consulte la Licencia Pública
 * General Affero de GNU (archivo LICENSE) para más detalles.
 *
 * Código fuente: https://github.com/JPS63/NovoPDF
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

/* Escáner TWAIN de prueba (fuente de datos .ds) para probar novopdf_twain en Wine.
 * Variables de entorno:
 *   FAKEDS_PAGES   número de páginas por tanda (por defecto: 3 con alimentador, 1 en cristal)
 *   FAKEDS_LOG     archivo donde anotar las capacidades recibidas
 *   FAKEDS_FAIL    "open" (no se puede abrir) | "xfer" (falla la 2.ª página) | "cancel" (cancela la 1.ª)
 *   FAKEDS_DELAY   milisegundos que tarda cada página
 * i686-w64-mingw32-gcc -shared -O2 -o NovoFake.ds fake_ds.c -Wl,--kill-at
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#pragma pack(push, 2)
typedef unsigned short TW_UINT16; typedef unsigned int TW_UINT32; typedef short TW_INT16; typedef int TW_INT32;
typedef unsigned short TW_BOOL; typedef void *TW_HANDLE; typedef void *TW_MEMREF; typedef char TW_STR32[34];
typedef struct { TW_INT16 Whole; TW_UINT16 Frac; } TW_FIX32;
typedef struct { TW_UINT16 MajorNum, MinorNum, Language, Country; TW_STR32 Info; } TW_VERSION;
typedef struct { TW_UINT32 Id; TW_VERSION Version; TW_UINT16 ProtocolMajor, ProtocolMinor; TW_UINT32 SupportedGroups;
                 TW_STR32 Manufacturer, ProductFamily, ProductName; } TW_IDENTITY;
typedef struct { TW_BOOL ShowUI; TW_BOOL ModalUI; TW_HANDLE hParent; } TW_USERINTERFACE;
typedef struct { TW_MEMREF pEvent; TW_UINT16 TWMessage; } TW_EVENT;
typedef struct { TW_UINT16 Count; TW_UINT32 EOJ; } TW_PENDINGXFERS;
typedef struct { TW_UINT16 Cap; TW_UINT16 ConType; TW_HANDLE hContainer; } TW_CAPABILITY;
typedef struct { TW_UINT16 ItemType; TW_UINT32 Item; } TW_ONEVALUE;
typedef struct { TW_UINT16 ConditionCode; TW_UINT16 Data; } TW_STATUS;
typedef struct { TW_FIX32 XResolution, YResolution; TW_INT32 ImageWidth, ImageLength; TW_INT16 SamplesPerPixel;
                 TW_INT16 BitsPerSample[8]; TW_INT16 BitsPerPixel; TW_BOOL Planar; TW_INT16 PixelType; TW_UINT16 Compression; } TW_IMAGEINFO;
#pragma pack(pop)

static int pixeltype = 1, dpi = 100, feeder = 0, duplex = 0, pending = 0, total = 0, state = 4, closereq = 0, showui = 0;
static TW_UINT16 cc = 0;
static HWND parent;

static void logf_(const char *fmt, ...)
{
    const char *p = getenv("FAKEDS_LOG");
    FILE *f;
    va_list ap;
    if (!p || !(f = fopen(p, "a"))) return;
    va_start(ap, fmt); vfprintf(f, fmt, ap); va_end(ap);
    fputc('\n', f); fclose(f);
}

static int env_int(const char *n, int d) { const char *v = getenv(n); return v && *v ? atoi(v) : d; }
static int fail(const char *what) { const char *v = getenv("FAKEDS_FAIL"); return v && !strcmp(v, what); }

static HANDLE make_dib(int page)
{
    int w = 85 * dpi / 10, h = 110 * dpi / 10;          /* carta pequeña */
    int bpp = pixeltype == 2 ? 24 : pixeltype == 1 ? 8 : 1;
    int colors = bpp == 24 ? 0 : (1 << bpp);
    int stride = ((w * bpp + 31) / 32) * 4;
    HANDLE hm = GlobalAlloc(GHND, sizeof(BITMAPINFOHEADER) + colors * 4 + stride * h);
    BITMAPINFOHEADER *bi = (BITMAPINFOHEADER *)GlobalLock(hm);
    RGBQUAD *pal = (RGBQUAD *)(bi + 1);
    unsigned char *bits = (unsigned char *)(pal + colors);
    int x, y, i;
    bi->biSize = sizeof *bi; bi->biWidth = w; bi->biHeight = h; bi->biPlanes = 1; bi->biBitCount = bpp;
    bi->biCompression = BI_RGB; bi->biSizeImage = stride * h;
    bi->biXPelsPerMeter = bi->biYPelsPerMeter = (LONG)(dpi / 0.0254 + 0.5);
    bi->biClrUsed = colors;
    for (i = 0; i < colors; i++) {
        int v = colors == 2 ? i * 255 : i;
        pal[i].rgbRed = pal[i].rgbGreen = pal[i].rgbBlue = (BYTE)v;
    }
    /* fondo blanco y unas barras «de texto»; tantas como el número de página */
    for (y = 0; y < h; y++) {
        unsigned char *row = bits + (size_t)y * stride;
        int dark = 0, k;
        for (k = 0; k < page + 1; k++) {
            int y0 = h - (h / 8 + k * h / 10);
            if (y < y0 && y > y0 - h / 40) dark = 1;
        }
        for (x = 0; x < w; x++) {
            int on = dark && x > w / 8 && x < w * 6 / 8;
            if (bpp == 24) { row[x * 3] = on ? 40 : 250; row[x * 3 + 1] = on ? 20 : 250; row[x * 3 + 2] = on ? 200 : 250; }
            else if (bpp == 8) row[x] = on ? 20 : 250;
            else if (!on) row[x >> 3] |= (unsigned char)(0x80 >> (x & 7));
        }
    }
    GlobalUnlock(hm);
    return hm;
}

static TW_UINT32 get_one(TW_CAPABILITY *c)
{
    TW_ONEVALUE *v = (TW_ONEVALUE *)GlobalLock(c->hContainer);
    TW_UINT32 it = v ? v->Item : 0;
    if (v) GlobalUnlock(c->hContainer);
    return it;
}

__declspec(dllexport) TW_UINT16 WINAPI DS_Entry(TW_IDENTITY *origin, TW_UINT32 dg, TW_UINT16 dat, TW_UINT16 msg, TW_MEMREF data)
{
    (void)origin;
    if (dg == 1 && dat == 3) {                               /* DAT_IDENTITY */
        if (msg == 1) {                                      /* MSG_GET */
            TW_IDENTITY *id = (TW_IDENTITY *)data;
            TW_UINT32 keep = id->Id;
            memset(id, 0, sizeof *id);
            id->Id = keep;
            id->Version.MajorNum = 1; strcpy(id->Version.Info, "1.0");
            id->ProtocolMajor = 1; id->ProtocolMinor = 9; id->SupportedGroups = 3;
            strcpy(id->Manufacturer, "NovoPDF"); strcpy(id->ProductFamily, "Prueba");
            strcpy(id->ProductName, "Escaner de prueba TWAIN");
            return 0;
        }
        if (msg == 0x401) { if (fail("open")) { cc = 23; return 1; } state = 4; logf_("open"); return 0; }
        if (msg == 0x402) { logf_("close"); state = 3; return 0; }
        return 1;
    }
    if (dg == 1 && dat == 8) { ((TW_STATUS *)data)->ConditionCode = cc; cc = 0; return 0; }
    if (dg == 1 && dat == 1) {                               /* DAT_CAPABILITY */
        TW_CAPABILITY *c = (TW_CAPABILITY *)data;
        if (msg == 6) {
            TW_UINT32 v = get_one(c);
            logf_("cap %04x=%u", c->Cap, (unsigned)(v & 0xffff));
            if (c->Cap == 0x0101) pixeltype = (int)(v & 0xffff);
            if (c->Cap == 0x1118) dpi = (TW_INT16)(v & 0xffff);
            if (c->Cap == 0x1002) feeder = (int)(v & 0xffff);
            if (c->Cap == 0x1013) duplex = (int)(v & 0xffff);
            return 0;
        }
        cc = 13; return 1;
    }
    if (dg == 1 && dat == 9) {                               /* DAT_USERINTERFACE */
        TW_USERINTERFACE *ui = (TW_USERINTERFACE *)data;
        if (msg == 0x502) {
            parent = (HWND)ui->hParent;
            showui = ui->ShowUI;
            logf_("enable ui=%d", ui->ShowUI);
            total = env_int("FAKEDS_PAGES", feeder ? 3 : 1) * (duplex ? 2 : 1);
            pending = 1;
            state = 5;
            PostMessageA(parent, WM_USER + 7, 0, 0);
            return 0;
        }
        if (msg == 0x501) { logf_("disable"); state = 4; return 0; }
        return 1;
    }
    if (dg == 1 && dat == 2 && msg == 0x601) {               /* MSG_PROCESSEVENT */
        TW_EVENT *ev = (TW_EVENT *)data;
        ev->TWMessage = 0;
        if (state == 5 && pending) { pending = 0; state = 6; ev->TWMessage = 0x101; return 4; }
        if (closereq) { closereq = 0; ev->TWMessage = 0x102; return 4; }
        return 5;
    }
    if (dg == 2 && dat == 0x0101) {                          /* DAT_IMAGEINFO */
        TW_IMAGEINFO *ii = (TW_IMAGEINFO *)data;
        memset(ii, 0, sizeof *ii);
        ii->XResolution.Whole = ii->YResolution.Whole = (TW_INT16)dpi;
        ii->PixelType = (TW_INT16)pixeltype;
        return 0;
    }
    if (dg == 2 && dat == 0x0104) {                          /* DAT_IMAGENATIVEXFER */
        static int served = 0;
        if (fail("cancel")) return 3;
        if (fail("xfer") && served == 1) { cc = 20; return 1; }
        Sleep((DWORD)env_int("FAKEDS_DELAY", 0));
        *(HANDLE *)data = make_dib(served);
        served++;
        state = 7;
        return 6;
    }
    if (dg == 1 && dat == 5) {                               /* DAT_PENDINGXFERS */
        TW_PENDINGXFERS *px = (TW_PENDINGXFERS *)data;
        if (msg == 0x701) {
            total--;
            px->Count = (TW_UINT16)(total > 0 ? total : 0);
            state = px->Count ? 6 : 5;
            if (!px->Count) { closereq = showui; if (showui) PostMessageA(parent, WM_USER + 7, 0, 0); }
            return 0;
        }
        if (msg == 7) { total = 0; px->Count = 0; state = 5; logf_("reset"); return 0; }
        return 1;
    }
    cc = 9;
    return 1;
}
