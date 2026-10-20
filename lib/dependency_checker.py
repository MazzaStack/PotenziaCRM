"""
Módulo de Verificación e Instalación Automática de Dependencias (Self-Healing Dependency Checker).
Garantiza que todos los componentes requeridos (seguridad, 2FA, rate limiting, base de datos, scrapers, IA)
estén instalados al iniciar la plataforma, sin requerir intervención manual.
"""
import sys
import os
import subprocess
import importlib.util

REQUIRED_COMPONENTS = [
    # (pip_package_spec, import_module_name)
    ("python-dotenv>=1.0.0", "dotenv"),
    ("flask-limiter>=4.1.0", "flask_limiter"),
    ("pyotp>=2.9.0", "pyotp"),
    ("qrcode[pil]>=8.0", "qrcode"),
    ("pillow>=10.0.0", "PIL"),
    ("flask==3.1.0", "flask"),
    ("flask-login==0.6.3", "flask_login"),
    ("requests==2.32.3", "requests"),
    ("beautifulsoup4==4.13.3", "bs4"),
    ("lxml==5.3.1", "lxml"),
    ("apscheduler==3.11.0", "apscheduler"),
    ("curl-cffi>=0.7.4", "curl_cffi"),
    ("pandas==2.2.3", "pandas"),
    ("openpyxl==3.1.5", "openpyxl"),
    ("google-genai==1.3.0", "google.genai"),
    ("groq==1.5.0", "groq"),
    ("fpdf2==2.8.7", "fpdf"),
    ("instagrapi==2.16.25", "instagrapi"),
    ("psycopg[binary,pool]>=3.2.0", "psycopg"),
]

def is_module_installed(module_name: str) -> bool:
    """Verifica si un módulo Python está disponible para importación."""
    try:
        if "." in module_name:
            parts = module_name.split(".")
            spec = importlib.util.find_spec(parts[0])
            if spec is None:
                return False
            # Intentar importar submódulo
            importlib.import_module(module_name)
            return True
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        try:
            importlib.import_module(module_name)
            return True
        except Exception:
            return False

def install_package(package_spec: str) -> bool:
    """Instala un paquete vía pip de forma silenciosa y segura."""
    print(f"[Auto-Installer] Instalando componente faltante: {package_spec}...")
    try:
        cmd = [sys.executable, "-m", "pip", "install", package_spec, "--quiet", "--no-warn-script-location"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"[Auto-Installer] [OK] {package_spec} instalado correctamente.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[Auto-Installer] [ERROR] No se pudo instalar {package_spec}: {e.stderr or e.stdout}")
        return False
    except Exception as ex:
        print(f"[Auto-Installer] [ERROR] Error inesperado instalando {package_spec}: {ex}")
        return False

def ensure_dependencies_installed(verbose: bool = True):
    """
    Chequea todas las dependencias críticas e instala automáticamente las que falten.
    Retorna True si todas están presentes o fueron instaladas.
    """
    missing_packages = []
    
    for pkg_spec, mod_name in REQUIRED_COMPONENTS:
        if not is_module_installed(mod_name):
            missing_packages.append(pkg_spec)
            
    if missing_packages:
        print(f"[Auto-Installer] Se detectaron {len(missing_packages)} componentes faltantes. Instalando automáticamente...")
        installed_count = 0
        for pkg in missing_packages:
            if install_package(pkg):
                installed_count += 1
        print(f"[Auto-Installer] Finalizada instalación ({installed_count}/{len(missing_packages)} componentes listos).")
        # Forzar invalidación de caches de importlib
        importlib.invalidate_caches()
    else:
        if verbose:
            print("[Auto-Installer] Todas las dependencias y módulos de seguridad están verificados y listos.")
            
    return len(missing_packages) == 0

if __name__ == "__main__":
    ensure_dependencies_installed(verbose=True)
