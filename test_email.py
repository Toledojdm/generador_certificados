import smtplib
import os
from dotenv import load_dotenv
from email.mime.text import MIMEText

# Cargar las variables del archivo .env
load_dotenv()

# Leer las credenciales
email_user = os.getenv("EMAIL_USER")
email_password = os.getenv("EMAIL_PASSWORD")
email_host = os.getenv("EMAIL_HOST")
email_port = int(os.getenv("EMAIL_PORT")) # El puerto debe ser un número

# --- Configuración del correo ---
remitente = 'bonchisort9@gmail.com'
# IMPORTANTE: Cambia este destinatario a un correo que puedas revisar
destinatario = 'josedelmartoledo@gmail.com'
asunto = 'Prueba de envío desde Python'
cuerpo = 'Si recibes este correo, ¡la configuración es correcta!'

# Crear el mensaje
msg = MIMEText(cuerpo)
msg['Subject'] = asunto
msg['From'] = remitente
msg['To'] = destinatario

print("--- Intentando enviar correo ---")
print(f"De: {remitente}")
print(f"Para: {destinatario}")

try:
    # Conectar al servidor SMTP
    print(f"Conectando a {email_host}:{email_port}...")
    server = smtplib.SMTP(email_host, email_port)
    server.starttls() # Iniciar conexión segura
    print("Conexión segura establecida.")

    # Iniciar sesión
    print(f"Iniciando sesión como {email_user}...")
    server.login(email_user, email_password)
    print("¡Inicio de sesión exitoso!")

    # Enviar el correo
    server.sendmail(remitente, destinatario, msg.as_string())
    print("✅ ¡Correo enviado exitosamente!")

except smtplib.SMTPAuthenticationError:
    print("❌ ERROR: Falló la autenticación. Revisa tu EMAIL_USER y EMAIL_PASSWORD.")
    print("Recuerda usar una 'Contraseña de Aplicación' de Google, no tu contraseña normal.")
except Exception as e:
    print(f"❌ Ocurrió un error inesperado: {e}")
finally:
    if 'server' in locals() and server:
        server.quit()
        print("Conexión cerrada.")