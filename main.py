import os
import json
import uuid
import io
import zipfile
import smtplib
import sqlite3
import string
import random
import pandas as pd
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# --- Configuración Inicial ---
load_dotenv()

app = FastAPI(
    title="API de Generación y Distribución de Certificados",
    description="Una solución completa para crear plantillas, gestionar participantes y enviar certificados."
)

# --- Definición de Constantes ---
CARPETA_PLANTILLAS_CONFIG = 'plantillas_config'
CARPETA_FUENTES = 'fuentes'
DEFAULT_FONT_PATH = os.path.join(CARPETA_FUENTES, "default_font.ttf")
DATABASE_NAME = "participantes.db"

# Crear directorios necesarios
os.makedirs(CARPETA_PLANTILLAS_CONFIG, exist_ok=True)
os.makedirs(CARPETA_FUENTES, exist_ok=True)

# --- Gestión de la Base de Datos (SQLite) ---

def init_db():
    """Inicializa la base de datos y crea las tablas si no existen."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lotes (
            id TEXT PRIMARY KEY,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS participantes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lote_id TEXT NOT NULL,
            nombre TEXT NOT NULL,
            correo TEXT NOT NULL,
            clave TEXT NOT NULL UNIQUE,
            FOREIGN KEY (lote_id) REFERENCES lotes (id)
        )
    ''')
    conn.commit()
    conn.close()

def generar_clave_unica(cursor, longitud=8):
    """Genera una clave alfanumérica única que no exista en la BD."""
    caracteres = string.ascii_uppercase + string.digits
    while True:
        clave = ''.join(random.choice(caracteres) for _ in range(longitud))
        cursor.execute("SELECT 1 FROM participantes WHERE clave = ?", (clave,))
        if cursor.fetchone() is None:
            return clave

# Evento de inicio: se ejecuta una vez cuando FastAPI arranca
@app.on_event("startup")
async def startup_event():
    init_db()
    if not os.path.exists(DEFAULT_FONT_PATH):
        print(f"ADVERTENCIA: No se encontró la fuente por defecto en '{DEFAULT_FONT_PATH}'. El endpoint de creación de plantillas fallará si no se sube una fuente.")

# --- Endpoints de la API ---

@app.post("/crear-plantilla", tags=["Gestión de Plantillas"])
async def crear_plantilla(
    y_coord: int = Form(..., description="Coordenada Y (vertical) donde se centrará el texto."),
    tamano_fuente: int = Form(..., description="Tamaño de la fuente del texto."),
    plantilla_png: UploadFile = File(..., description="Imagen de fondo del certificado en formato PNG."),
    fuente_ttf: Optional[UploadFile] = File(None, description="Opcional: Archivo de fuente .TTF o .OTF. Si no se envía, se usará la fuente por defecto.")
):
    """
    Paso 1: Crea una plantilla con la imagen de fondo, coordenadas y fuente. Devuelve un ID de plantilla.
    """
    if plantilla_png.content_type != "image/png":
        raise HTTPException(status_code=400, detail="El archivo de plantilla debe ser una imagen PNG.")

    plantilla_id = str(uuid.uuid4())
    ruta_plantilla_dir = os.path.join(CARPETA_PLANTILLAS_CONFIG, plantilla_id)
    os.makedirs(ruta_plantilla_dir)

    try:
        # Guardar imagen de fondo
        ruta_png = os.path.join(ruta_plantilla_dir, "fondo.png")
        with open(ruta_png, "wb") as buffer:
            buffer.write(await plantilla_png.read())

        # Gestionar la fuente (personalizada o por defecto)
        nombre_archivo_fuente = ""
        if fuente_ttf:
            if not fuente_ttf.filename.lower().endswith(('.ttf', '.otf')):
                raise HTTPException(status_code=400, detail="El archivo de fuente debe ser .TTF o .OTF.")
            nombre_archivo_fuente = fuente_ttf.filename
            ruta_fuente_destino = os.path.join(ruta_plantilla_dir, nombre_archivo_fuente)
            with open(ruta_fuente_destino, "wb") as buffer:
                buffer.write(await fuente_ttf.read())
        else:
            if not os.path.exists(DEFAULT_FONT_PATH):
                raise HTTPException(status_code=500, detail="No se proporcionó una fuente y la fuente por defecto no está disponible en el servidor.")
            nombre_archivo_fuente = "default"

        # Guardar configuración
        config = {
            "y_coord": y_coord,
            "tamano_fuente": tamano_fuente,
            "nombre_archivo_fuente": nombre_archivo_fuente
        }
        with open(os.path.join(ruta_plantilla_dir, "config.json"), "w") as f:
            json.dump(config, f)

        return {"message": "Plantilla creada exitosamente.", "plantilla_id": plantilla_id}
    except Exception as e:
        import shutil
        if os.path.exists(ruta_plantilla_dir):
            shutil.rmtree(ruta_plantilla_dir)
        raise HTTPException(status_code=500, detail=f"No se pudo crear la plantilla: {e}")

@app.post("/probar-plantilla", tags=["Gestión de Plantillas"])
async def probar_plantilla(
    plantilla_id: str = Form(..., description="El ID de la plantilla a probar."),
    nombre: str = Form("Nombre de Ejemplo Apellido", description="Un nombre para visualizar en el certificado.")
):
    """
    Paso 2: Genera un único PDF de previsualización para verificar la configuración de una plantilla.
    """
    ruta_plantilla_dir = os.path.join(CARPETA_PLANTILLAS_CONFIG, plantilla_id)
    if not os.path.isdir(ruta_plantilla_dir):
        raise HTTPException(status_code=404, detail="El ID de la plantilla no fue encontrado.")

    try:
        with open(os.path.join(ruta_plantilla_dir, "config.json"), 'r') as f:
            config = json.load(f)

        # Determinar qué fuente usar
        if config["nombre_archivo_fuente"] == "default":
            ruta_fuente = DEFAULT_FONT_PATH
        else:
            ruta_fuente = os.path.join(ruta_plantilla_dir, config["nombre_archivo_fuente"])

        fuente = ImageFont.truetype(ruta_fuente, config["tamano_fuente"])
        imagen_base = Image.open(os.path.join(ruta_plantilla_dir, "fondo.png")).convert("RGB")
        dibujo = ImageDraw.Draw(imagen_base)

        ancho_imagen, _ = imagen_base.size
        bbox = dibujo.textbbox((0, 0), nombre, font=fuente)
        ancho_texto = bbox[2] - bbox[0]
        x_coord = (ancho_imagen - ancho_texto) / 2

        dibujo.text((x_coord, config["y_coord"]), nombre, font=fuente, fill=(0, 0, 0))

        pdf_buffer = io.BytesIO()
        imagen_base.save(pdf_buffer, "PDF", resolution=100.0)
        pdf_buffer.seek(0)

        return StreamingResponse(pdf_buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=prueba_{plantilla_id}.pdf"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo generar la prueba: {e}")

@app.post("/subir-participantes", tags=["Gestión de Participantes"])
async def subir_participantes(
    archivo_excel: UploadFile = File(..., description="Archivo .xlsx con columnas 'nombre' y 'correo'.")
):
    """
    Paso 3: Sube un Excel con nombres y correos. Crea un lote en la base de datos con una clave única para cada uno.
    """
    if not archivo_excel.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="El archivo debe ser un .xlsx")

    try:
        df = pd.read_excel(archivo_excel.file)
        if not {'nombre', 'correo'}.issubset(df.columns):
            raise HTTPException(status_code=400, detail="El Excel debe contener las columnas 'nombre' y 'correo'.")

        lote_id = str(uuid.uuid4())
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO lotes (id) VALUES (?)", (lote_id,))

        participantes_para_insertar = []
        for _, row in df.iterrows():
            clave = generar_clave_unica(cursor)
            participantes_para_insertar.append((lote_id, row['nombre'], row['correo'], clave))

        cursor.executemany(
            "INSERT INTO participantes (lote_id, nombre, correo, clave) VALUES (?, ?, ?, ?)",
            participantes_para_insertar
        )
        conn.commit()
        conn.close()

        return {
            "message": "Datos de participantes cargados exitosamente.",
            "lote_id": lote_id,
            "participantes_agregados": len(participantes_para_insertar)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo procesar el archivo Excel: {e}")

@app.post("/enviar-correos", tags=["Gestión de Participantes"])
async def enviar_correos(
    lote_id: str = Form(..., description="ID del lote de participantes al que se enviarán los correos."),
    url_acceso: str = Form(..., description="URL base que se incluirá en el correo (ej: https://misitio.com/validar)."),
    asunto: str = Form("Acceso a tu certificado", description="Asunto del correo electrónico.")
):
    """
    Paso 4: Envía un correo personalizado a cada participante de un lote con su nombre, clave y una URL.
    """
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT nombre, correo, clave FROM participantes WHERE lote_id = ?", (lote_id,))
    participantes = cursor.fetchall()
    conn.close()

    if not participantes:
        raise HTTPException(status_code=404, detail="Lote no encontrado o sin participantes.")

    # Configuración de SMTP desde .env
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not all([smtp_server, smtp_port, smtp_username, smtp_password]):
        raise HTTPException(status_code=500, detail="La configuración del servidor de correo está incompleta en el archivo .env")

    enviados_count = 0
    fallidos = []

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_username, smtp_password)

        for participante in participantes:
            nombre = participante['nombre']
            correo = participante['correo']
            clave = participante['clave']
            
            cuerpo_email = (
                f"Hola {nombre},\n\n"
                f"Gracias por participar. Puedes acceder a tu certificado utilizando el siguiente enlace y tu clave personal.\n\n"
                f"Enlace: {url_acceso}\n"
                f"Tu clave de acceso: {clave}\n\n"
                "Saludos cordiales."
            )

            msg = MIMEMultipart()
            msg["From"] = smtp_username
            msg["To"] = correo
            msg["Subject"] = asunto
            msg.attach(MIMEText(cuerpo_email, "plain"))

            try:
                server.send_message(msg)
                enviados_count += 1
            except Exception:
                fallidos.append(correo)
        
        server.quit()

        return {
            "message": "Proceso de envío de correos completado.",
            "lote_id": lote_id,
            "enviados_exitosamente": enviados_count,
            "correos_fallidos": fallidos
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al conectar con el servidor de correo: {e}")