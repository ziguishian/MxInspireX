# MxinspireX

**De una idea a un diseño.** Un espacio de diseño con IA de 灵矩绘境 que prioriza el almacenamiento local y conecta conversaciones, referencias y un lienzo infinito.

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md)

![Imagen de producto, escena coherente y edición del fondo](docs/images/product-workflow.png)

## Funciones

- Logotipos, carteles, productos, envases, personajes coleccionables, espacios, textos y HTML interactivo.
- La primera imagen real del producto sirve como referencia para las escenas posteriores; las ediciones conservan el original.
- Conversaciones por proyecto, referencias a imágenes y documentos, nodos, versiones, vistas previas y exportación.
- Imágenes, voz, vídeo, servicios externos de 3D y CAD paramétrico local. La disponibilidad depende de los proveedores configurados.
- Consumo de Token y costes en yuanes, separando cargos confirmados, estimaciones y operaciones pendientes de conciliación.

Los resultados independientes pueden generarse en paralelo; las escenas dependientes esperan su imagen de origen. No hay una fase automática de revisión de calidad. Las solicitudes con facturación desconocida no se reenvían automáticamente.

## Inicio rápido

Instala **Node.js 22 o 24** y **uv**:

```sh
git clone https://github.com/ziguishian/MxInspireX.git
cd MxInspireX
npm run start:portable
```

El lanzador instala las dependencias fijadas y prepara Python 3.12 mediante uv. Abre la dirección indicada en la terminal, normalmente `http://127.0.0.1:5173`. Si el puerto está ocupado, se elige otro. Detén los servicios con Ctrl+C.

Abre el avatar → **Ajustes / 设置 → Modelos y conexiones / 模型与连接**. Elige un proveedor, introduce tu clave, sincroniza su catálogo y selecciona los modelos. **La dirección oficial de EvoLink está integrada; solo necesitas la clave.** Vuelve al inicio, describe la tarea y añade referencias.

La interfaz está principalmente en chino. Estos README no implican una interfaz localizada. No se incluyen claves, cuentas, saldo ni proyectos personales. La generación 3D externa requiere configuración independiente.

## Guías y desarrollo

[Guía ilustrada en chino](docs/USER_GUIDE.md) · [Migración](RUN_IN_CODEX.md) · [Empaquetado](docs/PACKAGING.md) · [Guía técnica](AGENTS.md) · [Flujo del Agent](docs/agent-flow.md) · [Validación](docs/RELEASE_VALIDATION.md)

```sh
npm run setup:portable
npm run verify:portable   # Espacio vacío aislado, sin llamadas a modelos
npm run typecheck
npm test
npm run api:test
npm run build:web
npm run build
```

Para desarrollar la versión de escritorio, ejecuta `node node_modules/electron/install.js` y después `npm run dev`. El ZIP de código fuente requiere instalar dependencias; no es un instalador autónomo. Se excluyen los originales privados de los ejemplos: las pruebas de diseño siguen ejecutándose y dos comprobaciones de archivos se omiten solo si falta todo su conjunto de datos.

El proyecto usa Vue 3 / TypeScript / Vite / Vue Flow, Electron, FastAPI / Python y un worker Agent en Node. Los datos se guardan en `.local/portable-workspace/`. Detén la aplicación antes de hacer una copia de seguridad. No publiques claves, archivos `.env` ni bases de datos. Los modelos en la nube reciben el contenido necesario para procesar las solicitudes.

## Licencia y contacto

El código mantiene la licencia [MIT](LICENSE). Dependencias, fuentes y motores conservan sus licencias (`services/api/notices/`). Las obras y archivos subidos pertenecen a sus respectivos titulares.

**灵矩绘境 · MxinspireX** · [ziguishian@foxmail.com](mailto:ziguishian@foxmail.com)
