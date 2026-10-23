# MxinspireX

**Agente de diseño con IA, almacenamiento local y lienzo infinito · De una idea a un conjunto de diseños.**

[![Release](https://img.shields.io/github/v/release/ziguishian/MxInspireX?style=flat-square&color=4b8bd8&label=Release)](https://github.com/ziguishian/MxInspireX/releases/latest)
[![Windows x64](https://img.shields.io/badge/Windows-x64-4b8bd8?style=flat-square)](https://github.com/ziguishian/MxInspireX/releases/latest)
[![MIT License](https://img.shields.io/github/license/ziguishian/MxInspireX?style=flat-square&color=608571)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/ziguishian/MxInspireX?style=flat-square&color=c79a49&label=Stars)](https://github.com/ziguishian/MxInspireX/stargazers)

MxinspireX es un **espacio de trabajo de diseño con IA** creado por 灵矩绘境 para profesionales del diseño, equipos de proyectos culturales y creativos, y creadores de productos. Convierte requisitos y materiales de referencia en diseños que puedes seguir editando, comparar y exportar.

Sube imágenes de productos, materiales de marca o documentos y explica lo que necesitas con tus propias palabras. El agente utiliza el contexto del proyecto para llamar a los modelos y reúne conceptos de producto, envases, carteles, personajes e imágenes de ambientes en un mismo lienzo infinito. Puedes continuar la conversación para hacer cambios o conectar nodos para usar textos e imágenes anteriores como referencias en la siguiente generación.

> **Describe tu idea → Añade referencias → Genera con el agente → Compara y ajusta en el lienzo → Exporta**

Los proyectos y archivos se guardan en tu ordenador. Para usar modelos en la nube necesitas tu propia clave API; el proveedor cobra las llamadas realizadas. La aplicación no incluye créditos gratuitos.

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md)

[Descargar](https://github.com/ziguishian/MxInspireX/releases) · [Guía de uso (en chino)](docs/USER_GUIDE.md) · [Funciones y limitaciones (en chino)](docs/product-facts.md) · [Informar de un problema](https://github.com/ziguishian/MxInspireX/issues)

## Vista del espacio de trabajo

<img width="3840" height="1978" alt="Espacio de diseño y lienzo de MxinspireX 1" src="https://github.com/user-attachments/assets/838a1600-51fa-4382-81ea-13d7e9d9834b" />

<details>
<summary>Ver más ejemplos del lienzo y los diseños</summary>

<img width="3840" height="1978" alt="Espacio de diseño y lienzo de MxinspireX 2" src="https://github.com/user-attachments/assets/a53fa767-5d18-4aa2-9ae0-758ecd35e7a2" />
<img width="3840" height="1978" alt="Espacio de diseño y lienzo de MxinspireX 3" src="https://github.com/user-attachments/assets/005e4846-60de-4e4f-bb43-4ee812f649b7" />

</details>

## Funciones

- Logotipos, carteles, productos, envases, personajes coleccionables, espacios, textos y HTML interactivo.
- La primera imagen real del producto sirve como referencia para las escenas posteriores; las ediciones conservan el original.
- Conversaciones por proyecto, referencias a imágenes y documentos, nodos, versiones, vistas previas y exportación.
- Imágenes, voz, vídeo, servicios externos de 3D y CAD paramétrico local. La disponibilidad depende de los proveedores configurados.
- Consumo de Token y costes en yuanes, separando cargos confirmados, estimaciones y operaciones pendientes de conciliación.

Los resultados independientes pueden generarse en paralelo; las escenas dependientes esperan su imagen de origen. No hay una fase automática de revisión de calidad. Las solicitudes con facturación desconocida no se reenvían automáticamente.

## Inicio rápido

Para usar la aplicación de escritorio, descarga el instalador de Windows x64 desde [GitHub Releases](https://github.com/ziguishian/MxInspireX/releases/latest). La aplicación avisa cuando hay actualizaciones y solo las descarga y se reinicia para instalarlas con tu confirmación. Consulta la [guía de actualizaciones y publicación (en chino)](docs/desktop-updates.md). Para ejecutar el código fuente, sigue estos pasos.

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

## Star History

Si este espacio de trabajo te resulta útil, puedes darle una estrella o compartir tus comentarios en [Issues](https://github.com/ziguishian/MxInspireX/issues).

<a href="https://www.star-history.com/?repos=ziguishian%2FMxInspireX&type=date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date" />
    <img width="800" alt="Evolución de las estrellas de MxinspireX en GitHub" src="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date" />
  </picture>
</a>

[Ver el gráfico interactivo en Star History](https://www.star-history.com/?repos=ziguishian%2FMxInspireX&type=date)

## Licencia y contacto

El código mantiene la licencia [MIT](LICENSE). Dependencias, fuentes y motores conservan sus licencias (`services/api/notices/`). Las obras y archivos subidos pertenecen a sus respectivos titulares.

**灵矩绘境 · MxinspireX** · [ziguishian@foxmail.com](mailto:ziguishian@foxmail.com)
