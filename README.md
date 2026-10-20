# PotenziaCRM 🏢⚡

PotenziaCRM es una plataforma integral de gestión inmobiliaria y captación inteligente diseñada para brokers y agentes inmobiliarios. Incorpora herramientas de automatización, analítica de operaciones, tasador de mercado, vinculación de fichas marca blanca, chatbot con IA e integración multicanal (WhatsApp Status, Instagram Stories, email).

---

## 🚀 Inicio Rápido

### 1. Clonar el repositorio
```bash
git clone https://github.com/MazzaStack/PotenziaCRM.git
cd PotenziaCRM
```

### 2. Instalar dependencias
Se recomienda utilizar un entorno virtual con **Python 3.10+**:
```bash
python -m venv venv
# En Windows:
venv\Scripts\activate
# En Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Configuración del entorno
Copia la plantilla de variables de entorno y ajusta tus credenciales según corresponda:
```bash
copy .env.example .env
```

### 4. Iniciar la aplicación
Podés ejecutar la app directamente:
```bash
python app.py
```
O bien utilizar el script para Windows:
```bash
Start.bat
```
La aplicación quedará disponible en: `http://localhost:5000`

---

## 🔑 Credenciales de Acceso por Defecto

Al inicializar la base de datos por primera vez, el sistema crea automáticamente la cuenta de **SuperAdmin** principal:

| Campo | Valor Inicial |
| :--- | :--- |
| **Usuario** | `GermanMazza` |
| **Contraseña** | `GermanMazza123` |
| **Rol** | SuperAdmin / Acceso Completo |

> ⚠️ **Recomendación de seguridad:** Cambiá la contraseña desde el panel de Configuración apenas ingreses por primera vez.

---

## ☕ Apoya el proyecto
Si este CRM te resultó útil para tu negocio o desarrollo, puedes apoyar su mantenimiento:
- [Buy Me a Coffee](https://buymeacoffee.com/germanmazza)
