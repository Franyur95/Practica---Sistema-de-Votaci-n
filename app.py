from flask import Flask, render_template, request, redirect, url_for, flash
import json
import os

app = Flask(__name__)
app.secret_key = 'clave_secreta_olga_marquez'

# Detecta automáticamente la carpeta del script para evitar fallas de rutas en Windows
CARPETA_ACTUAL = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(CARPETA_ACTUAL, 'base_datos.json')

def cargar_datos():
    # Si el archivo no existe, lo crea automáticamente con las 10 candidatas y sus fotos
    if not os.path.exists(DB_FILE):
        datos_iniciales = {
            "candidatas": [
                {"id": 1, "nombre": "Sofía Benítez", "curso": "1er Año", "foto": "1.jpg"},
                {"id": 2, "nombre": "Valentina Giménez", "curso": "2do Año", "foto": "2.jpg"},
                {"id": 3, "nombre": "Martina Alarcón", "curso": "3er Año", "foto": "3.jpg"},
                {"id": 4, "nombre": "Camila Mamani", "curso": "4to Año 1ra", "foto": "4.jpg"},
                {"id": 5, "nombre": "Lucía Flores", "curso": "4to Año 2da", "foto": "5.jpg"},
                {"id": 6, "nombre": "Antonella Solís", "curso": "5to Año 1ra", "foto": "6.jpg"},
                {"id": 7, "nombre": "Zoe Gutiérrez", "curso": "5to Año 2da", "foto": "7.jpg"},
                {"id": 8, "nombre": "Agostina Tolaba", "curso": "5to Año 3ra", "foto": "8.jpg"},
                {"id": 9, "nombre": "Micaela Cruz", "curso": "6to Año 1ra", "foto": "9.jpg"},
                {"id": 10, "nombre": "Abril Vázquez", "curso": "6to Año 2da", "foto": "10.jpg"}
            ],
            "votos_jurados": []
        }
        guardar_datos(datos_iniciales)
        return datos_iniciales
        
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def guardar_datos(datos):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(datos, f, indent=4, ensure_ascii=False)

@app.route('/')
def home():
    datos = cargar_datos()
    cantidad_jurados = len(datos.get('votos_jurados', []))
    return render_template('login_jurado.html', cantidad_jurados=cantidad_jurados)

@app.route('/evaluacion', methods=['POST'])
def evaluacion():
    nombre_jurado = request.form.get('nombre_jurado')
    datos = cargar_datos()
    
    if len(datos['votos_jurados']) >= 5:
        flash('Ya han votado los 5 jurados reglamentarios.')
        return redirect(url_for('resultados'))
        
    return render_template('votar.html', nombre_jurado=nombre_jurado, candidatas=datos['candidatas'])

@app.route('/guardar_votos', methods=['POST'])
def guardar_votos():
    datos = cargar_datos()
    nombre_jurado = request.form.get('nombre_jurado')
    
    planilla_jurado = {"jurado": nombre_jurado, "puntuaciones": {}}
    
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
    guardar_datos(datos)
    
    flash(f'¡Planilla del {nombre_jurado} guardada con éxito!')
    return redirect(url_for('home'))

@app.route('/resultados')
def resultados():
    datos = cargar_datos()
    candidatas = datos['candidatas']
    votos = datos['votos_jurados']
    
    resultados_candidatas = {}
    for c in candidatas:
        resultados_candidatas[c['id']] = {
            'id': c['id'],
            'nombre': c['nombre'],
            'curso': c['curso'],
            'acumulado_total': 0,
            'acumulado_elegancia': 0,
            'acumulado_simpatia': 0
        }
    
    for v in votos:
        for id_c, notas in v['puntuaciones'].items():
            id_int = int(id_c)
            if id_int in resultados_candidatas:
                resultados_candidatas[id_int]['acumulado_total'] += notas['total']
                resultados_candidatas[id_int]['acumulado_elegancia'] += notas['elegancia']
                resultados_candidatas[id_int]['acumulado_simpatia'] += notas['simpatia']
                
    lista_candidatas = list(resultados_candidatas.values())
    podio = []
    
    if len(votos) > 0:
        # 1. Determinar la REINA
        lista_candidatas.sort(key=lambda x: x['acumulado_total'], reverse=True)
        reina = lista_candidatas.pop(0)
        reina['titulo'] = "👑 Reina Escolar 👑"
        reina['score_mostrar'] = f"{reina['acumulado_total']} pts totales"
        podio.append(reina)
        
        # 2. Determinar MISS ELEGANCIA
        lista_candidatas.sort(key=lambda x: x['acumulado_elegancia'], reverse=True)
        miss_elegancia = lista_candidatas.pop(0)
        miss_elegancia['titulo'] = "✨ Miss Elegancia ✨"
        miss_elegancia['score_mostrar'] = f"{miss_elegancia['acumulado_elegancia']} pts"
        podio.append(miss_elegancia)
        
        # 3. Determinar MISS SIMPATÍA
        lista_candidatas.sort(key=lambda x: x['acumulado_simpatia'], reverse=True)
        miss_simpatia = lista_candidatas.pop(0)
        miss_simpatia['titulo'] = "😊 Miss Simpatía 😊"
        miss_simpatia['score_mostrar'] = f"{miss_simpatia['acumulado_simpatia']} pts"
        podio.append(miss_simpatia)

    return render_template('podio.html', podio=podio, total_jurados=len(votos))

@app.route('/reiniciar')
def reiniciar():
    datos = cargar_datos()
    datos['votos_jurados'] = []
    guardar_datos(datos)
    flash("Votación reiniciada con éxito.")
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)