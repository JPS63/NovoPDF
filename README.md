# NovoPDF

Una aplicación sencilla y atractiva para trabajar con documentos PDF, para Windows y macOS.
Funciona sin conexión a Internet y no necesita instalación (versión portable para Windows).

**Versión actual: 1.7.0** · [Descargas](https://github.com/JPS63/NovoPDF/releases) ·
Licencia [GNU AGPL v3 o posterior](LICENSE)

## Qué hace

- **Ver y organizar**: pestañas y varias ventanas, miniaturas, buscar, insertar, extraer, duplicar,
  girar, reordenar y eliminar páginas; crear PDF en blanco, desde imágenes o combinando varios.
- **Editar**: cambiar párrafos sin descolocar la página (conservando fuentes, negritas y viñetas),
  añadir texto e imágenes, borrar zonas, resaltar, subrayar y tachar. También sobre escaneados.
- **Formularios**: rellenarlos (Tab para pasar de un campo a otro), crearlos a mano o con
  **Detectar campos** (rayas, recuadros, tablas y casillas de un impreso sin formulario),
  vaciarlos, aplanarlos y exportar sus datos a Excel (de uno o de muchos formularios a la vez).
- **Firmar** digitalmente (PAdES) con certificados del sistema (FNMT, DNIe, tarjetas) o archivos
  .pfx/.p12, con sello visible o invisible, y comprobar firmas.
- **Escanear** directamente a PDF (WIA y TWAIN en Windows) y **reconocer texto** (OCR en español e
  inglés con Tesseract).
- **Exportar** a Word, Excel e imágenes; **imprimir** con vista previa; **proteger** con contraseña
  (AES-256).

## Descargar

Los programas listos para usar están en [Releases](https://github.com/JPS63/NovoPDF/releases):

| Archivo | Para qué |
|---|---|
| `NovoPDF_<versión>_portable_Windows.zip` | Windows 10/11 de 64 bits. Descomprimir y abrir `NovoPDF.exe`. |
| `actualizacion_Windows_<versión>.zip` | Actualizar una carpeta NovoPDF ya existente (conserva la configuración). |

Cada versión publicada incluye su código fuente exacto (etiqueta `v<versión>`).

## Código fuente

```
src/novopdf/core   lógica sin interfaz (documento, edición, formularios, firma, OCR, exportación…)
src/novopdf/ui     interfaz con PySide6 (Qt 6)
build/             construcción del portable de Windows y de la app de macOS, lanzador y ayudante TWAIN
tests/             pruebas automáticas
licencias/         textos de las licencias de terceros
```

Para ejecutarlo desde el código (Python 3.12):

```
pip install -r build/requisitos.txt
python -m novopdf                          # desde la carpeta src/
```

Los detalles de construcción están en [COMPILAR.txt](COMPILAR.txt). Los datos del OCR
(`src/recursos/tessdata`) no están en el repositorio: se descargan de
<https://github.com/tesseract-ocr/tessdata>.

## Licencia

Copyright © 2026 Jesús Punzón Suero.

NovoPDF es software libre: puede redistribuirlo y/o modificarlo bajo los términos de la
[Licencia Pública General Affero de GNU](LICENSE), versión 3 o (a su elección) cualquier versión
posterior. Se distribuye SIN NINGUNA GARANTÍA.

NovoPDF usa componentes de terceros (PyMuPDF/MuPDF, Qt/PySide6, pyHanko, Tesseract, Python y
otros), cada uno con su licencia: ver [AVISOS_TERCEROS.txt](AVISOS_TERCEROS.txt).
