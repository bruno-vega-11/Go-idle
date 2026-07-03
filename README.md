# IDE del Compilador Go- → x86-64

Aplicación de escritorio que demuestra, de forma visual e interactiva, las
fases del compilador desarrollado en C++ (`../ProyectoCompiladoresC-`) para un
subconjunto del lenguaje **Go**, y las principales características del lenguaje
implementado.

Está construida con **Tkinter** (la librería de GUI estándar de Python, la
misma sobre la que se apoya el IDLE de Python), por lo que **no requiere
instalar dependencias adicionales de Python**.

---

## ¿Qué demuestra? (requisitos cubiertos)

| Requisito | Dónde se ve en el IDE |
|-----------|-----------------------|
| **Editor de código** para el lenguaje diseñado | Panel izquierdo, con resaltado de sintaxis y numeración de líneas |
| **Visualización del AST** | Pestaña **AST** — árbol real construido por el parser del compilador |
| **Generación de código ensamblador x86-64** | Pestaña **Ensamblador x86-64** — salida real de `GenCode` (sintaxis AT&T) |
| **Ejecución / simulación del programa compilado** | Pestaña **Ejecución** — ensambla el `.s` y ejecuta el binario nativo |
| **Visualización de resultados de ejecución** | Pestaña **Ejecución** — stdout, stderr y código de salida |

Además, la franja superior derecha muestra el **estado de las 5 fases**
(léxico → sintaxis → AST → semántica → codegen) con indicadores en verde/rojo,
y la pestaña **Tokens** muestra el volcado léxico completo.

> El AST y el ensamblador mostrados son la **salida auténtica del compilador
> C++ del proyecto**, no una reimplementación. El IDE compila las fuentes del
> compilador junto a un pequeño *driver* que además vuelca el AST a JSON.

---

## Requisitos

1. **Python 3.8+** con Tkinter (viene incluido en la instalación estándar de
   Python en Windows y macOS; en Linux: `sudo apt install python3-tk`).
2. Un **toolchain de C/C++** (`g++` y `gcc`) para compilar el compilador y para
   ensamblar/ejecutar el código x86-64 generado:
   - **Windows**: [MSYS2](https://www.msys2.org/) — el IDE detecta
     automáticamente `C:\msys64\ucrt64\bin` aunque no esté en el `PATH`.
     Instala el toolchain con: `pacman -S mingw-w64-ucrt-x86_64-gcc`.
   - **Linux/macOS**: `g++`/`gcc` del sistema (build-essential / Xcode CLT).

El IDE indica en la esquina superior derecha si encontró el toolchain, y en
**Ayuda → Diagnóstico del toolchain** da el detalle.

---

## Cómo ejecutarlo

**Windows:** doble clic en `run_ide.bat` (o `python ide.py` desde esta carpeta).

**Linux/macOS/Git Bash:** `./run_ide.sh` (o `python3 ide.py`).

La primera compilación tarda unos segundos porque compila el compilador C++ una
sola vez (queda cacheado en `build/ide_driver`).

---

## Flujo de uso

1. Escribe código o carga uno de los ejemplos desde el menú **Ejemplos**.
2. Pulsa **▶ Compilar (F5)** para correr las fases y ver tokens, AST y
   ensamblador. Si alguna fase falla, el indicador se pone rojo y el mensaje de
   error aparece en la barra de estado (resaltando la línea si es un error de
   sintaxis).
3. Pulsa **⚡ Compilar y ejecutar (F6)** para además ensamblar y correr el
   binario x86-64, viendo su salida en la pestaña **Ejecución**.

---

## Ejemplos incluidos (`examples/`)

| Archivo | Características del lenguaje |
|---------|------------------------------|
| `01_aritmetica.go-` | `var`, `int`, operadores, `println` |
| `02_funciones_bucle.go-` | funciones con retorno, `for` con cláusula |
| `03_control_flujo.go-` | `if`/`else`, operadores relacionales |
| `04_struct_metodo.go-` | `struct`, método con receptor puntero, literal compuesto |
| `05_float_string.go-` | `float64` (SSE), `string` y concatenación |
| `06_switch_globales.go-` | `const`/`var` globales, `switch`/`case`/`default` |

---

## Nota técnica: ejecución en Windows (puente de ABI)

El compilador genera ensamblador con la **ABI System V de Linux** (argumentos en
`%rdi`/`%rsi`/`%xmm0`, llamadas a `printf@PLT`, etc.). En Windows la libc usa la
**ABI Win64**, así que ejecutar ese código directamente provoca un *segfault*.

Para poder **ejecutar realmente** el binario en Windows, el IDE aplica un puente
de ABI (`driver/runtime_win.c`): unos envoltorios no variádicos marcados
`__attribute__((sysv_abi))` que reciben los argumentos como los pasa el código
generado y reenvían a la libc nativa. En Linux esto no se usa: el `.s` se
ensambla tal cual.

---

## Estructura de la carpeta

```
idle/
├── ide.py              IDE (Tkinter): editor, tokens, AST, asm, ejecución
├── backend.py          Orquestación: build / compile / assemble / run
├── driver/
│   ├── ide_main.cpp    Driver del compilador (corre las 4 fases + estado)
│   ├── ast_json.cpp    Volcado del AST real del parser a JSON
│   ├── ast_json.h
│   └── runtime_win.c   Puente de ABI SysV→Win64 (solo Windows)
├── examples/           Programas de ejemplo (.go-)
├── build/              Artefactos generados (driver + trabajo por sesión)
├── run_ide.bat / .sh   Lanzadores
└── README.md
```

El compilador original en `../ProyectoCompiladoresC-` **no se modifica**: el IDE
solo compila sus fuentes junto al driver.
