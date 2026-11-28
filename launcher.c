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

/* Lanzador portable de NovoPDF: ejecuta runtime\pythonw.exe app\novopdf_inicio.pyw [args]
 *
 * Con «--impresora» hace de receptor de la impresora virtual «NovoPDF»: la impresora usa el
 * controlador «Microsoft Print To PDF» y un puerto local que es la tubería con nombre
 * \\.\pipe\NovoPDF-impresora. Este proceso (muy ligero, sin Python) espera en la tubería,
 * guarda cada trabajo en %LOCALAPPDATA%\NovoPDF\Impresiones\<documento>.pdf y lo abre con
 * NovoPDF (si ya está abierto, en una pestaña nueva). Se arranca al iniciar sesión (HKCU\...\Run).
 */
#include <windows.h>
#include <sddl.h>
#include <shlobj.h>
#include <stdlib.h>
#include <wchar.h>
#include <winspool.h>

#define PIPE_NAME L"\\\\.\\pipe\\NovoPDF-impresora"
#define PRINTER_NAME L"NovoPDF"
#define QUIT_MAGIC "NOVOPDF-SALIR"

static void sanitize(wchar_t *s) {
    /* nombre de archivo válido: sin \ / : * ? " < > | y sin espacios ni puntos al final */
    for (wchar_t *p = s; *p; ++p)
        if (wcschr(L"\\/:*?\"<>|", *p) || *p < 32) *p = L'_';
    size_t n = wcslen(s);
    while (n && (s[n - 1] == L' ' || s[n - 1] == L'.')) s[--n] = 0;
}

static void job_title(wchar_t *out, size_t cap) {
    /* nombre del documento que se está imprimiendo (para el nombre del archivo) */
    out[0] = 0;
    HANDLE h = NULL;
    if (!OpenPrinterW((LPWSTR)PRINTER_NAME, &h, NULL)) return;
    DWORD need = 0, n = 0;
    EnumJobsW(h, 0, 32, 1, NULL, 0, &need, &n);
    if (need) {
        BYTE *buf = (BYTE *)malloc(need);
        if (buf && EnumJobsW(h, 0, 32, 1, buf, need, &need, &n)) {
            JOB_INFO_1W *j = (JOB_INFO_1W *)buf;
            for (DWORD k = 0; k < n; ++k) {
                if (j[k].pDocument && (j[k].Status & JOB_STATUS_PRINTING || k == n - 1)) {
                    wcsncpy(out, j[k].pDocument, cap - 1);
                    out[cap - 1] = 0;
                    break;
                }
            }
        }
        free(buf);
    }
    ClosePrinter(h);
    /* «Microsoft Word - Informe.docx» -> «Informe» */
    const wchar_t *pref[] = {L"Microsoft Word - ", L"Microsoft Excel - ", L"Microsoft PowerPoint - ", NULL};
    for (int i = 0; pref[i]; ++i) {
        size_t lp = wcslen(pref[i]);
        if (_wcsnicmp(out, pref[i], lp) == 0) memmove(out, out + lp, (wcslen(out + lp) + 1) * sizeof(wchar_t));
    }
    wchar_t *dot = wcsrchr(out, L'.');
    if (dot && wcslen(dot) <= 5 && dot != out) *dot = 0;
    sanitize(out);
    if (wcslen(out) > 80) out[80] = 0;
}

static int pipe_security(SECURITY_ATTRIBUTES *sa) {
    /* Escriben en la tubería la cola de impresión (SYSTEM, servicios locales) y el usuario. */
    wchar_t sddl[512] = L"D:(A;;GA;;;SY)(A;;GA;;;LS)(A;;GA;;;NS)(A;;GA;;;BA)";
    HANDLE tok;
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &tok)) {
        BYTE buf[256];
        DWORD len;
        if (GetTokenInformation(tok, TokenUser, buf, sizeof(buf), &len)) {
            LPWSTR sid = NULL;
            if (ConvertSidToStringSidW(((TOKEN_USER *)buf)->User.Sid, &sid)) {
                wcscat(sddl, L"(A;;GA;;;");
                wcscat(sddl, sid);
                wcscat(sddl, L")");
                LocalFree(sid);
            }
        }
        CloseHandle(tok);
    }
    sa->nLength = sizeof(*sa);
    sa->bInheritHandle = FALSE;
    return ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, SDDL_REVISION_1, &sa->lpSecurityDescriptor, NULL);
}

static int run_printer_listener(const wchar_t *exe) {
    HANDLE mutex = CreateMutexW(NULL, TRUE, L"Local\\NovoPDF-impresora");
    if (GetLastError() == ERROR_ALREADY_EXISTS) return 0;          /* ya hay uno en marcha */
    wchar_t dir[MAX_PATH * 2];
    if (FAILED(SHGetFolderPathW(NULL, CSIDL_LOCAL_APPDATA, NULL, 0, dir))) return 1;
    wcscat(dir, L"\\NovoPDF");
    CreateDirectoryW(dir, NULL);
    wcscat(dir, L"\\Impresiones");
    CreateDirectoryW(dir, NULL);
    SECURITY_ATTRIBUTES sa;
    if (!pipe_security(&sa)) sa.lpSecurityDescriptor = NULL;
    for (;;) {
        HANDLE pipe = CreateNamedPipeW(PIPE_NAME, PIPE_ACCESS_INBOUND, PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                                       PIPE_UNLIMITED_INSTANCES, 0, 1 << 16, 0,
                                       sa.lpSecurityDescriptor ? &sa : NULL);
        if (pipe == INVALID_HANDLE_VALUE) { Sleep(3000); continue; }
        if (!ConnectNamedPipe(pipe, NULL) && GetLastError() != ERROR_PIPE_CONNECTED) {
            CloseHandle(pipe);
            continue;
        }
        wchar_t title[128], tmp[MAX_PATH * 2], path[MAX_PATH * 2];
        job_title(title, 128);
        if (!title[0]) {
            SYSTEMTIME st;
            GetLocalTime(&st);
            _snwprintf(title, 128, L"Impreso %04d-%02d-%02d %02d.%02d.%02d", st.wYear, st.wMonth, st.wDay,
                       st.wHour, st.wMinute, st.wSecond);
        }
        _snwprintf(tmp, MAX_PATH * 2, L"%ls\\.recibiendo_%lu.tmp", dir, GetTickCount());
        HANDLE out = CreateFileW(tmp, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        char buf[1 << 16];
        DWORD got, total = 0, wr;
        char head[16] = {0};
        while (ReadFile(pipe, buf, sizeof(buf), &got, NULL) && got) {
            if (total < sizeof(head) - 1) {
                DWORD c = got < sizeof(head) - 1 - total ? got : sizeof(head) - 1 - total;
                memcpy(head + total, buf, c);
            }
            if (out != INVALID_HANDLE_VALUE) WriteFile(out, buf, got, &wr, NULL);
            total += got;
        }
        DisconnectNamedPipe(pipe);
        CloseHandle(pipe);
        if (out != INVALID_HANDLE_VALUE) CloseHandle(out);
        if (strncmp(head, QUIT_MAGIC, strlen(QUIT_MAGIC)) == 0) {      /* NovoPDF pide que se cierre */
            DeleteFileW(tmp);
            break;
        }
        if (total < 8 || strncmp(head, "%PDF", 4) != 0) {               /* vacío o no es PDF */
            DeleteFileW(tmp);
            continue;
        }
        _snwprintf(path, MAX_PATH * 2, L"%ls\\%ls.pdf", dir, title);
        for (int n = 2; GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES && n < 1000; ++n)
            _snwprintf(path, MAX_PATH * 2, L"%ls\\%ls (%d).pdf", dir, title, n);
        if (!MoveFileW(tmp, path)) wcscpy(path, tmp);
        wchar_t cmd[MAX_PATH * 5];
        _snwprintf(cmd, MAX_PATH * 5, L"\"%ls\" \"%ls\" --impreso", exe, path);
        STARTUPINFOW si;
        PROCESS_INFORMATION pi;
        ZeroMemory(&si, sizeof(si));
        si.cb = sizeof(si);
        if (CreateProcessW(exe, cmd, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) {
            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
        }
    }
    if (sa.lpSecurityDescriptor) LocalFree(sa.lpSecurityDescriptor);
    ReleaseMutex(mutex);
    CloseHandle(mutex);
    return 0;
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR pCmdLine, int nShow) {
    (void)hInst; (void)hPrev; (void)nShow;
    if (pCmdLine && wcsstr(pCmdLine, L"--impresora")) {
        wchar_t exe[MAX_PATH * 2];
        GetModuleFileNameW(NULL, exe, MAX_PATH * 2);
        return run_printer_listener(exe);
    }
    const DWORD N = 32768;
    wchar_t *dir = (wchar_t *)calloc(N, sizeof(wchar_t));
    wchar_t *py = (wchar_t *)calloc(N, sizeof(wchar_t));
    wchar_t *cmd = (wchar_t *)calloc(N * 2, sizeof(wchar_t));
    if (!dir || !py || !cmd) return 1;
    GetModuleFileNameW(NULL, dir, N);
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;
    _snwprintf(py, N, L"%ls\\runtime\\pythonw.exe", dir);
    if (GetFileAttributesW(py) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"No se encuentra la carpeta \"runtime\" junto a NovoPDF.exe.\n\n"
                          L"Copia la carpeta NovoPDF completa, no solo el ejecutable.",
                    L"NovoPDF", MB_ICONERROR | MB_OK);
        return 1;
    }
    _snwprintf(cmd, N * 2, L"\"%ls\" -E -s \"%ls\\app\\novopdf_inicio.pyw\" %ls", py, dir,
               pCmdLine ? pCmdLine : L"");
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    SetEnvironmentVariableW(L"PYTHONHOME", NULL);
    SetEnvironmentVariableW(L"PYTHONPATH", NULL);
    SetEnvironmentVariableW(L"QT_PLUGIN_PATH", NULL);
    if (!CreateProcessW(py, cmd, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        wchar_t msg[512];
        _snwprintf(msg, 512, L"No se pudo iniciar NovoPDF (error %lu).", GetLastError());
        MessageBoxW(NULL, msg, L"NovoPDF", MB_ICONERROR | MB_OK);
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    free(dir); free(py); free(cmd);
    return 0;
}
