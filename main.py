import os
import json
import uuid
import io
import zipfile
import shutil
from typing import List

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# --- Configuración Inicial ---
load_dotenv()

app = FastAPI(
    title="API de Generación de Certificados",
    description="Un servicio para crear plantillas y generar lotes de certificados en PDF."
)

# --- Definición de Carpetas ---
CARPETA_GENERADOS = 'archivos_generados'
CARPETA_PLANTILLAS_CONFIG = 'plantillas_config'
CARPETA_FUENTES = 'fuentes'

os.makedirs(CARPETA_GENERADOS, exist_ok=True)
os.makedirs(CARPETA_PLANTILLAS_CONFIG, exist_ok=True)
os.makedirs(CARPETA_FUENTES, exist_ok=True)


# --- Endpoints de la API ---

@app.get("/", response_class=HTMLResponse, tags=["Interfaz de Usuario"])
async def leer_interfaz():
    """Sirve la página web principal para interactuar con la API."""
    try:
        with open("frontend/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="El archivo frontend/index.html no fue encontrado.")


@app.post("/crear-plantilla-certificado", tags=["Flujo de Certificados"])
async def crear_plantilla_certificado(
    y_coord: int = Form(..., description="Coordenada Y (vertical) donde se centrará el texto."),
    tamano_fuente: int = Form(..., description="Tamaño de la fuente del texto."),
    plantilla_png: UploadFile = File(..., description="Imagen de fondo del certificado en formato PNG."),
    fuente_ttf: UploadFile = File(..., description="Archivo de fuente .TTF o .OTF para el texto.")
):
    """Paso 1: Crea una plantilla y devuelve un ID único para usar en el siguiente paso."""
    if not plantilla_png.content_type == "image/png":
        raise HTTPException(status_code=400, detail="El archivo de plantilla debe ser una imagen PNG.")
    if not fuente_ttf.filename.lower().endswith(('.ttf', '.otf')):
        raise HTTPException(status_code=400, detail="El archivo de fuente debe ser .TTF o .OTF.")

    plantilla_id = str(uuid.uuid4())
    ruta_plantilla = os.path.join(CARPETA_PLANTILLAS_CONFIG, plantilla_id)
    os.makedirs(ruta_plantilla)

    try:
        ruta_png = os.path.join(ruta_plantilla, "fondo.png")
        with open(ruta_png, "wb") as buffer:
            buffer.write(await plantilla_png.read())

        ruta_fuente = os.path.join(ruta_plantilla, fuente_ttf.filename)
        with open(ruta_fuente, "wb") as buffer:
            buffer.write(await fuente_ttf.read())

        config = {
            "y_coord": y_coord,
            "tamano_fuente": tamano_fuente,
            "nombre_archivo_fuente": fuente_ttf.filename
        }
        ruta_config = os.path.join(ruta_plantilla, "config.json")
        with open(ruta_config, "w") as f:
            json.dump(config, f)

        return {"message": "Plantilla creada exitosamente.", "plantilla_id": plantilla_id}
    except Exception as e:
        if os.path.exists(ruta_plantilla):
            shutil.rmtree(ruta_plantilla)
        raise HTTPException(status_code=500, detail=f"No se pudo crear la plantilla: {e}")


@app.post("/generar-certificados", tags=["Flujo de Certificados"])
async def generar_certificados(
    plantilla_id: str = Form(..., description="El ID de la plantilla creada previamente."),
    nombres: List[str] = Form(..., description="Lista de nombres para generar los certificados.")
):
    """Paso 2: Usa el ID de la plantilla y una lista de nombres para generar los PDFs en un ZIP."""
    ruta_plantilla = os.path.join(CARPETA_PLANTILLAS_CONFIG, plantilla_id)
    if not os.path.isdir(ruta_plantilla):
        raise HTTPException(status_code=404, detail="El ID de la plantilla no fue encontrado.")

    try:
        with open(os.path.join(ruta_plantilla, "config.json"), 'r') as f:
            config = json.load(f)
        
        ruta_png = os.path.join(ruta_plantilla, "fondo.png")
        ruta_fuente = os.path.join(ruta_plantilla, config["nombre_archivo_fuente"])
        fuente = ImageFont.truetype(ruta_fuente, config["tamano_fuente"])
        
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for nombre in nombres:
                imagen_base = Image.open(ruta_png).convert("RGB")
                dibujo = ImageDraw.Draw(imagen_base)
                
                ancho_imagen, _ = imagen_base.size
                bbox = dibujo.textbbox((0, 0), nombre, font=fuente)
                ancho_texto = bbox[2] - bbox[0]
                x_coord = (ancho_imagen - ancho_texto) / 2
                
                dibujo.text((x_coord, config["y_coord"]), nombre, font=fuente, fill=(0, 0, 0))

                pdf_buffer = io.BytesIO()
                imagen_base.save(pdf_buffer, "PDF", resolution=100.0)
                pdf_buffer.seek(0)
                
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


# --- Punto de Entrada para Ejecución con Uvicorn ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)