import os
import re
import urllib.request

CARPETA_ACTUAL = os.path.dirname(os.path.abspath(__file__))
CARPETA_FUENTES = os.path.join(CARPETA_ACTUAL, 'static', 'fuentes')
CARPETA_CSS = os.path.join(CARPETA_ACTUAL, 'static', 'css')
CSS_SALIDA_FUENTES = os.path.join(CARPETA_CSS, 'fuentes.css')
TAILWIND_SALIDA = os.path.join(CARPETA_CSS, 'tailwind.min.css')

URL_GOOGLE_FONTS = (
    "https://fonts.googleapis.com/css2?"
    "family=Cormorant+Garamond:wght@500;600;700&"
    "family=Montserrat:wght@400;500;600;700&display=swap"
)

URL_TAILWIND = "https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css"

CABECERAS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def descargar_texto(url):
    req = urllib.request.Request(url, headers=CABECERAS)
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode('utf-8')


def descargar_binario(url, destino):
    req = urllib.request.Request(url, headers=CABECERAS)
    with urllib.request.urlopen(req) as resp:
        with open(destino, 'wb') as f:
            f.write(resp.read())


def descargar_fuentes():
    print("Descargando la hoja de estilos de Google Fonts...")
    css_original = descargar_texto(URL_GOOGLE_FONTS)

    bloques = re.findall(r'@font-face\s*{[^}]*}', css_original)
    print(f"Se encontraron {len(bloques)} variantes de fuente.")

    css_nuevo = ""
    contador = 0

    for bloque in bloques:
        familia_match = re.search(r"font-family:\s*'([^']+)'", bloque)
        peso_match = re.search(r"font-weight:\s*(\d+)", bloque)
        url_match = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", bloque)

        if not (familia_match and peso_match and url_match):
            continue

        contador += 1
        familia = familia_match.group(1)
        peso = peso_match.group(1)
        url_fuente = url_match.group(1)

        nombre_archivo = f"{familia.replace(' ', '')}-{peso}-{contador}.woff2"
        ruta_local = os.path.join(CARPETA_FUENTES, nombre_archivo)

        print(f"Descargando {familia} peso {peso}...")
        descargar_binario(url_fuente, ruta_local)

        bloque_local = re.sub(
            r"url\(https://fonts\.gstatic\.com/[^)]+\)\s*format\('woff2'\)",
            f"url('../fuentes/{nombre_archivo}') format('woff2')",
            bloque
        )
        css_nuevo += bloque_local + "\n\n"

    with open(CSS_SALIDA_FUENTES, 'w', encoding='utf-8') as f:
        f.write(css_nuevo)

    print(f"Listo. Se generó {CSS_SALIDA_FUENTES}")
    print(f"Se descargaron {contador} archivos de fuente en {CARPETA_FUENTES}\n")


def descargar_tailwind():
    print("Descargando Tailwind CSS (build completo, sin JIT) para uso local...")
    descargar_binario(URL_TAILWIND, TAILWIND_SALIDA)
    print(f"Listo. Se generó {TAILWIND_SALIDA}\n")


def main():
    os.makedirs(CARPETA_FUENTES, exist_ok=True)
    os.makedirs(CARPETA_CSS, exist_ok=True)

    descargar_fuentes()
    descargar_tailwind()

    print("TODO LISTO. A partir de ahora el sistema puede correr sin internet,")
    print("siempre que uses los archivos locales (ver plantillas HTML actualizadas).")


if __name__ == '__main__':
    main()