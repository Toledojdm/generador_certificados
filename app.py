import os
import json
import uuid
from flask import Flask, request, jsonify, send_from_directory
from jinja2 import Environment, FileSystemLoader, Template, exceptions
from weasyprint import HTML

app = Flask(__name__)

CARPETA_PLANTILLAS = 'plantillas'
CARPETA_SUBIDAS = 'archivos_subidos'
CARPETA_GENERADOS = 'archivos_generados'

os.makedirs(CARPETA_SUBIDAS, exist_ok=True)
os.makedirs(CARPETA_GENERADOS, exist_ok=True)

env_jinja = Environment(loader=FileSystemLoader(CARPETA_PLANTILLAS))


@app.route('/convertir-json-a-pdf', methods=['POST'])
def convertir_json_a_pdf():
    if 'json_data' not in request.form:
        return jsonify({"error": "No se encontró el campo 'json_data' en el formulario."}), 400

    try:
        datos_json = json.loads(request.form['json_data'])
    except json.JSONDecodeError:
        return jsonify({"error": "El JSON proporcionado no es válido."}), 400

    ruta_plantilla_temporal = None
    try:
        if 'plantilla' in request.files and request.files['plantilla'].filename != '':
            archivo_plantilla = request.files['plantilla']
            
            nombre_unico = str(uuid.uuid4()) + ".html"
            ruta_plantilla_temporal = os.path.join(CARPETA_SUBIDAS, nombre_unico)
            archivo_plantilla.save(ruta_plantilla_temporal)
            
            with open(ruta_plantilla_temporal, 'r', encoding='utf-8') as f:
                plantilla_obj = Template(f.read())
        else:
            plantilla_obj = env_jinja.get_template('predeterminada.html')

        html_renderizado = plantilla_obj.render(datos_json)
        
        nombre_pdf = str(uuid.uuid4()) + ".pdf"
        ruta_pdf_salida = os.path.join(CARPETA_GENERADOS, nombre_pdf)
        
        HTML(string=html_renderizado).write_pdf(ruta_pdf_salida)
        
        return send_from_directory(CARPETA_GENERADOS, nombre_pdf, as_attachment=True)

    except exceptions.TemplateSyntaxError as e:
        return jsonify({"error": f"Error de sintaxis en la plantilla: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": f"Ocurrió un error en el procesamiento: {str(e)}"}), 500
    finally:
        if ruta_plantilla_temporal and os.path.exists(ruta_plantilla_temporal):
            os.remove(ruta_plantilla_temporal)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)