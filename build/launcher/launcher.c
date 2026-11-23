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

/* Lanzador portable de NovoPDF: ejecuta runtime\pythonw.exe app\novopdf_inicio.pyw [args] */
#include <windows.h>
#include <stdlib.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR pCmdLine, int nShow) {
    (void)hInst; (void)hPrev; (void)nShow;
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
