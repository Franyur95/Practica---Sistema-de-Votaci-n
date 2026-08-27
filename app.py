from PIL import Image
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
from flask_compress import Compress
import json
import os
import io
import threading
import uuid
from functools import wraps
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 60 * 60 * 24  # 1 día de caché en el navegador
app.config['COMPRESS_MIMETYPES'] = ['text/html', 'text/css', 'text/xml', 'application/json', 'application/javascript']
Compress(app)
app.secret_key = 'clave_secreta_olga_marquez'

CARPETA_ACTUAL = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(CARPETA_ACTUAL, 'base_datos.json')
lock_datos = threading.RLock()

# Cache en memoria: evita leer y parsear el JSON del disco en cada clic.
_datos_cache = None
_mtime_cache = None

CARPETA_FOTOS = os.path.join(CARPETA_ACTUAL, 'static', 'fotos')
EXTENSIONES_PERMITIDAS = {'png', 'jpg', 'jpeg', 'webp'}
ANCHO_MAXIMO_FOTO = 900

CATEGORIAS_POR_DEFECTO = [
    {"id": "belleza", "nombre": "Belleza", "otorga_titulo": False},
    {"id": "elegancia", "nombre": "Elegancia", "otorga_titulo": True},
    {"id": "simpatia", "nombre": "Simpatía", "otorga_titulo": True},
    {"id": "postura", "nombre": "Postura", "otorga_titulo": False},
]


def extension_permitida(nombre_archivo):
    return '.' in nombre_archivo and nombre_archivo.rsplit('.', 1)[1].lower() in EXTENSIONES_PERMITIDAS


def slugify(texto):
    texto = texto.strip().lower()
    reemplazos = {'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ñ': 'n', ' ': '_'}
    for k, v in reemplazos.items():
        texto = texto.replace(k, v)
    return ''.join(ch for ch in texto if ch.isalnum() or ch == '_') or "categoria"


def cargar_datos():
    global _datos_cache, _mtime_cache

    with lock_datos:
        if not os.path.exists(DB_FILE):
            datos_iniciales = {
                "candidatas": [],
                "jurados": [],
                "votos_jurados": [],
                "categorias": CATEGORIAS_POR_DEFECTO,
                "admin": {"usuario": "admin", "password": "1234"}
            }
            guardar_datos(datos_iniciales)
            return _datos_cache

        mtime_actual = os.path.getmtime(DB_FILE)

        if _datos_cache is not None and _mtime_cache == mtime_actual:
            return _datos_cache

        with open(DB_FILE, 'r', encoding='utf-8') as f:
            datos = json.load(f)

        datos.setdefault('jurados', [])
        datos.setdefault('admin', {"usuario": "admin", "password": "olga2026"})
        datos.setdefault('categorias', CATEGORIAS_POR_DEFECTO)

        cambio = False
        for i, c in enumerate(datos.get('candidatas', []), start=1):
            if 'numero' not in c or not c['numero']:
                c['numero'] = i
                cambio = True

        _datos_cache = datos
        _mtime_cache = mtime_actual

        if cambio:
            guardar_datos(datos)

        return _datos_cache


def guardar_datos(datos):
    global _datos_cache, _mtime_cache
    with lock_datos:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(datos, f, indent=4, ensure_ascii=False)
        _datos_cache = datos
        _mtime_cache = os.path.getmtime(DB_FILE)


def guardar_foto_optimizada(archivo, ruta_destino):
    """Redimensiona y comprime la foto antes de guardarla, para que la
    página cargue rápido en las demás PCs conectadas por LAN/WiFi."""
    extension = ruta_destino.rsplit('.', 1)[1].lower()
    imagen = Image.open(archivo)

    if imagen.width > ANCHO_MAXIMO_FOTO:
        proporcion = ANCHO_MAXIMO_FOTO / float(imagen.width)
        nuevo_alto = int(imagen.height * proporcion)
        imagen = imagen.resize((ANCHO_MAXIMO_FOTO, nuevo_alto), Image.LANCZOS)

    if extension in ('jpg', 'jpeg'):
        if imagen.mode in ("RGBA", "P"):
            imagen = imagen.convert("RGB")
        imagen.save(ruta_destino, "JPEG", quality=82, optimize=True)
    else:
        imagen.save(ruta_destino, optimize=True)


def admin_requerido(f):
    @wraps(f)
    def decorador(*args, **kwargs):
        if not session.get('admin_logueado'):
            flash('Necesitás iniciar sesión como administrador.')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorador


# ==========================================================================
#  CÁLCULO DE RESULTADOS (nuevo método, explicado en el informe)
# ==========================================================================
import unicodedata

def calcular_resultados(datos):
    candidatas = datos.get('candidatas', [])
    votos = datos.get('votos_jurados', [])
    categorias = datos.get('categorias', [])
    n_categorias = len(categorias) or 1
    n_votos = len(votos)

    def normalizar(texto):
        texto = unicodedata.normalize('NFD', texto or '')
        return ''.join(c for c in texto if unicodedata.category(c) != 'Mn').lower()

    # 1. Identificar IDs de categorías para desempate
    cat_ids = {'belleza': None, 'elegancia': None, 'simpatia': None, 'postura': None}
    for cat in categorias:
        nombre_norm = normalizar(cat.get('nombre', ''))
        cid = cat['id']
        if 'belleza' in nombre_norm:
            cat_ids['belleza'] = cid
        elif 'elegancia' in nombre_norm:
            cat_ids['elegancia'] = cid
        elif 'simpatia' in nombre_norm:
            cat_ids['simpatia'] = cid
        elif 'postura' in nombre_norm:
            cat_ids['postura'] = cid

    # 2. Estructurar acumuladores por candidata
    resultados = {}
    for c in candidatas:
        cid_str = str(c['id'])
        resultados[cid_str] = {
            'id': c['id'],
            'nombre': c['nombre'],
            'curso': c['curso'],
            'numero': c.get('numero', 0),
            'foto': c.get('foto', ''),
            'promedio_desempate': c.get('promedio_desempate', 0), # Oculto en BD
            'acumulado': {cat['id']: 0 for cat in categorias},
            'acumulado_total': 0,
        }

    # 3. Sumar votos recibidos
    for v in votos:
        for id_c, notas in v.get('puntuaciones', {}).items():
            id_str = str(id_c)
            if id_str in resultados:
                for cat in categorias:
                    resultados[id_str]['acumulado'][cat['id']] += notas.get(cat['id'], 0)
                resultados[id_str]['acumulado_total'] += notas.get('total', 0)

    lista = list(resultados.values())

    # 4. Calcular promedios
    for f in lista:
        if n_votos > 0:
            f['promedio'] = {cid: round(val / n_votos, 2) for cid, val in f['acumulado'].items()}
            f['promedio_general'] = round((f['acumulado_total'] / n_votos) / n_categorias, 2)
            f['_promedio_exacto'] = (f['acumulado_total'] / n_votos) / n_categorias
        else:
            f['promedio'] = {cat['id']: 0 for cat in categorias}
            f['promedio_general'] = 0
            f['_promedio_exacto'] = 0

    # 5. Criterio de desempate en estricto orden solicitado
    def clave_desempate(fila):
        return (
            fila['promedio_general'],                                                      # 1° Promedio general redondeado
            fila['_promedio_exacto'],                                                      # 2° Promedio exacto decimal
            fila['promedio'].get(cat_ids['belleza'], 0) if cat_ids['belleza'] else 0,      # 3° PRIORIDAD: Belleza
            fila['promedio'].get(cat_ids['elegancia'], 0) if cat_ids['elegancia'] else 0,  # 4° PRIORIDAD: Elegancia
            fila['promedio'].get(cat_ids['simpatia'], 0) if cat_ids['simpatia'] else 0,    # 5° PRIORIDAD: Simpatía
            fila['promedio'].get(cat_ids['postura'], 0) if cat_ids['postura'] else 0,      # 6° PRIORIDAD: Postura
            fila.get('promedio_desempate', 0),                                             # 7° Desempate por Promedio BD (oculto)
            -(fila['numero'] or 0)                                                         # 8° Menor número de candidata
        )

    podio = []

    if n_votos > 0 and lista:
        orden_general = sorted(lista, key=clave_desempate, reverse=True)

        titulos_podio = [
            {"titulo": "Reina Escolar", "emoji": "👑"},
            {"titulo": "1ra Princesa", "emoji": "👑"},
            {"titulo": "2da Princesa", "emoji": "👑"},
            {"titulo": "Miss Elegancia", "emoji": "✨"},
            {"titulo": "Miss Simpatía", "emoji": "✨"}
        ]

        for i, candidata in enumerate(orden_general):
            if i < len(titulos_podio):
                item_podio = dict(candidata)
                item_podio['titulo'] = titulos_podio[i]['titulo']
                item_podio['emoji'] = titulos_podio[i]['emoji']
                item_podio['score_mostrar'] = f"{candidata['promedio_general']} / 10 (Promedio General)"
                podio.append(item_podio)

    # 6. Ocultar del retorno los promedios privados/de desempate
    for item in lista:
        item.pop('_promedio_exacto', None)
        item.pop('promedio_desempate', None)

    for item in podio:
        item.pop('_promedio_exacto', None)
        item.pop('promedio_desempate', None)

    return podio, lista

# ---------------------- PANEL DE JURADOS ----------------------

@app.route('/')
def home():
    datos = cargar_datos()
    total_jurados = len(datos.get('jurados', []))
    votos_emitidos = len(datos.get('votos_jurados', []))
    return render_template('login_jurado.html',
                            total_jurados=total_jurados,
                            votos_emitidos=votos_emitidos)


@app.route('/evaluacion', methods=['POST'])
def evaluacion():
    usuario = request.form.get('usuario', '').strip()
    password = request.form.get('password', '').strip()
    datos = cargar_datos()

    jurado = next((j for j in datos['jurados']
                    if j['usuario'] == usuario and j['password'] == password), None)

    if not jurado:
        flash('Usuario o contraseña incorrectos.')
        return redirect(url_for('home'))

    if jurado.get('ha_votado'):
        flash('Este jurado ya registró su planilla.')
        return redirect(url_for('home'))

    if jurado.get('token'):
        flash('Este jurado ya está en sesión.')
        return redirect(url_for('home'))
        
    if not datos['candidatas']:
        flash('Todavía no hay candidatas cargadas. Contactá al administrador.')
        return redirect(url_for('home'))
    # Generar token único y marcar sesión activa
    token = str(uuid.uuid4())
    jurado['token'] = token
    guardar_datos(datos)
    session['jurado_token'] = token
    session['jurado_id'] = jurado['id']
    
    candidatas_ordenadas = sorted(datos['candidatas'], key=lambda c: c.get('numero', 0))

    return render_template('votar.html',
                            nombre_jurado=jurado['nombre'],
                            jurado_id=jurado['id'],
                            candidatas=candidatas_ordenadas,
                            categorias=datos['categorias'])


@app.route('/guardar_votos', methods=['POST'])
def guardar_votos():
    datos = cargar_datos()
    jurado_id = session.get('jurado_id')
    jurado_token = session.get('jurado_token')

    jurado = next((j for j in datos['jurados'] if str(j['id']) == str(jurado_id)), None)
    if not jurado:
        flash('Jurado no válido.')
        return redirect(url_for('home'))

    # Validar token de sesión
    if jurado_token != jurado.get('token'):
        flash('Sesión inválida o duplicada.')
        return redirect(url_for('home'))

    if jurado.get('ha_votado'):
        flash('Este jurado ya había votado.')
        return redirect(url_for('home'))

    planilla_jurado = {
        "jurado_id": jurado['id'],
        "jurado": jurado['nombre'],
        "fecha_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "puntuaciones": {}
    }

    categorias = datos['categorias']
    for c in datos['candidatas']:
        id_c = str(c['id'])
        notas = {}
        total = 0
        for cat in categorias:
            valor = int(request.form.get(f"{cat['id']}_{id_c}", 0))
            notas[cat['id']] = valor
            total += valor
        notas['total'] = total
        planilla_jurado["puntuaciones"][id_c] = notas

    datos['votos_jurados'].append(planilla_jurado)
    jurado['ha_votado'] = True
    jurado['token'] = None  # invalidar token al finalizar
    guardar_datos(datos)

    # limpiar sesión
    session.pop('jurado_token', None)
    session.pop('jurado_id', None)

    flash(f'¡Planilla del {jurado["nombre"]} guardada con éxito!')
    return redirect(url_for('home'))
    
@app.route('/resultados')
def resultados():
    datos = cargar_datos()
    total_registrados = len(datos.get('jurados', []))
    podio, _ = calcular_resultados(datos)
    return render_template('podio.html',
                            podio=podio,
                            categorias=datos['categorias'],
                            total_jurados=len(datos['votos_jurados']),
                            total_registrados=total_registrados)


@app.route('/descargar_pdf')
def descargar_pdf():
    datos = cargar_datos()
    votos = datos['votos_jurados']
    categorias = datos['categorias']
    nombres_categorias = [cat['nombre'] for cat in categorias]

    def nombre_de(id_c):
        cand = next((c for c in datos['candidatas'] if str(c['id']) == str(id_c)), None)
        return cand['nombre'] if cand else id_c

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)

    margen = 43
    ancho_pagina, alto_pagina = letter

    c.drawImage(os.path.join(CARPETA_ACTUAL, "static", "fotos", "escudo.png"),
                margen, alto_pagina - 120, width=80, height=80, mask='auto')
    c.drawImage(os.path.join(CARPETA_ACTUAL, "static", "fotos", "logo_evento.png"),
                ancho_pagina - 160, alto_pagina - 120, width=80, height=80, mask='auto')

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(ancho_pagina / 2, alto_pagina - 40, "Resultados Finales Elección Reina")
    c.setFont("Helvetica", 12)
    c.drawCentredString(ancho_pagina / 2, alto_pagina - 60, "Colegio Secundario Olga Márquez de Aredez")

    y = alto_pagina - 150
    n_cols = len(categorias) + 2
    ancho_col = 480 // n_cols

    for v in votos:
        if y < 200:
            c.showPage()
            y = alto_pagina - 100

        c.setFont("Helvetica-Bold", 12)
        c.drawString(margen, y, f"Jurado: {v['jurado']}")
        y -= 16

        c.setFont("Helvetica", 10)
        c.drawString(margen, y, f"Fecha y hora: {v.get('fecha_hora', 'No registrada')}")
        y -= 20

        data = [["Candidata"] + nombres_categorias + ["Total"]]
        for id_c, notas in v['puntuaciones'].items():
            fila = [nombre_de(id_c)] + [notas.get(cat['id'], 0) for cat in categorias] + [notas.get('total', 0)]
            data.append(fila)

        table = Table(data, colWidths=[ancho_col] * n_cols)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
        ]))

        ancho_tabla = n_cols * ancho_col
        x_centrado = (ancho_pagina - ancho_tabla) / 2
        table.wrapOn(c, x_centrado, y)
        table.drawOn(c, x_centrado, y - 120)

        c.rect(x_centrado, y - 250, 200, 40)
        c.drawString(x_centrado + 5, y - 240, "Firma del Jurado")

        y -= 300

    c.showPage()
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(ancho_pagina / 2, alto_pagina - 50, "Tabla Resumen Final")

    podio, detalle = calcular_resultados(datos)
    detalle.sort(key=lambda x: x['promedio_general'], reverse=True)

    encabezado = ["Candidata", "Título"] + nombres_categorias + ["Promedio general"]
    data_resumen = [encabezado]

    # Crear un diccionario rápido para mapear títulos por candidata
    titulos_por_id = {str(p['id']): p.get('titulo', '') for p in podio}

    for f in detalle:
        titulo = titulos_por_id.get(str(f['id']), "")
        fila = [f['nombre'], titulo] + [f['promedio'].get(cat['id'], 0) for cat in categorias] + [f['promedio_general']]
        data_resumen.append(fila)

    n_cols_resumen = len(categorias) + 3  # ahora hay una columna extra
    col_widths = [100, 90] + [55] * (n_cols_resumen - 3) + [70]

    table_resumen = Table(data_resumen, colWidths=col_widths)
    table_resumen.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
    ]))

    ancho_tabla = sum(col_widths)
    x_centrado = (ancho_pagina - ancho_tabla) / 2
    ancho, alto = table_resumen.wrap(ancho_pagina, alto_pagina)

    y_tabla = alto_pagina - 80 - alto
    table_resumen.drawOn(c, x_centrado, y_tabla)

    y_firma = y_tabla - 70
    c.setFont("Helvetica-Bold", 12)

    c.drawString(margen, y_firma, "Firma Director/a")
    c.rect(margen, y_firma - 40, 200, 40)

    c.drawString(ancho_pagina / 2, y_firma, "Firma Vicedirector/a")
    c.rect(ancho_pagina / 2, y_firma - 40, 200, 40)

    c.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name="resultados.pdf", mimetype="application/pdf")


# ---------------------- PANEL DE ADMINISTRADOR ----------------------

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        datos = cargar_datos()
        usuario = request.form.get('usuario', '').strip()
        password = request.form.get('password', '').strip()
        admin = datos.get('admin', {})
        if usuario == admin.get('usuario') and password == admin.get('password'):
            session['admin_logueado'] = True
            return redirect(url_for('admin_panel'))
        flash('Credenciales de administrador incorrectas.')
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logueado', None)
    return redirect(url_for('home'))


@app.route('/admin/panel')
@admin_requerido
def admin_panel():
    datos = cargar_datos()
    return render_template('admin_panel.html',
                            total_candidatas=len(datos['candidatas']),
                            total_jurados=len(datos['jurados']),
                            total_votos=len(datos['votos_jurados']))


@app.route('/admin/candidatas', methods=['GET', 'POST'])
@admin_requerido
def admin_candidatas():
    datos = cargar_datos()
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        curso = request.form.get('curso', '').strip()
        archivo = request.files.get('foto_archivo')

        if not (nombre and curso):
            flash('Nombre y curso son obligatorios.')
            return redirect(url_for('admin_candidatas'))

        nuevo_id = max([c['id'] for c in datos['candidatas']], default=0) + 1
        nuevo_numero = max([c.get('numero', 0) for c in datos['candidatas']], default=0) + 1
        nombre_foto = ""

        if archivo and archivo.filename != '':
            if extension_permitida(archivo.filename):
                extension = archivo.filename.rsplit('.', 1)[1].lower()
                nombre_foto = f"candidata_{nuevo_id}.{extension}"
                os.makedirs(CARPETA_FOTOS, exist_ok=True)
                guardar_foto_optimizada(archivo, os.path.join(CARPETA_FOTOS, nombre_foto))
            else:
                flash('Formato de imagen no permitido (usá jpg, jpeg, png o webp).')
                return redirect(url_for('admin_candidatas'))

        datos['candidatas'].append({
            "id": nuevo_id, "numero": nuevo_numero, "nombre": nombre, "curso": curso, "foto": nombre_foto
        })
        guardar_datos(datos)
        flash(f'Candidata "{nombre}" agregada correctamente.')
        return redirect(url_for('admin_candidatas'))

    candidatas_ordenadas = sorted(datos['candidatas'], key=lambda c: c.get('numero', 0))
    return render_template('admin_candidatas.html', candidatas=candidatas_ordenadas)


@app.route('/admin/candidatas/editar/<int:id_candidata>', methods=['POST'])
@admin_requerido
def editar_candidata(id_candidata):
    datos = cargar_datos()
    candidata = next((c for c in datos['candidatas'] if c['id'] == id_candidata), None)
    if not candidata:
        flash('Candidata no encontrada.')
        return redirect(url_for('admin_candidatas'))

    nombre = request.form.get('nombre', '').strip()
    curso = request.form.get('curso', '').strip()
    numero = request.form.get('numero', '').strip()
    archivo = request.files.get('foto_archivo')

    if nombre:
        candidata['nombre'] = nombre
    if curso:
        candidata['curso'] = curso
    if numero:
        try:
            candidata['numero'] = int(numero)
        except ValueError:
            flash('El número de postulante debe ser un número.')
            return redirect(url_for('admin_candidatas'))

    if archivo and archivo.filename != '':
        if extension_permitida(archivo.filename):
            extension = archivo.filename.rsplit('.', 1)[1].lower()
            nombre_foto = f"candidata_{id_candidata}.{extension}"
            os.makedirs(CARPETA_FOTOS, exist_ok=True)
            archivo.save(os.path.join(CARPETA_FOTOS, nombre_foto))
            candidata['foto'] = nombre_foto
        else:
            flash('Formato de imagen no permitido (usá jpg, jpeg, png o webp).')
            return redirect(url_for('admin_candidatas'))

    guardar_datos(datos)
    flash(f'Candidata "{candidata["nombre"]}" actualizada correctamente.')
    return redirect(url_for('admin_candidatas'))


@app.route('/admin/candidatas/eliminar/<int:id_candidata>', methods=['POST'])
@admin_requerido
def eliminar_candidata(id_candidata):
    datos = cargar_datos()
    datos['candidatas'] = [c for c in datos['candidatas'] if c['id'] != id_candidata]
    guardar_datos(datos)
    flash('Candidata eliminada.')
    return redirect(url_for('admin_candidatas'))


@app.route('/admin/categorias', methods=['GET', 'POST'])
@admin_requerido
def admin_categorias():
    datos = cargar_datos()
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        otorga_titulo = request.form.get('otorga_titulo') == 'on'

        if not nombre:
            flash('El nombre de la categoría es obligatorio.')
            return redirect(url_for('admin_categorias'))

        id_cat = slugify(nombre)
        if any(cat['id'] == id_cat for cat in datos['categorias']):
            flash('Ya existe una categoría con ese nombre.')
            return redirect(url_for('admin_categorias'))

        if datos.get('votos_jurados'):
            flash('No se pueden agregar categorías si ya hay votos cargados. Reiniciá la votación primero.')
            return redirect(url_for('admin_categorias'))

        datos['categorias'].append({"id": id_cat, "nombre": nombre, "otorga_titulo": otorga_titulo})
        guardar_datos(datos)
        flash(f'Categoría "{nombre}" agregada correctamente.')
        return redirect(url_for('admin_categorias'))

    return render_template('admin_categorias.html', categorias=datos['categorias'])


@app.route('/admin/categorias/eliminar/<id_categoria>', methods=['POST'])
@admin_requerido
def eliminar_categoria(id_categoria):
    datos = cargar_datos()
    if len(datos['categorias']) <= 1:
        flash('Debe existir al menos una categoría.')
        return redirect(url_for('admin_categorias'))
    if datos.get('votos_jurados'):
        flash('No se pueden eliminar categorías si ya hay votos cargados. Reiniciá la votación primero.')
        return redirect(url_for('admin_categorias'))
    datos['categorias'] = [c for c in datos['categorias'] if c['id'] != id_categoria]
    guardar_datos(datos)
    flash('Categoría eliminada.')
    return redirect(url_for('admin_categorias'))


@app.route('/admin/categorias/titulo/<id_categoria>', methods=['POST'])
@admin_requerido
def alternar_titulo_categoria(id_categoria):
    datos = cargar_datos()
    for cat in datos['categorias']:
        if cat['id'] == id_categoria:
            cat['otorga_titulo'] = not cat.get('otorga_titulo', False)
    guardar_datos(datos)
    return redirect(url_for('admin_categorias'))


@app.route('/admin/jurados', methods=['GET', 'POST'])
@admin_requerido
def admin_jurados():
    datos = cargar_datos()
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        usuario = request.form.get('usuario', '').strip()
        password = request.form.get('password', '').strip()
        if nombre and usuario and password:
            if any(j['usuario'] == usuario for j in datos['jurados']):
                flash('Ya existe un jurado con ese usuario.')
            else:
                nuevo_id = max([j['id'] for j in datos['jurados']], default=0) + 1
                datos['jurados'].append({
                    "id": nuevo_id, "nombre": nombre, "usuario": usuario,
                    "password": password, "ha_votado": False
                })
                guardar_datos(datos)
                flash(f'Jurado "{nombre}" agregado correctamente.')
        else:
            flash('Todos los campos son obligatorios.')
        return redirect(url_for('admin_jurados'))
    return render_template('admin_jurados.html', jurados=datos['jurados'])


@app.route('/admin/jurados/eliminar/<int:id_jurado>', methods=['POST'])
@admin_requerido
def eliminar_jurado(id_jurado):
    datos = cargar_datos()
    datos['jurados'] = [j for j in datos['jurados'] if j['id'] != id_jurado]
    guardar_datos(datos)
    flash('Jurado eliminado.')
    return redirect(url_for('admin_jurados'))


@app.route('/admin/jurados/resetear/<int:id_jurado>', methods=['POST'])
@admin_requerido
def resetear_jurado(id_jurado):
    datos = cargar_datos()
    for j in datos['jurados']:
        if j['id'] == id_jurado:
            j['ha_votado'] = False
    datos['votos_jurados'] = [v for v in datos['votos_jurados'] if v.get('jurado_id') != id_jurado]
    guardar_datos(datos)
    flash('Se habilitó al jurado para volver a votar.')
    return redirect(url_for('admin_jurados'))


@app.route('/admin/reiniciar')
@admin_requerido
def reiniciar():
    datos = cargar_datos()
    datos['votos_jurados'] = []
    for j in datos['jurados']:
        j['ha_votado'] = False
    guardar_datos(datos)
    flash("Votación reiniciada con éxito.")
    return redirect(url_for('admin_panel'))


if __name__ == '__main__':
    try:
        from waitress import serve
        print("Servidor iniciado en http://0.0.0.0:5000 (modo producción, varios jurados a la vez)")
        serve(app, host='0.0.0.0', port=5000, threads=8)
    except ImportError:
        print("AVISO: instalá 'waitress' para mejor rendimiento (ver instrucciones).")
        print("Usando el servidor de desarrollo de Flask mientras tanto...")
        app.run(host='0.0.0.0', port=5000, threaded=True, debug=False)
