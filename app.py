from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
import json
import os
import io
import threading
from functools import wraps
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors

app = Flask(__name__)
app.secret_key = 'clave_secreta_olga_marquez'

CARPETA_ACTUAL = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(CARPETA_ACTUAL, 'base_datos.json')
lock_datos = threading.Lock()

CARPETA_FOTOS = os.path.join(CARPETA_ACTUAL, 'static', 'fotos')
EXTENSIONES_PERMITIDAS = {'png', 'jpg', 'jpeg', 'webp'}

def extension_permitida(nombre_archivo):
    return '.' in nombre_archivo and nombre_archivo.rsplit('.', 1)[1].lower() in EXTENSIONES_PERMITIDAS

lock_datos = threading.Lock()  # evita choques al escribir el JSON con varios jurados a la vez


def cargar_datos():
    if not os.path.exists(DB_FILE):
        datos_iniciales = {
            "candidatas": [],
            "jurados": [],
            "votos_jurados": [],
            "admin": {"usuario": "admin", "password": "1234"}
        }
        guardar_datos(datos_iniciales)
        return datos_iniciales

    with open(DB_FILE, 'r', encoding='utf-8') as f:
        datos = json.load(f)

    # Migración: asegura que existan las claves nuevas si venís de una base vieja
    datos.setdefault('jurados', [])
    datos.setdefault('admin', {"usuario": "admin", "password": "olga2026"})
    return datos


def guardar_datos(datos):
    with lock_datos:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(datos, f, indent=4, ensure_ascii=False)


def admin_requerido(f):
    @wraps(f)
    def decorador(*args, **kwargs):
        if not session.get('admin_logueado'):
            flash('Necesitás iniciar sesión como administrador.')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorador


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

    if not datos['candidatas']:
        flash('Todavía no hay candidatas cargadas. Contactá al administrador.')
        return redirect(url_for('home'))

    return render_template('votar.html',
                            nombre_jurado=jurado['nombre'],
                            jurado_id=jurado['id'],
                            candidatas=datos['candidatas'])


@app.route('/guardar_votos', methods=['POST'])
def guardar_votos():
    datos = cargar_datos()
    nombre_jurado = request.form.get('nombre_jurado')
    jurado_id = request.form.get('jurado_id')

    jurado = next((j for j in datos['jurados'] if str(j['id']) == str(jurado_id)), None)
    if not jurado:
        flash('Jurado no válido.')
        return redirect(url_for('home'))
    if jurado.get('ha_votado'):
        flash('Este jurado ya había votado.')
        return redirect(url_for('home'))

    planilla_jurado = {"jurado_id": jurado['id'], "jurado": nombre_jurado, "puntuaciones": {}}

    for c in datos['candidatas']:
        id_c = str(c['id'])
        try:
            belleza = int(request.form.get(f'belleza_{id_c}', 0))
            elegancia = int(request.form.get(f'elegancia_{id_c}', 0))
            simpatia = int(request.form.get(f'simpatia_{id_c}', 0))
            postura = int(request.form.get(f'postura_{id_c}', 0))

            planilla_jurado["puntuaciones"][id_c] = {
                "belleza": belleza,
                "elegancia": elegancia,
                "simpatia": simpatia,
                "postura": postura,
                "total": belleza + elegancia + simpatia + postura
            }
        except (TypeError, ValueError):
            flash("Error en los datos ingresados.")
            return redirect(url_for('home'))

    datos['votos_jurados'].append(planilla_jurado)
    jurado['ha_votado'] = True
    guardar_datos(datos)

    flash(f'¡Planilla del {nombre_jurado} guardada con éxito!')
    return redirect(url_for('home'))


@app.route('/resultados')
def resultados():
    datos = cargar_datos()
    candidatas = datos['candidatas']
    votos = datos['votos_jurados']
    total_registrados = len(datos.get('jurados', []))

    resultados_candidatas = {}
    for c in candidatas:
        resultados_candidatas[c['id']] = {
            'id': c['id'],
            'nombre': c['nombre'],
            'curso': c['curso'],
            'foto': c.get('foto', ''),
            'acumulado_total': 0,
            'acumulado_belleza': 0,
            'acumulado_elegancia': 0,
            'acumulado_simpatia': 0,
            'acumulado_postura': 0
        }

    for v in votos:
        for id_c, notas in v['puntuaciones'].items():
            id_int = int(id_c)
            if id_int in resultados_candidatas:
                resultados_candidatas[id_int]['acumulado_total'] += notas['total']
                resultados_candidatas[id_int]['acumulado_belleza'] += notas['belleza']
                resultados_candidatas[id_int]['acumulado_elegancia'] += notas['elegancia']
                resultados_candidatas[id_int]['acumulado_simpatia'] += notas['simpatia']
                resultados_candidatas[id_int]['acumulado_postura'] += notas['postura']

    lista_candidatas = list(resultados_candidatas.values())
    podio = []

    if len(votos) > 0 and len(lista_candidatas) >= 3:
        # Reina: total, con desempate en cascada (belleza > elegancia > simpatia > postura)
        lista_candidatas.sort(key=lambda x: (
            x['acumulado_total'], x['acumulado_belleza'],
            x['acumulado_elegancia'], x['acumulado_simpatia'], x['acumulado_postura']
        ), reverse=True)
        reina = lista_candidatas.pop(0)
        empate_reina = len(lista_candidatas) > 0 and lista_candidatas[0]['acumulado_total'] == reina['acumulado_total']
        reina['titulo'] = "👑 Reina Escolar 👑"
        reina['score_mostrar'] = f"{reina['acumulado_total']} pts totales"
        reina['empate'] = empate_reina
        podio.append(reina)

        # Primera princesa: elegancia, con desempate por total
        lista_candidatas.sort(key=lambda x: (x['acumulado_elegancia'], x['acumulado_total']), reverse=True)
        miss_elegancia = lista_candidatas.pop(0)
        empate_elegancia = len(lista_candidatas) > 0 and lista_candidatas[0]['acumulado_elegancia'] == miss_elegancia['acumulado_elegancia']
        miss_elegancia['titulo'] = "✨ Primera Princesa ✨"
        miss_elegancia['score_mostrar'] = f"{miss_elegancia['acumulado_elegancia']} pts"
        miss_elegancia['empate'] = empate_elegancia
        podio.append(miss_elegancia)

        # Segunda princesa: simpatía, con desempate por total
        lista_candidatas.sort(key=lambda x: (x['acumulado_simpatia'], x['acumulado_total']), reverse=True)
        miss_simpatia = lista_candidatas.pop(0)
        empate_simpatia = len(lista_candidatas) > 0 and lista_candidatas[0]['acumulado_simpatia'] == miss_simpatia['acumulado_simpatia']
        miss_simpatia['titulo'] = "😊 Segunda Princesa 😊"
        miss_simpatia['score_mostrar'] = f"{miss_simpatia['acumulado_simpatia']} pts"
        miss_simpatia['empate'] = empate_simpatia
        podio.append(miss_simpatia)

    return render_template('podio.html', podio=podio,
                            total_jurados=len(votos),
                            total_registrados=total_registrados)

@app.route('/descargar_pdf')
def descargar_pdf():
    datos = cargar_datos()
    votos = datos['votos_jurados']

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

    for v in votos:
        if y < 200:
            c.showPage()
            y = alto_pagina - 100

        c.setFont("Helvetica-Bold", 12)
        c.drawString(margen, y, f"Jurado: {v['jurado']}")
        y -= 20

        data = [["Candidata", "Belleza", "Elegancia", "Simpatía", "Postura", "Total"]]
        for id_c, notas in v['puntuaciones'].items():
            fila = [id_c, notas['belleza'], notas['elegancia'],
                    notas['simpatia'], notas['postura'], notas['total']]
            data.append(fila)

        table = Table(data, colWidths=[70] * 6)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER')
        ]))

        ancho_tabla = 6 * 70
        x_centrado = (ancho_pagina - ancho_tabla) / 2
        table.wrapOn(c, x_centrado, y)
        table.drawOn(c, x_centrado, y - 200)

        c.rect(x_centrado, y - 250, 200, 40)
        c.drawString(x_centrado + 5, y - 240, "Firma del Jurado")

        y -= 300

    c.showPage()
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(ancho_pagina / 2, alto_pagina - 50, "Tabla Resumen Final")

    candidatas = datos['candidatas']
    resumen = []
    for candi in candidatas:
        fila = [candi['nombre']]
        total_final = 0
        for v in votos:
            puntaje = v['puntuaciones'].get(str(candi['id']), {}).get('total', 0)
            fila.append(puntaje)
            total_final += puntaje
        fila.append(total_final)
        resumen.append(fila)

    resumen.sort(key=lambda x: x[-1], reverse=True)

    encabezado = ["Candidata"] + [f"Jurado {i+1}" for i in range(len(votos))] + ["Total"]
    data_resumen = [encabezado]
    data_resumen.extend(resumen)

    col_widths = [90] + [60] * len(votos) + [60]
    table_resumen = Table(data_resumen, colWidths=col_widths)
    table_resumen.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER')
    ]))

    ancho_tabla = sum(col_widths)
    x_centrado = (ancho_pagina - ancho_tabla) / 2
    table_resumen.wrapOn(c, x_centrado, alto_pagina - 100)
    table_resumen.drawOn(c, x_centrado, alto_pagina - 500)

    c.showPage()
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margen, 120, "Firma Director/a")
    c.rect(margen, 100, 200, 40)

    c.drawString(ancho_pagina / 2, 120, "Firma Vicedirector/a")
    c.rect(ancho_pagina / 2, 100, 200, 40)

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
        nombre_foto = ""

        if archivo and archivo.filename != '':
            if extension_permitida(archivo.filename):
                extension = archivo.filename.rsplit('.', 1)[1].lower()
                nombre_foto = f"candidata_{nuevo_id}.{extension}"
                os.makedirs(CARPETA_FOTOS, exist_ok=True)
                archivo.save(os.path.join(CARPETA_FOTOS, nombre_foto))
            else:
                flash('Formato de imagen no permitido (usá jpg, jpeg, png o webp).')
                return redirect(url_for('admin_candidatas'))

        datos['candidatas'].append({
            "id": nuevo_id, "nombre": nombre, "curso": curso, "foto": nombre_foto
        })
        guardar_datos(datos)
        flash(f'Candidata "{nombre}" agregada correctamente.')
        return redirect(url_for('admin_candidatas'))

    return render_template('admin_candidatas.html', candidatas=datos['candidatas'])


@app.route('/admin/candidatas/eliminar/<int:id_candidata>', methods=['POST'])
@admin_requerido
def eliminar_candidata(id_candidata):
    datos = cargar_datos()
    datos['candidatas'] = [c for c in datos['candidatas'] if c['id'] != id_candidata]
    guardar_datos(datos)
    flash('Candidata eliminada.')
    return redirect(url_for('admin_candidatas'))


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
    app.run(host='0.0.0.0', debug=True)