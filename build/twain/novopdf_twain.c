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

/*
 * novopdf_twain - ayudante de escaneo TWAIN para NovoPDF.
 *
 * NovoPDF es un programa de 64 bits y muchos escáneres de oficina (p. ej. los Ricoh Aficio
 * con «Network TWAIN») solo tienen controlador TWAIN de 32 bits, que no se puede cargar en
 * un proceso de 64 bits. Este programa pequeño (se compila en 32 y en 64 bits) hace de
 * intermediario: habla con el gestor TWAIN (twain_32.dll o TWAINDSM.dll), escanea y guarda
 * cada página como BMP en una carpeta; NovoPDF lee las páginas al terminar.
 *
 * Uso:
 *   novopdf_twain list
 *       SOURCE\t<nombre>\t<fabricante>\t<familia>\t<versión de protocolo>
 *   novopdf_twain scan --source <nombre> --out <carpeta> [--ui] [--dpi N]
 *                      [--mode color|gray|bw] [--feeder] [--duplex] [--cancel <archivo>]
 *       PAGE\t<archivo.bmp>\t<ppp>      (una línea por página)
 *       DONE\t<páginas>  |  CANCEL\t<páginas>  |  ERROR\t<código TWAIN o 1000+>\t<etapa>
 *   (solo ASCII: los textos para el usuario los pone NovoPDF; los nombres de los escáneres
 *   salen en la página de códigos ANSI de Windows)
 *
 * Compilar (mingw-w64):
 *   i686-w64-mingw32-gcc   -O2 -s -mwindows -o novopdf_twain32.exe novopdf_twain.c -luser32 -lkernel32
 *   x86_64-w64-mingw32-gcc -O2 -s -mwindows -o novopdf_twain64.exe novopdf_twain.c -luser32 -lkernel32
 * (-mwindows: sin ventana de consola; la salida va igualmente por la tubería a NovoPDF.)
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---------------------------------------------------------------- definiciones TWAIN */
#pragma pack(push, 2)
typedef unsigned short TW_UINT16;
typedef unsigned int TW_UINT32;      /* 32 bits también en Win64 */
typedef short TW_INT16;
typedef int TW_INT32;
typedef unsigned short TW_BOOL;
typedef void *TW_HANDLE;
typedef void *TW_MEMREF;
typedef char TW_STR32[34];

typedef struct { TW_INT16 Whole; TW_UINT16 Frac; } TW_FIX32;
typedef struct { TW_UINT16 MajorNum, MinorNum, Language, Country; TW_STR32 Info; } TW_VERSION;
typedef struct {
    TW_UINT32 Id; TW_VERSION Version; TW_UINT16 ProtocolMajor, ProtocolMinor;
    TW_UINT32 SupportedGroups; TW_STR32 Manufacturer, ProductFamily, ProductName;
} TW_IDENTITY;
typedef struct { TW_BOOL ShowUI; TW_BOOL ModalUI; TW_HANDLE hParent; } TW_USERINTERFACE;
typedef struct { TW_MEMREF pEvent; TW_UINT16 TWMessage; } TW_EVENT;
typedef struct { TW_UINT16 Count; TW_UINT32 EOJ; } TW_PENDINGXFERS;
typedef struct { TW_UINT16 Cap; TW_UINT16 ConType; TW_HANDLE hContainer; } TW_CAPABILITY;
typedef struct { TW_UINT16 ItemType; TW_UINT32 Item; } TW_ONEVALUE;
typedef struct { TW_UINT16 ConditionCode; TW_UINT16 Data; } TW_STATUS;
typedef struct {
    TW_FIX32 XResolution, YResolution; TW_INT32 ImageWidth, ImageLength; TW_INT16 SamplesPerPixel;
    TW_INT16 BitsPerSample[8]; TW_INT16 BitsPerPixel; TW_BOOL Planar; TW_INT16 PixelType;
    TW_UINT16 Compression;
} TW_IMAGEINFO;
#pragma pack(pop)

typedef TW_UINT16 (WINAPI *DSMENTRYPROC)(TW_IDENTITY *, TW_IDENTITY *, TW_UINT32, TW_UINT16, TW_UINT16, TW_MEMREF);

#define DG_CONTROL 0x0001
#define DG_IMAGE 0x0002
#define DAT_CAPABILITY 0x0001
#define DAT_EVENT 0x0002
#define DAT_IDENTITY 0x0003
#define DAT_PARENT 0x0004
#define DAT_PENDINGXFERS 0x0005
#define DAT_STATUS 0x0008
#define DAT_USERINTERFACE 0x0009
#define DAT_IMAGEINFO 0x0101
#define DAT_IMAGENATIVEXFER 0x0104
#define MSG_GET 0x0001
#define MSG_GETFIRST 0x0004
#define MSG_GETNEXT 0x0005
#define MSG_SET 0x0006
#define MSG_RESET 0x0007
#define MSG_XFERREADY 0x0101
#define MSG_CLOSEDSREQ 0x0102
#define MSG_CLOSEDSOK 0x0103
#define MSG_OPENDSM 0x0301
#define MSG_CLOSEDSM 0x0302
#define MSG_OPENDS 0x0401
#define MSG_CLOSEDS 0x0402
#define MSG_USERSELECT 0x0403
#define MSG_DISABLEDS 0x0501
#define MSG_ENABLEDS 0x0502
#define MSG_PROCESSEVENT 0x0601
#define MSG_ENDXFER 0x0701
#define TWRC_SUCCESS 0
#define TWRC_FAILURE 1
#define TWRC_CHECKSTATUS 2
#define TWRC_CANCEL 3
#define TWRC_DSEVENT 4
#define TWRC_NOTDSEVENT 5
#define TWRC_XFERDONE 6
#define TWRC_ENDOFLIST 7
#define TWON_ONEVALUE 5
#define TWTY_INT16 0x0001
#define TWTY_UINT16 0x0004
#define TWTY_BOOL 0x0006
#define TWTY_FIX32 0x0007
#define CAP_XFERCOUNT 0x0001
#define ICAP_PIXELTYPE 0x0101
#define ICAP_UNITS 0x0102
#define ICAP_XFERMECH 0x0103
#define ICAP_XRESOLUTION 0x1118
#define ICAP_YRESOLUTION 0x1119
#define CAP_FEEDERENABLED 0x1002
#define CAP_AUTOFEED 0x1007
#define CAP_DUPLEXENABLED 0x1013
#define CAP_INDICATORS 0x100b
#define TWPT_BW 0
#define TWPT_GRAY 1
#define TWPT_RGB 2
#define TWUN_INCHES 0
#define TWSX_NATIVE 0
#define DF_APP2 0x20000000
#define DG_CONTROL_IMAGE (DG_CONTROL | DG_IMAGE)

/* ---------------------------------------------------------------- estado */
static DSMENTRYPROC dsm = NULL;
static TW_IDENTITY app, src;
static HWND hwnd = NULL;
static int dsm_open = 0, ds_open = 0, ds_enabled = 0;
static int pages = 0, finished = 0, cancelled = 0, failed = 0;
static char outdir[MAX_PATH] = ".";
static char cancel_file[MAX_PATH] = "";

static void out(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stdout, fmt, ap);
    va_end(ap);
    fputc('\n', stdout);
    fflush(stdout);
}

static TW_UINT16 condition(TW_IDENTITY *dest)
{
    TW_STATUS st;
    memset(&st, 0, sizeof st);
    dsm(&app, dest, DG_CONTROL, DAT_STATUS, MSG_GET, &st);
    return st.ConditionCode;
}

static int load_dsm(void)
{
    const char *names[] = {"TWAINDSM.dll", "twain_32.dll", NULL};
    char path[MAX_PATH];
    int i;
#ifdef _WIN64
    names[1] = NULL;               /* twain_32.dll solo existe en 32 bits */
#endif
    for (i = 0; names[i]; i++) {
        HMODULE h = LoadLibraryA(names[i]);
        if (!h && GetWindowsDirectoryA(path, MAX_PATH)) {
            strcat(path, "\\");
            strcat(path, names[i]);
            h = LoadLibraryA(path);
        }
        if (h) {
            dsm = (DSMENTRYPROC)GetProcAddress(h, "DSM_Entry");
            if (dsm)
                return 1;
            FreeLibrary(h);
        }
    }
    return 0;
}

static void init_identity(void)
{
    memset(&app, 0, sizeof app);
    app.Version.MajorNum = 1;
    app.Version.MinorNum = 5;
    app.Version.Language = 0x6c;   /* TWLG_SPANISH */
    app.Version.Country = 34;      /* TWCY_SPAIN */
    strcpy(app.Version.Info, "NovoPDF");
    app.ProtocolMajor = 1;         /* 1.9: sin DF_APP2, válido con twain_32 y TWAINDSM */
    app.ProtocolMinor = 9;
    app.SupportedGroups = DG_CONTROL_IMAGE;
    strcpy(app.Manufacturer, "NovoPDF");
    strcpy(app.ProductFamily, "NovoPDF");
    strcpy(app.ProductName, "NovoPDF");
}

static int open_dsm(void)
{
    if (!load_dsm()) {
        out("ERROR\t1001\tnodsm");
        return 0;
    }
    init_identity();
    if (dsm(&app, NULL, DG_CONTROL, DAT_PARENT, MSG_OPENDSM, (TW_MEMREF)&hwnd) != TWRC_SUCCESS) {
        out("ERROR\t1002\topendsm");
        return 0;
    }
    dsm_open = 1;
    return 1;
}

static void close_all(void)
{
    if (ds_enabled) {
        TW_USERINTERFACE ui;
        memset(&ui, 0, sizeof ui);
        ui.hParent = (TW_HANDLE)hwnd;
        dsm(&app, &src, DG_CONTROL, DAT_USERINTERFACE, MSG_DISABLEDS, &ui);
        ds_enabled = 0;
    }
    if (ds_open) {
        dsm(&app, NULL, DG_CONTROL, DAT_IDENTITY, MSG_CLOSEDS, &src);
        ds_open = 0;
    }
    if (dsm_open) {
        dsm(&app, NULL, DG_CONTROL, DAT_PARENT, MSG_CLOSEDSM, (TW_MEMREF)&hwnd);
        dsm_open = 0;
    }
}

/* ---------------------------------------------------------------- capacidades */
static int set_one(TW_UINT16 cap, TW_UINT16 type, TW_UINT32 value)
{
    TW_CAPABILITY c;
    TW_ONEVALUE *v;
    TW_UINT16 rc;
    c.Cap = cap;
    c.ConType = TWON_ONEVALUE;
    c.hContainer = GlobalAlloc(GHND, sizeof(TW_ONEVALUE));
    if (!c.hContainer)
        return 0;
    v = (TW_ONEVALUE *)GlobalLock(c.hContainer);
    v->ItemType = type;
    v->Item = value;
    GlobalUnlock(c.hContainer);
    rc = dsm(&app, &src, DG_CONTROL, DAT_CAPABILITY, MSG_SET, &c);
    GlobalFree(c.hContainer);
    return rc == TWRC_SUCCESS || rc == TWRC_CHECKSTATUS;
}

static TW_UINT32 fix32(int whole) { return (TW_UINT32)(TW_UINT16)whole; }

/* ---------------------------------------------------------------- transferencia */
static int save_dib(HANDLE h, int dpi_hint)
{
    BITMAPINFOHEADER *bi = (BITMAPINFOHEADER *)GlobalLock(h);
    BITMAPFILEHEADER fh;
    DWORD colors, header, image, stride;
    char path[MAX_PATH + 32];
    FILE *f;
    int dpi;
    if (!bi)
        return 0;
    colors = bi->biClrUsed;
    if (!colors && bi->biBitCount <= 8)
        colors = 1u << bi->biBitCount;
    header = bi->biSize + colors * 4 + (bi->biCompression == BI_BITFIELDS && bi->biSize == sizeof(BITMAPINFOHEADER) ? 12 : 0);
    stride = ((bi->biWidth * bi->biBitCount + 31) / 32) * 4;
    image = bi->biSizeImage ? bi->biSizeImage : stride * (DWORD)abs(bi->biHeight);
    if (bi->biCompression == BI_RGB)
        image = stride * (DWORD)abs(bi->biHeight);
    dpi = bi->biXPelsPerMeter > 0 ? (int)(bi->biXPelsPerMeter * 0.0254 + 0.5) : dpi_hint;
    if (dpi < 50 || dpi > 2400)
        dpi = dpi_hint > 0 ? dpi_hint : 200;
    memset(&fh, 0, sizeof fh);
    fh.bfType = 0x4d42;
    fh.bfOffBits = sizeof fh + header;
    fh.bfSize = fh.bfOffBits + image;
    snprintf(path, sizeof path, "%s\\pagina_%04d.bmp", outdir, pages + 1);
    f = fopen(path, "wb");
    if (!f) {
        GlobalUnlock(h);
        out("ERROR\t1003\tsave");
        return 0;
    }
    fwrite(&fh, sizeof fh, 1, f);
    fwrite(bi, 1, header + image, f);
    fclose(f);
    GlobalUnlock(h);
    pages++;
    out("PAGE\t%s\t%d", path, dpi);
    return 1;
}

static int cancel_requested(void)
{
    return cancel_file[0] && GetFileAttributesA(cancel_file) != INVALID_FILE_ATTRIBUTES;
}

static void transfer(void)
{
    TW_PENDINGXFERS px;
    memset(&px, 0, sizeof px);
    do {
        TW_IMAGEINFO info;
        TW_HANDLE hdib = NULL;
        TW_UINT16 rc;
        int dpi = 0;
        memset(&info, 0, sizeof info);
        if (dsm(&app, &src, DG_IMAGE, DAT_IMAGEINFO, MSG_GET, &info) == TWRC_SUCCESS)
            dpi = info.XResolution.Whole;
        rc = dsm(&app, &src, DG_IMAGE, DAT_IMAGENATIVEXFER, MSG_GET, (TW_MEMREF)&hdib);
        if (rc == TWRC_XFERDONE) {
            if (hdib) {
                save_dib((HANDLE)hdib, dpi);
                GlobalFree((HANDLE)hdib);
            }
        } else if (rc == TWRC_CANCEL) {
            cancelled = 1;
        } else {
            TW_UINT16 cc = condition(&src);
            out("ERROR\t%u\txfer", (unsigned)cc);
            failed = 1;
        }
        if (dsm(&app, &src, DG_CONTROL, DAT_PENDINGXFERS, MSG_ENDXFER, &px) != TWRC_SUCCESS)
            px.Count = 0;
        if ((cancelled || failed || cancel_requested()) && px.Count) {
            dsm(&app, &src, DG_CONTROL, DAT_PENDINGXFERS, MSG_RESET, &px);
            px.Count = 0;
            if (!failed)
                cancelled = 1;
        }
    } while (px.Count != 0);
}

/* ---------------------------------------------------------------- ventana y bucle */
static LRESULT CALLBACK wndproc(HWND h, UINT m, WPARAM w, LPARAM l)
{
    if (m == WM_TIMER && cancel_requested() && !finished) {
        cancelled = 1;
        finished = 1;
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(h, m, w, l);
}

static void make_window(void)
{
    WNDCLASSA wc;
    memset(&wc, 0, sizeof wc);
    wc.lpfnWndProc = wndproc;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "NovoPDF_TWAIN";
    RegisterClassA(&wc);
    /* ventana invisible que hace de «padre» de la ventana del controlador */
    hwnd = CreateWindowExA(WS_EX_TOOLWINDOW, wc.lpszClassName, "NovoPDF - Escanear", WS_POPUP,
                           GetSystemMetrics(SM_CXSCREEN) / 2, GetSystemMetrics(SM_CYSCREEN) / 3, 1, 1,
                           NULL, NULL, wc.hInstance, NULL);
    ShowWindow(hwnd, SW_SHOWNOACTIVATE);
    SetForegroundWindow(hwnd);
    SetTimer(hwnd, 1, 250, NULL);
}

static int do_list(void)
{
    TW_IDENTITY id;
    TW_UINT16 rc;
    if (!open_dsm())
        return 2;
    memset(&id, 0, sizeof id);
    rc = dsm(&app, NULL, DG_CONTROL, DAT_IDENTITY, MSG_GETFIRST, &id);
    while (rc == TWRC_SUCCESS) {
        out("SOURCE\t%s\t%s\t%s\t%u.%u", id.ProductName, id.Manufacturer, id.ProductFamily,
            (unsigned)id.ProtocolMajor, (unsigned)id.ProtocolMinor);
        memset(&id, 0, sizeof id);
        rc = dsm(&app, NULL, DG_CONTROL, DAT_IDENTITY, MSG_GETNEXT, &id);
    }
    out("DONE\t0");
    close_all();
    return 0;
}

static int do_scan(const char *name, int show_ui, int dpi, const char *mode, int feeder, int duplex)
{
    TW_USERINTERFACE ui;
    TW_UINT16 rc;
    MSG msg;
    if (!open_dsm())
        return 2;
    memset(&src, 0, sizeof src);
    if (name && *name) {
        strncpy(src.ProductName, name, sizeof(src.ProductName) - 1);
        rc = dsm(&app, NULL, DG_CONTROL, DAT_IDENTITY, MSG_OPENDS, &src);
    } else {
        rc = dsm(&app, NULL, DG_CONTROL, DAT_IDENTITY, MSG_USERSELECT, &src);
        if (rc == TWRC_CANCEL) {
            out("CANCEL\t0");
            close_all();
            return 0;
        }
        if (rc == TWRC_SUCCESS)
            rc = dsm(&app, NULL, DG_CONTROL, DAT_IDENTITY, MSG_OPENDS, &src);
    }
    if (rc != TWRC_SUCCESS) {
        TW_UINT16 cc = condition(NULL);
        out("ERROR\t%u\topends", (unsigned)cc);
        close_all();
        return 3;
    }
    ds_open = 1;
    /* Preferencias (si el controlador no las admite, se queda con las suyas) */
    set_one(CAP_XFERCOUNT, TWTY_INT16, (TW_UINT32)(TW_UINT16)-1);
    set_one(ICAP_XFERMECH, TWTY_UINT16, TWSX_NATIVE);
    set_one(ICAP_UNITS, TWTY_UINT16, TWUN_INCHES);
    if (mode) {
        TW_UINT32 pt = !strcmp(mode, "color") ? TWPT_RGB : !strcmp(mode, "bw") ? TWPT_BW : TWPT_GRAY;
        set_one(ICAP_PIXELTYPE, TWTY_UINT16, pt);
    }
    if (dpi > 0) {
        set_one(ICAP_XRESOLUTION, TWTY_FIX32, fix32(dpi));
        set_one(ICAP_YRESOLUTION, TWTY_FIX32, fix32(dpi));
    }
    if (feeder || duplex) {
        set_one(CAP_FEEDERENABLED, TWTY_BOOL, 1);
        set_one(CAP_AUTOFEED, TWTY_BOOL, 1);
    } else {
        set_one(CAP_FEEDERENABLED, TWTY_BOOL, 0);
    }
    set_one(CAP_DUPLEXENABLED, TWTY_BOOL, duplex ? 1 : 0);
    if (!show_ui)
        set_one(CAP_INDICATORS, TWTY_BOOL, 1);

    memset(&ui, 0, sizeof ui);
    ui.ShowUI = (TW_BOOL)(show_ui ? 1 : 0);
    ui.ModalUI = 0;
    ui.hParent = (TW_HANDLE)hwnd;
    rc = dsm(&app, &src, DG_CONTROL, DAT_USERINTERFACE, MSG_ENABLEDS, &ui);
    if (rc == TWRC_CANCEL) {
        out("CANCEL\t0");
        close_all();
        return 0;
    }
    if (rc != TWRC_SUCCESS && rc != TWRC_CHECKSTATUS) {
        TW_UINT16 cc = condition(&src);
        out("ERROR\t%u\tenable", (unsigned)cc);
        close_all();
        return 4;
    }
    ds_enabled = 1;
    while (!finished && GetMessageA(&msg, NULL, 0, 0) > 0) {
        TW_EVENT ev;
        ev.pEvent = (TW_MEMREF)&msg;
        ev.TWMessage = 0;
        rc = dsm(&app, &src, DG_CONTROL, DAT_EVENT, MSG_PROCESSEVENT, &ev);
        if (rc == TWRC_DSEVENT) {
            switch (ev.TWMessage) {
            case MSG_XFERREADY:
                transfer();
                if (!show_ui || cancelled || failed)
                    finished = 1;
                break;
            case MSG_CLOSEDSREQ:
            case MSG_CLOSEDSOK:
                finished = 1;
                break;
            }
            continue;
        }
        TranslateMessage(&msg);
        DispatchMessageA(&msg);
    }
    close_all();
    if (failed && !pages)
        return 5;
    if (cancelled)
        out("CANCEL\t%d", pages);
    else
        out("DONE\t%d", pages);
    return 0;
}

int main(int argc, char **argv)
{
    int i, show_ui = 0, dpi = 0, feeder = 0, duplex = 0;
    const char *name = NULL, *mode = NULL;
    if (argc < 2) {
        out("ERROR\t1000\tusage");
        return 1;
    }
    for (i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--source") && i + 1 < argc) name = argv[++i];
        else if (!strcmp(argv[i], "--out") && i + 1 < argc) { strncpy(outdir, argv[++i], MAX_PATH - 1); }
        else if (!strcmp(argv[i], "--cancel") && i + 1 < argc) { strncpy(cancel_file, argv[++i], MAX_PATH - 1); }
        else if (!strcmp(argv[i], "--ui")) show_ui = 1;
        else if (!strcmp(argv[i], "--dpi") && i + 1 < argc) dpi = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--mode") && i + 1 < argc) mode = argv[++i];
        else if (!strcmp(argv[i], "--feeder")) feeder = 1;
        else if (!strcmp(argv[i], "--duplex")) duplex = 1;
    }
    make_window();
    if (!strcmp(argv[1], "list"))
        return do_list();
    if (!strcmp(argv[1], "scan"))
        return do_scan(name, show_ui, dpi, mode, feeder, duplex);
    out("ERROR\t1000\tusage");
    return 1;
}
