# Kang AI-AutoCut

**Local-first Agentic AI Video Production System**

**Sistema de producción de vídeo con IA agéntica y enfoque local**

**Languages:** [English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Bahasa Indonesia](README.id.md) | [Deutsch](README.de.md) | Español

[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3-3776AB)](README.md#installation)
[![FFmpeg](https://img.shields.io/badge/ffmpeg-required-007808)](README.md#installation)
[![Local-first](https://img.shields.io/badge/local--first-yes-4c1)](docs/decisions/ADR-0007-local-first.md)
[![Agent-oriented](https://img.shields.io/badge/agent--oriented-yes-8957e5)](README.md#use-with-an-ai-agent)
[![Tests](https://img.shields.io/badge/tests-1062%20passing-brightgreen)](README.md#installation)
[![macOS](https://img.shields.io/badge/macOS-tested-000000)](README.md#installation)
[![Baseline](https://img.shields.io/badge/baseline-pre--third--SKU-orange)](README.md#frozen-baseline)

*Las insignias son estáticas y describen la línea base congelada. Este repositorio no ejecuta ningún flujo de trabajo de CI, y los números de las insignias no son un estado en vivo.*

Kang AI-AutoCut es un sistema de producción de vídeo orientado a Agentes, no un
script de unión con FFmpeg. Toma material de origen autorizado y un objetivo
creativo declarado, y conduce el trabajo a través de **ocho etapas de producción**
— comprensión del material, inteligencia de edición, planificación narrativa,
construcción de la línea de tiempo, acabado de imagen, tipografía, audio,
masterización, revisión y reparación — con la **aprobación humana como un gate
explícito**.

Se ejecuta en tu propia máquina. La ruta de control de producción y el
procesamiento de medios tienen un enfoque local-first; los proveedores externos de
IA solo pueden recibir las entradas requeridas explícitamente para tareas aprobadas
de inteligencia o generación. Cada decisión creativa queda registrada, y el sistema
se niega a reportar un éxito que no puede medir.

> **Comercial primero, extensible por diseño.** La publicidad comercial es el primer
> flujo de trabajo validado en producción. La arquitectura está construida para
> ampliarse hacia flujos de trabajo más amplios de creadores y de medios.

```
Raw Footage
    ↓
Understand  →  Plan  →  Edit
    ↓
Picture  ·  Typography  ·  Audio
    ↓
Assemble & Master
    ↓
Review  →  Repair  →  Human Approval
    ↓
Final Video
```

---

## Por qué Kang AI-AutoCut

La mayoría de las herramientas de vídeo con IA producen **un vídeo, una sola vez**,
dentro de una ventana de chat. Volver a ejecutarlas da como resultado un vídeo
distinto, y nada del proceso es inspeccionable.

Kang AI-AutoCut trata la producción de vídeo como un **pipeline de ingeniería**:

| Salida habitual de la IA de vídeo | Kang AI-AutoCut |
|---|---|
| Un resultado puntual, difícil de repetir | Un flujo de trabajo reutilizable que ejecutas de nuevo |
| Las decisiones viven en un registro de chat | Cada decisión es un artefacto registrado |
| Un fallo significa empezar de cero | Los jobs se reanudan desde la etapa en la que se detuvieron |
| «Parece terminado» es la única comprobación | La salida se mide: fotogramas, fotogramas negros, congelaciones, sonoridad, true peak, hash del máster |
| Un modelo puede omitir un paso en silencio | Una etapa **no puede aprobarse sin nombrar la capacidad que ejecutó** |
| El criterio humano es invisible | La intervención humana ocurre en gates con nombre y queda registrada |
| Tu material se sube a un proveedor | El procesamiento es local-first; los proveedores reciben únicamente las entradas que una tarea requiere |

---

## Qué puedes construir

**Validado en producción actualmente:**

- **Publicidad comercial y vídeo de producto para e-commerce** — el primer flujo de
  trabajo llevado de principio a fin, incluida la verificación del máster de
  entrega.
- **Contenido de producto de formato corto para redes sociales** — ediciones
  comerciales verticales y de corta duración, usando las mismas ocho etapas.

**Dirección hacia la que la arquitectura está diseñada para extenderse** — *todavía
no validada en producción*:

- vídeo de creadores y de medios propios
- contenido de demostración y explicación de producto
- contenido de marca y de campaña
- otros flujos de trabajo estructurados de producción de vídeo

Hoy el sistema prioriza lo comercial. Nada aquí afirma que todas las categorías de
vídeo ya estén soportadas, y todavía no existe ningún framework de modos de
contenido.

---

## Cómo funciona

### Lo que haces tú

1. **Añade material de origen** — apunta el sistema a un directorio de vídeo fuente.
2. **Declara el objetivo** — producto, plataforma, idioma, duración objetivo y lo
   que el vídeo debe y no debe afirmar.
3. **Deja que el Agente ejecute el pipeline** — avanza por las etapas y se detiene
   cuando te necesita.
4. **Responde a los gates** — aprueba el copy, aporta un artefacto que falta o toma
   una decisión creativa.
5. **Aprueba el vídeo final** — una persona identificada libera el máster. Esa
   liberación es una decisión distinta de la revisión, y nombra el máster exacto que
   aprueba.

### Lo que hace el sistema

La ruta de control de producción ejecuta la **Production Fast Path de ocho etapas
semánticas**:

| # | Etapa | Qué ocurre |
|---|---|---|
| 1 | **PREPARE** | Inventario de fuentes con digests inmutables por archivo |
| 2 | **UNDERSTAND SHOTS** | Se analizan los medios; las marcas de tiempo medidas se mapean sobre una rejilla de análisis CFR para encontrar segmentos visuales reales |
| 3 | **PLAN THE EDIT** | Los rangos de la línea de tiempo se validan contra la acción observable — se rechaza un corte que no acierta con el inicio o con el resultado |
| 4 | **FINISH THE PICTURE** | Los rangos de origen se extraen a través del invariante de base de tiempo, se miden y se toma una decisión KEEP / REVIEW / CORRECT por plano |
| 5 | **PLAN THE WORDS** | La cobertura de la narración se comprueba **antes** de cualquier trabajo de voz de pago; después se renderiza el copy en pantalla |
| 6 | **BUILD THE AUDIO** | FIT / SYNC / RHYTHM se evalúan por separado; después se construye la mezcla y se **mide** |
| 7 | **ASSEMBLE & MASTER** | Se produce el máster de entrega y luego se verifica contra el propio archivo |
| 8 | **REVIEW & REPAIR** | Se evalúan todas las dimensiones de revisión; se deriva el veredicto; gate de liberación humana |

### Cómo se corresponden las dos vistas

```
USER VIEW                          SYSTEM VIEW (8 stages)
─────────────────────────────      ──────────────────────────────────────
1  add raw footage            →    PREPARE
2  state the goal             →    (job manifest + brief)
3  understand the material    →    UNDERSTAND SHOTS
4  build the editing strategy →    PLAN THE EDIT
5  construct the timeline     →    PLAN THE EDIT
6  finish the picture         →    FINISH THE PICTURE
7  titles / copy / typography →    PLAN THE WORDS
8  voice / music / audio      →    BUILD THE AUDIO
9  assemble and master        →    ASSEMBLE & MASTER
10 review and repair          →    REVIEW & REPAIR
11 human approval             →    REVIEW & REPAIR (human release gate)
12 final video                →    delivered master
```

### Las etapas se detienen de forma intencional

Cuando falta una entrada requerida, la ejecución **se detiene y nombra quién debe
actuar**:

```
   Stage ──▶ [ PRODUCER GATE ] ──▶ Stage
                 │
                 ├─ which artifact is missing
                 ├─ which producer is responsible (AUTO / CODEX / HUMAN / ADAPTER)
                 ├─ the input and output contract
                 ├─ the procedure to follow
                 ├─ the evidence required
                 └─ what must become true to resume
```

**Un gate no es un fallo.** Es el sistema negándose a inventar una decisión creativa
o a reclamar un trabajo que no hizo. Algunas etapas están automatizadas; otras
necesitan legítimamente un Agente, un adaptador de proveedor o una persona. Las
expresiones «generate or prepare» (generar o preparar), «Agent supplies» (el Agente
aporta) y «job-authored when required» (aportado por el job cuando se requiere) se
usan de forma deliberada a lo largo de este README.

---

## Capacidades actuales

### Disponibles y verificadas hoy

| Capacidad | Notas |
|---|---|
| Ingesta de fuentes e inventario inmutable | SHA-256 por archivo, reverificado antes de su uso |
| Comprensión de medios segura ante VFR | marcas de tiempo medidas y mapeadas a una rejilla de análisis CFR |
| Segmentación visual | se ejecuta sobre la rejilla que el motor decodifica realmente |
| Validación de rangos de la línea de tiempo | rechaza cortes que no aciertan con la acción observable |
| Extracción de rangos de origen | cada rango se resuelve a partir de una marca de tiempo medida |
| Ejecución de imagen | produce un artefacto de vídeo real, remedido después |
| Cobertura de narración | se ejecuta antes de cualquier generación de voz de pago |
| Renderizado de tipografía | salida real a partir del layout y las fuentes del propio job |
| Mezcla y masterización de audio | mezcla real, con sonoridad, true peak y clipping medidos |
| Empaquetado y máster final | `final/master.mp4` más QA técnico medido |
| Contrato de revisión y veredicto de liberación | cada dimensión se evalúa una vez; el veredicto se deriva, no se afirma |
| Planificación de reparación dirigida | alcance limitado a la capa afectada |
| Gate de liberación humana | una decisión distinta que nombra el máster que aprueba |
| Registro de intervenciones | se escribe automáticamente siempre que un gate detiene una ejecución |
| Reanudación e invalidación | se reanuda en la primera etapa incompleta; invalidar una etapa reabre todo lo que está aguas abajo |
| Validación de integridad del máster | el digest se recalcula; un máster eliminado o alterado falla la verificación |

### Con gate / aportadas por el job

Estas capacidades se ejecutan, pero el artefacto que consumen se aporta por job —
mediante un Agente, un adaptador o una persona:

| Capacidad | Qué se sigue aportando |
|---|---|
| Medición de imagen de solo lectura | en este repositorio no se incluye ninguna herramienta de medición |
| Protección de autenticidad del producto | lo mismo; sus comprobaciones de tolerancia aún no se han ejecutado sobre datos reales |
| Decisión KEEP / REVIEW / CORRECT | la decisión se ejecuta; nada aquí actúa sobre un `CORRECT` |
| Verificación del programa de audio (FIT / SYNC / RHYTHM) | la colocación de la voz que consume |
| Generación de voz / música | la aporta un adaptador de proveedor; **no está integrada** |

### Planificadas / extensibles

No implementadas y no reclamadas: un revisor comercial automatizado, compiladores de
backend genéricos, un registro de artefactos, una cola de jobs, un ejecutor
desatendido de un solo comando y flujos de trabajo más amplios de modos de
contenido.

---

## Uso con un Agente de IA

Kang AI-AutoCut está diseñado para **operarse con un Agente** — un modelo que puede
actuar sobre tu sistema de archivos y tu shell, no un modelo que solo conversa.

**No está atado a ningún producto de Agente en particular.** La compatibilidad se
basa en capacidades:

| El Agente debe ser capaz de… | Por qué |
|---|---|
| leer archivos del repositorio | seguir `README.md`, `PROJECT_IDENTITY.md`, `AGENTS.md` |
| ejecutar comandos de shell | FFmpeg, FFprobe, Python, la suite de pruebas |
| leer y escribir archivos locales | estado del job, artefactos, preparación de medios |
| ejecutar flujos de trabajo de Python y FFmpeg | cada etapa es local y determinista |
| entender artefactos JSON estructurados | jobs, revisiones, evidencia, manifiestos |
| **detenerse en un Producer Gate** (puerta de productor: el sistema se detiene deliberadamente hasta que un productor declarado aporte o apruebe un artefacto) | y preguntarte, en lugar de adivinar |
| respetar los límites del repositorio | medios fuera de Git, sin secretos, sin rutas ligadas a una máquina |

Ejemplos de Agentes capaces son Codex, DeepSeek Harness, Claude Code y otros Agentes
de programación o de uso de computadora. **Estos son ejemplos, no requisitos ni
integraciones respaldadas.**

**Un modelo que solo conversa no puede operar este sistema.** Sin acceso al sistema
de archivos y al shell no puede ejecutar el pipeline; solo puede hablar de él.

### Gobernanza interna frente a compatibilidad pública

Son dos cosas distintas y ambas son ciertas:

- **Internamente**, el flujo de trabajo de producción validado usa **Codex como
  Supervisor de nivel superior.** La autoridad creativa reside ahí, y el sistema
  está construido de modo que ningún componente determinista decida qué debe decir
  un vídeo.
- **Públicamente**, el repositorio busca mantenerse **agnóstico respecto al Agente**
  allí donde la arquitectura lo permite. Nada en la ruta de control está rígidamente
  atado al Agente de un único proveedor.

---

## Inicio rápido con un Agente

Entrega a un Agente de programación capaz la URL del repositorio y un prompt como
este:

```text
Instala Kang AI-AutoCut en este ordenador siguiendo las instrucciones del repositorio.

Repositorio: https://github.com/KanG-ciyuan/Kang-AI-AutoCut

Antes de cambiar nada:
1. Lee README.md, PROJECT_IDENTITY.md y AGENTS.md.
2. Comprueba el entorno: Python, FFmpeg/FFprobe y los paquetes de Python que el
   código importa realmente.
3. Informa de lo que falta. No instales nada que yo no haya aprobado.

Después:
4. Configura el espacio de trabajo local y la raíz de medios usando solo roles
   lógicos y variables de entorno. Mantén los medios fuera de Git.
5. Nunca escribas una clave de API, un token o una credencial en ningún archivo
   rastreado, log o commit.
6. Ejecuta las autopruebas del repositorio antes de crear mi primer job de vídeo.

Cuando empecemos un job:
7. Ejecuta la ruta de control de producción y detente en cada Producer Gate.
8. Pregúntame cuando un gate necesite una decisión humana o una aprobación
   creativa.
9. No inventes copy, dirección de arte ni afirmaciones en mi nombre.
```

**Lo que el Agente todavía tiene que hacer a mano.** La instalación *no* está
completamente automatizada hoy: no hay instalador, no hay manifiesto de empaquetado
y no hay un lockfile de dependencias declarado. El Agente debe inspeccionar el
entorno, instalar los requisitos previos que apruebes y configurar las rutas
locales. El README de abajo enumera exactamente lo que está verificado, y el
repositorio no contiene ningún `pyproject.toml` ni `requirements.txt` — eso es una
laguna de documentación conocida, no un paso oculto.

---

## Instalación

### Requisitos previos verificados

| Requisito | Estado |
|---|---|
| **Python 3** | verificado en 3.11.15. El repositorio no declara ninguna versión mínima — considéralo una laguna. |
| **FFmpeg y FFprobe** | requeridos. Verificados en ffmpeg/ffprobe 9.0.1. |
| **`numpy`** | requerido por el módulo de comprensión de medios |
| **`Pillow`** | requerido por el adaptador de ejecución de tipografía |
| **macOS** | verificado en macOS arm64. Windows y Linux **no** están verificados. |

No existe `pyproject.toml`, `setup.py` ni `requirements.txt`, así que aquí no se
declara ninguna fijación de versiones. Lee los imports en lugar de confiar en un
lockfile que no está.

### Configuración inicial

```sh
git clone https://github.com/KanG-ciyuan/Kang-AI-AutoCut.git
cd AI-AutoCut

# Local configuration: resolves environment variables, never machine paths
cp config/examples/autocut.env.example .env.local
# edit .env.local: set AUTOCUT_MEDIA_ROOT and AUTOCUT_WORKSPACE
```

### Verificar la instalación

```sh
# Full offline regression — no network, no media required
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests

# End-to-end execution proof — builds its own media, produces a real master
python3 scripts/run_pre_exam_proof.py --job-root /tmp/pre-exam-proof
```

La prueba es deliberadamente de dos fases: se detiene en el gate de liberación
humana, escribe la liberación nombrando el máster **verificado** y luego se reanuda
hasta completarse. Falla si el máster se elimina o se altera.

### Tu primer job

```sh
# 1. Initialize a job (generic: any product, any source count)
python3 -m src.ai_autocut.job_foundation \
    --job-id my-first-job \
    --product-name 'My Product' \
    --source-root /path/to/footage \
    --workspace /path/to/job-workspace

# 2. Run the production control path
python3 -m src.ai_autocut.fast_path --job-root /path/to/job-workspace
```

Se detendrá en el primer Producer Gate y te dirá qué se necesita a continuación.

Instrucciones completas: [`docs/audit/execution-runbook.md`](docs/audit/execution-runbook.md).

---

## Compatibilidad con Agentes y LLM

Cuatro capas distintas se confunden con facilidad. El sistema las mantiene separadas
a propósito:

| Capa | Qué es | En este proyecto |
|---|---|---|
| **LLM** | un modelo de razonamiento | intercambiable, allí donde se usa un modelo |
| **Agente** | un modelo **más herramientas** que puede actuar sobre este repositorio | requerido para operar el sistema |
| **Proveedor** | un servicio externo opcional para generación o inteligencia | conectable; **no integrado** |
| **Motor de ejecución** | el pipeline local determinista de Python/FFmpeg | lo único en lo que se confía para informar que un paso se completó correctamente |

**Sin dependencia de proveedor por diseño.** La ruta de control llama a módulos
locales deterministas. Cuando hay un modelo o un proveedor implicado, es un productor
que aporta un artefacto a través de un contrato declarado — de modo que cambiar el
modelo o el proveedor no cambia el pipeline.

**Pero la compatibilidad es una cuestión de capacidades, no de marcas.** Un modelo
que no puede leer y escribir archivos, ejecutar comandos de shell o respetar un gate
no puede operar este sistema, por muy capaz que sea razonando.

---

## Arquitectura de audio y proveedores de IA

El repositorio actual realiza **mezcla y masterización locales** sobre los activos de
audio que aporta el job. Deliberadamente **no** llama a ningún proveedor de voz,
música o efectos de sonido. La síntesis de audio no está implementada aquí.

```
External Audio Provider   (future Adapter layer — NOT built in)
        ↓
  generated VO / BGM / SFX assets
        ↓
  job-local audio assets
        ↓
  Audio Program  →  local Mix  →  local Master
                     (measured: loudness, true peak, clipping)
```

**Lo que existe hoy:** la etapa `BUILD THE AUDIO` consume activos de audio locales al
job, los mezcla con FFmpeg contra los objetivos del propio job y mide el resultado.
Rechaza una mezcla cuyo pico de muestra alcanza el fondo de escala.

**Lo que no existe:** ninguna integración de proveedor incorporada. No hay generación
de voz con un solo clic, y este repositorio no contiene ningún cliente de proveedor.

**Contexto histórico, etiquetado con precisión.** La locución (voice-over) se produjo
mediante **MiniMax `speech-2.8-hd`** durante trabajos de producción validados
anteriores, y un manifiesto de job predecesor registra **Doubao Seed Audio 1.0**.
Ambos son **experimentos evaluados históricamente**, registrados en
[`docs/providers/audio-provider.md`](docs/providers/audio-provider.md) — no son
integraciones de producción incorporadas actuales. Sus hallazgos dieron forma a la
política de audio; sus clientes no forman parte de este repositorio.

Ningún valor de clave, token o credencial aparece en ningún lugar de este
repositorio. Las credenciales se referencian únicamente por el nombre de la variable
de entorno.

---

## Valor comercial y de producción

El valor está en la arquitectura, no en una promesa sobre los resultados:

- **Un flujo de trabajo reutilizable, no una salida puntual.** Ejecuta el mismo
  proceso de producción en el siguiente producto en lugar de iniciar una conversación
  nueva.
- **Producción repetible.** Las mismas etapas, contratos y gates se aplican a cada
  job, de modo que el conocimiento del proceso se acumula en lugar de evaporarse.
- **Decisiones creativas auditables.** Cada elección es un artefacto con evidencia,
  así que una revisión puede preguntar *por qué*, no solo *qué*.
- **Jobs reanudables.** Un job detenido por un gate o por un fallo continúa desde la
  etapa en la que se detuvo, en lugar de empezar de nuevo.
- **Ejecución determinista.** El renderizado, la extracción y la medición son locales
  y reproducibles; la afirmación de un modelo nunca es la evidencia.
- **El material de origen es reutilizable.** Un material sólido puede servir para
  múltiples variantes sin volver a rodar.
- **Revisión y reparación estructuradas.** La reparación se dirige a la capa
  afectada, no a una regeneración completa — así una edición aprobada no se
  reemplaza en silencio.
- **Validación medible de la salida.** El recuento de fotogramas, los fotogramas
  negros, los fotogramas congelados, la sonoridad, el true peak y el digest del
  máster se miden a partir del archivo.
- **La intervención humana es visible.** El sistema registra cuándo se abrió un gate,
  quién actuó y cuándo se resolvió.
- **Propiedad local de los medios.** Los medios de origen no se suben automáticamente
  a un pipeline en la nube; la ruta de control y el procesamiento de medios
  permanecen en tu máquina, y un proveedor externo aprobado recibe únicamente las
  entradas que una tarea requiere de forma explícita.
- **Flexibilidad de proveedores.** La generación queda detrás de un límite, de modo
  que la elección de proveedor es reemplazable.

Lo que esto **no** afirma: calidad garantizada, conversión o ingresos garantizados,
ni una reducción garantizada del tiempo de edición. Nada de eso queda establecido por
nada de este repositorio.

---

## Arquitectura

| Documento | Contenido |
|---|---|
| [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md) | modelo de interacción, ruta de control de producción, madurez |
| [`docs/architecture/supervisor-authority.md`](docs/architecture/supervisor-authority.md) | el límite del Supervisor de Codex |
| [`docs/architecture/backend-neutral-timeline.md`](docs/architecture/backend-neutral-timeline.md) | una línea de tiempo, tres backends |
| [`docs/architecture/operations.md`](docs/architecture/operations.md) | roles de rutas, staging ASCII, regla de verificación |
| [`docs/contracts/`](docs/contracts/) | contratos congelados |
| [`docs/policies/`](docs/policies/) | política de edición, planos, tipografía, audio y revisión |
| [`docs/decisions/`](docs/decisions/) | registros de decisiones de arquitectura |
| [`docs/audit/production-chain-manifest.md`](docs/audit/production-chain-manifest.md) | cableado y grado de preparación por capacidad |
| [`docs/audit/execution-runbook.md`](docs/audit/execution-runbook.md) | cómo ejecutar cada límite |
| [`docs/audit/gate-g0-history.md`](docs/audit/gate-g0-history.md) | cómo se alcanzó la línea base congelada |

### Estructura del repositorio

```
src/ai_autocut/          production code
  fast_path.py             the eight-stage control path
  producer_registry.py     every required artifact and its producer
  execution_contracts.py   the four execution boundaries
  execution_adapters.py    job-scoped picture / typography / audio / packaging
  timebase_adapter.py      the source-timestamp invariant
  media_probe.py           measured facts about a real media file
  ...                      contracts, policies, validators

tests/                   offline regression suite
schemas/                 frozen contracts and the Gold manifest
docs/                    architecture, contracts, policies, decisions, audits
scripts/                 the execution proof and the local-env wrapper
examples/                example job shape
config/examples/         configuration template
```

---

## Diseño local-first

Local-first es un requisito, no un estado temporal. La ruta de control de producción
y todo el procesamiento de medios se ejecutan en la máquina local, usando Python,
FFmpeg/FFprobe y el sistema de archivos local, con orquestación determinista. Las API
de IA externas aprobadas pueden usarse para tareas seleccionadas de inteligencia o
generación; nunca son la ruta de control. La infraestructura en la nube —
almacenamiento de objetos, plataformas de servidor, workers distribuidos, paneles,
cuentas de usuario — está deliberadamente ausente. Ver
[ADR-0007](docs/decisions/ADR-0007-local-first.md).

Ninguna ruta absoluta ligada a una máquina aparece en este repositorio. Cada
ubicación en tiempo de ejecución es un rol lógico resuelto desde una variable de
entorno; ver [`docs/architecture/operations.md`](docs/architecture/operations.md) y
[`config/examples/autocut.env.example`](config/examples/autocut.env.example).

---

## Estado actual

| | |
|---|---|
| Línea base congelada | `pre-third-sku-blind-v1` → `b65a73b53040bd1ff5defe25e624a28f623b6847` |
| Estado de congelación | `CLOSED_AND_FROZEN` |
| Validez del examen | `PASS_WITH_EXPLICIT_PRODUCER_GATES` |
| Siguiente fase de producción planificada | Examen a ciegas del tercer SKU — **no iniciado** |

Existe una **ruta de control de producción con gates** que funciona y que ha
producido un máster de entrega real, verificado de forma independiente. No es un
editor desatendido de un solo clic, y no pretende serlo.

---

## Limitaciones conocidas

- **No es un editor desatendido de un solo comando.** Los Producer Gate detienen la
  ejecución por diseño, y algunos necesitan una persona o un Agente.
- **Sin revisor comercial automatizado.** El contrato de revisión registra un juicio;
  no lo produce.
- **La medición de imagen y la protección de producto son aportadas por el job.** Aquí
  no se incluye ninguna herramienta de medición, y las comprobaciones de tolerancia de
  la protección aún no se han ejecutado sobre datos reales — el gate ha demostrado
  rechazar, no evaluar.
- **La rama `CORRECT` de imagen nunca se ha activado** en una ejecución de producción.
- **Sin proveedor de audio integrado.** La síntesis no está implementada; el pipeline
  consume activos locales al job.
- **La tipografía demuestra ejecución, no dirección de arte.** No hay planificador de
  jerarquía del copy en pantalla ni validación de obstrucción de producto; el job
  aporta su propio layout.
- **La prueba de ejecución usa audio local generado.** Demuestra la ruta de mezcla y
  masterización, no una interpretación de voz real.
- **Sin registro de artefactos y sin cola de jobs.** Los datos grandes de preparación
  se limpian a mano.
- **Sin compiladores de backend genéricos.** `compile_for_backend` lanza un error para
  todos los backends; la ejecución ocurre mediante adaptadores con alcance de job.
- **Sin manifiesto de dependencias declarado.** No existe `pyproject.toml` ni
  lockfile.
- **Verificado solo en macOS.** Windows y Linux no están probados.
- **Con seguimiento abierto, sin resolver:** segmentación visual consciente de la
  ejecución (C-01) y verificación automática del rango seleccionado («needs vision»).

---

## Hoja de ruta

1. **Ejecutar el examen a ciegas del tercer SKU contra `pre-third-sku-blind-v1`.**
2. Medir la calidad final, la frecuencia de los Producer Gate y la intervención
   humana.
3. Usar la evidencia de la ejecución a ciegas para decidir qué capacidades restantes
   aportadas por el job merecen automatizarse a continuación.

La línea base congelada está pensada para examinarse **como congelada**: no hay
trabajo de automatización previo al examen programado antes de la ejecución a
ciegas, de modo que el examen mida el sistema aceptado y no un sistema que todavía se
mueve bajo él.

---

## Línea base congelada

```
tag             pre-third-sku-blind-v1
target commit   b65a73b53040bd1ff5defe25e624a28f623b6847
```

**Qué significa «congelada» aquí:** existe una línea base reproducible previa al
examen. El commit etiquetado es exactamente el sistema que fue auditado y aceptado,
de modo que la siguiente ejecución del examen pueda compararse contra un estado
conocido en lugar de contra un recuerdo del mismo.

**Qué no significa:** que el producto esté terminado, que cada capacidad esté
automatizada o que el sistema esté completo para producción. Pueden aterrizar
commits de documentación en `main` después de la etiqueta; la etiqueta en sí no se
mueve.

---

## Licencia

**Apache-2.0.** El texto completo de la licencia está en [LICENSE](LICENSE). La
justificación, la decisión de no incluir `NOTICE` y los puntos que siguen abiertos
para una etapa posterior se registran en
[LICENSE_DECISION_PENDING.md](LICENSE_DECISION_PENDING.md).

---

## Identidad canónica

- ID del proyecto: `ai-autocut`
- Rama por defecto: `main`
- Raíz de datos en tiempo de ejecución: rol lógico `AUTOCUT_WORKSPACE`
- Raíz de medios: rol lógico `AUTOCUT_MEDIA_ROOT`

El registro de identidad legible por máquina es
[PROJECT_IDENTITY.md](PROJECT_IDENTITY.md). Las reglas de entrada para Agentes están
en [AGENTS.md](AGENTS.md).
