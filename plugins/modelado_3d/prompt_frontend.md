# PROMPT PARA GENERAR EL FRONTEND DE MODELADO 3D (CRM PLUGIN)

**Copiar y pegar todo el texto a continuación en la nueva ventana de Antigravity para implementar la UI interactiva.**

---

### Contexto del Proyecto

Estamos desarrollando un módulo de **Modelado 3D de Propiedades** mediante **Gaussian Splatting (3DGS)** integrado como un Plugin dentro de nuestro CRM (Flask). 
Ya creamos la estructura del plugin en `CRM\plugins\modelado_3d\manifest.json` y el proxy backend en `CRM\plugins\modelado_3d\routes.py`.

Tu tarea es reemplazar el archivo placeholder en:
`C:\Users\Germa\OneDrive\Trabajo\CRM\plugins\modelado_3d\templates\modelado_3d.html`
con una interfaz de usuario espectacular, interactiva y de aspecto premium (siguiendo las pautas de diseño moderno: dark mode, glassmorphism, degradados limpios, y fuentes como Outfit o Inter).

---

### Especificaciones Técnicas y de API

El controlador Flask del CRM (`routes.py`) ya expone los siguientes endpoints autenticados que debes consumir vía `fetch()` en la interfaz:

1.  **Listar Proyectos 3D:**
    *   **Endpoint:** `GET /modelado_3d/api/projects`
    *   **Respuesta (JSON):** Lista de objetos proyecto:
        `[{"id": "...", "name": "Casa de Campo", "property_id": "...", "status": "completed", "progress": 100, "message": "...", "created_at": "..."}]`
2.  **Subir Video para Nuevo Modelo:**
    *   **Endpoint:** `POST /modelado_3d/api/projects` (Form-data: `video`, `name`, `property_id`)
3.  **Iniciar Entrenamiento (Procesamiento 3D):**
    *   **Endpoint:** `POST /modelado_3d/api/projects/<project_id>/train` (JSON body: `{"simulate": true}`)
4.  **Verificar Estado del Proceso:**
    *   **Endpoint:** `GET /modelado_3d/api/projects/<project_id>/status`
    *   **Respuesta (JSON):** `{"status": "processing", "progress": 40, "message": "Ejecutando COLMAP..."}`
5.  **Descargar/Cargar Archivo del Modelo:**
    *   **Endpoint:** `GET /modelado_3d/model/<project_id>/model.spz` (formato comprimido optimizado de PlayCanvas) o `model.ply`
6.  **Eliminar Proyecto:**
    *   **Endpoint:** `DELETE /modelado_3d/api/projects/<project_id>`

El backend del CRM inyecta en la plantilla una variable de Jinja2 llamada `properties` que contiene la lista de propiedades registradas en el CRM (`id` y `titulo` o similar) para que el usuario pueda enlazar el modelo 3D a una casa real mediante un `<select>`.

---

### Requisitos del Frontend a Desarrollar

1.  **Diseño Visual de Alto Impacto (Estética Premium):**
    *   Usa una paleta de colores moderna (tonos oscuros elegantes, acentos azul/violeta eléctrico `#6366f1`, bordes semi-transparentes).
    *   Tipografía limpia (e.g., Google Fonts `Outfit` o `Inter`).
    *   Animaciones sutiles para transiciones, botones y estados de carga de procesamiento (por ejemplo, una barra de progreso circular o de línea que brille y se mueva según el progreso real).

2.  **Secciones en Pestañas (Tabs):**
    *   **Pestaña 1: Panel de Control (Escaneos):**
        *   Un botón destacado para "Nuevo Escaneo" que abra un modal flotante.
        *   El modal debe permitir escribir un nombre para el escaneo, seleccionar una propiedad del CRM en un menú desplegable (usando la lista inyectada en Jinja: `{% for p in properties %}`), y arrastrar/subir el archivo de video.
        *   Una lista de proyectos existentes con tarjetas ("Cards") de diseño refinado. Cada tarjeta muestra el nombre del proyecto, la propiedad vinculada, la fecha, y su estado actual:
            *   *Pendiente:* Botón verde de "Iniciar Procesamiento (Entrenar)".
            *   *Procesando:* Barra de carga en tiempo real que consulte el estado cada 3 segundos (`setInterval` dinámico).
            *   *Completado:* Botones para "Ver Recorrido 3D", "Editar Modelo (Limpiar)" y "Descargar".
            *   *Fallido:* Mensaje de error detallado y opción de reintento.
    *   **Pestaña 2: Visor de Recorridos 3D (Viewer):**
        *   Un contenedor `<canvas>` o visor integrado para previsualizar interactivamente el modelo de Gaussian Splatting generado.
        *   Usa el visor oficial ligero de PlayCanvas o la biblioteca de WebGL `gsplat.js` vía CDN (e.g. `https://cdn.jsdelivr.net/npm/gsplat@1.2.0/dist/gsplat.min.js` o similar) para cargar directamente el archivo `.spz` o `.ply` obtenido del endpoint `/modelado_3d/model/<project_id>/model.spz`.
        *   Implementa controles interactivos: Órbita con el ratón y modo de navegación tipo "caminar" o primera persona para explorar la casa.
    *   **Pestaña 3: Editor de Splats (Limpieza de Ruido):**
        *   Una integración limpia de **PlayCanvas SuperSplat** (puedes embeberlo mediante un `<iframe>` apuntando a `https://superspl.at/editor/` explicando que el usuario puede arrastrar su archivo `.ply` allí, o crear un enlace optimizado que transfiera el archivo para su limpieza rápida).

3.  **Código Limpio e Integrado:**
    *   Todo el código HTML, CSS (`<style>`) y lógica Javascript (`<script>`) debe estar contenido en el mismo archivo `modelado_3d.html` o referenciado correctamente si existen layouts globales del CRM (verifica si el CRM usa herencia de plantillas como `{% extends "base.html" %}`).
