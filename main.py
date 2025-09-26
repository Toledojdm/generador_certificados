import os
import json
import uuid
import io
import zipfile
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import List

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# --- Configuración ---
load_dotenv()

app = FastAPI(
    title="API de Generación de Certificados",
    description="Un servicio para crear plantillas de certificados y generar lotes de documentos en PDF."
)

# --- Definición de Carpetas ---
CARPETA_SUBIDAS = 'archivos_subidos'
CARPETA_GENERADOS = 'archivos_generados'
CARPETA_PLANTILLAS_CONFIG = 'plantillas_config' # Carpeta para guardar plantillas y sus datos
CARPETA_FUENTES = 'fuentes'

os.makedirs(CARPETA_SUBIDAS, exist_ok=True)
os.makedirs(CARPETA_GENERADOS, exist_ok=True)
os.makedirs(CARPETA_PLANTILLAS_CONFIG, exist_ok=True)
os.makedirs(CARPETA_FUENTES, exist_ok=True)


# --- Endpoints de la API ---

@app.post("/crear-plantilla-certificado", tags=["Flujo de Certificados"])
async def crear_plantilla_certificado(
    y_coord: int = Form(..., description="Coordenada Y (vertical) donde se centrará el texto."),
    tamano_fuente: int = Form(..., description="Tamaño de la fuente del texto."),
    plantilla_png: UploadFile = File(..., description="Imagen de fondo del certificado en formato PNG."),
    fuente_ttf: UploadFile = File(..., description="Archivo de fuente .TTF o .OTF para el texto.")
):
    """
    Paso 1: Sube la imagen de fondo, la fuente y las coordenadas.
    Esto crea una plantilla y devuelve un ID único para usar en el siguiente paso.
    """
    if not plantilla_png.content_type == "image/png":
        raise HTTPException(status_code=400, detail="El archivo de plantilla debe ser una imagen PNG.")
    if not fuente_ttf.filename.lower().endswith(('.ttf', '.otf')):
        raise HTTPException(status_code=400, detail="El archivo de fuente debe ser .TTF o .OTF.")

    plantilla_id = str(uuid.uuid4())
    ruta_plantilla = os.path.join(CARPETA_PLANTILLAS_CONFIG, plantilla_id)
    os.makedirs(ruta_plantilla)

    try:
        # Guardar la imagen de la plantilla
        ruta_png = os.path.join(ruta_plantilla, "fondo.png")
        with open(ruta_png, "wb") as buffer:
            buffer.write(await plantilla_png.read())

        # Guardar el archivo de fuente
        ruta_fuente = os.path.join(ruta_plantilla, fuente_ttf.filename)
        with open(ruta_fuente, "wb") as buffer:
            buffer.write(await fuente_ttf.read())

        # Guardar el archivo de configuración
        config = {
            "y_coord": y_coord,
            "tamano_fuente": tamano_fuente,
            "nombre_archivo_fuente": fuente_ttf.filename
        }
        ruta_config = os.path.join(ruta_plantilla, "config.json")
        with open(ruta_config, "w") as f:
            json.dump(config, f)

        return {
            "message": "Plantilla creada exitosamente.",
            "plantilla_id": plantilla_id
        }
    except Exception as e:
        # Limpieza en caso de error
        if os.path.exists(ruta_plantilla):
            import shutil
            shutil.rmtree(ruta_plantilla)
        raise HTTPException(status_code=500, detail=f"No se pudo crear la plantilla: {e}")


@app.post("/generar-certificados", tags=["Flujo de Certificados"])
async def generar_certificados(
    plantilla_id: str = Form(..., description="El ID de la plantilla creada previamente."),
    nombres: List[str] = Form(..., description="Lista de nombres para generar los certificados.")
):
    """
    Paso 2: Usa el ID de la plantilla y una lista de nombres para generar los PDFs.
    Devuelve un archivo ZIP con todos los certificados.
    """
    ruta_plantilla = os.path.join(CARPETA_PLANTILLAS_CONFIG, plantilla_id)
    if not os.path.isdir(ruta_plantilla):
        raise HTTPException(status_code=404, detail="El ID de la plantilla no fue encontrado.")

    ruta_config = os.path.join(ruta_plantilla, "config.json")
    ruta_png = os.path.join(ruta_plantilla, "fondo.png")

    try:
        with open(ruta_config, 'r') as f:
            config = json.load(f)
        
        y_coord = config["y_coord"]
        tamano_fuente = config["tamano_fuente"]
        ruta_fuente = os.path.join(ruta_plantilla, config["nombre_archivo_fuente"])
        
        fuente = ImageFont.truetype(ruta_fuente, tamano_fuente)
        
        # Crear un archivo ZIP en memoria
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for nombre in nombres:
                # Abrir la imagen de fondo original para cada certificado
                imagen_base = Image.open(ruta_png).convert("RGB")
                dibujo = ImageDraw.Draw(imagen_base)
                
                # Calcular el ancho del texto para centrarlo
                ancho_imagen, _ = imagen_base.size
                bbox = dibujo.textbbox((0, 0), nombre, font=fuente)
                ancho_texto = bbox[2] - bbox[0]
                
                # Calcular la coordenada X para centrar el texto
                x_coord = (ancho_imagen - ancho_texto) / 2
                
                dibujo.text((x_coord, y_coord), nombre, font=fuente, fill=(0, 0, 0)) # Texto en negro

                # Guardar el PDF en un buffer de memoria temporal
                pdf_buffer = io.BytesIO()
                imagen_base.save(pdf_buffer, "PDF", resolution=100.0)
                pdf_buffer.seek(0)
                
                # Añadir el PDF en memoria al archivo ZIP
                nombre_archivo_pdf = f"certificado_{nombre.replace(' ', '_')}.pdf"
                zip_file.writestr(nombre_archivo_pdf, pdf_buffer.read())

        zip_buffer.seek(0)
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=certificados_{plantilla_id}.zip"}
        )

    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Faltan archivos en la configuración de la plantilla.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ocurrió un error al generar los certificados: {e}")