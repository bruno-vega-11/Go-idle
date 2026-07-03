"""
backend.py — Orquestacion de compilacion para el IDE
=====================================================
Encapsula todo lo que el IDE necesita hacer con el compilador C++ del proyecto,
sin depender de tkinter (puede usarse desde linea de comandos para pruebas).

Flujo (mismo espiritu que run_all_inputs.py del proyecto original):

  1. build_driver()  -> compila UNA vez los .cpp del compilador + el driver
                        del IDE (driver/ide_main.cpp + driver/ast_json.cpp)
                        en un ejecutable 'ide_driver'.
  2. compile_source() -> corre ese ejecutable sobre un archivo fuente y produce
                        los artefactos por fase: tokens, AST (json), asm (.s),
                        y el estado OK/ERROR de cada fase.
  3. build_program()  -> ensambla el .s a un ejecutable nativo. En Windows
                        aplica el puente de ABI (driver/runtime_win.c).
  4. run_program()    -> ejecuta ese binario y captura su salida.

Detecta g++/gcc en el PATH y, si no estan, prueba ubicaciones tipicas de
MSYS2/MinGW en Windows.
"""

import os
import re
import shutil
import subprocess
import sys

# --- Rutas base -------------------------------------------------------------
IDLE_DIR    = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(IDLE_DIR, "..", "ProyectoCompiladoresGolang"))
DRIVER_DIR  = os.path.join(IDLE_DIR, "driver")
BUILD_DIR   = os.path.join(IDLE_DIR, "build")
WORK_DIR    = os.path.join(BUILD_DIR, "work")     # artefactos por-fase de la sesion

IS_WINDOWS = os.name == "nt"
EXE_SUFFIX = ".exe" if IS_WINDOWS else ""

# Fuentes del compilador (las del repo original, NO se modifican).
COMPILER_SOURCES = [
    "scanner.cpp", "token.cpp", "parser.cpp", "ast.cpp",
    "visitor.cpp", "Semantic_types.cpp", "TypeCheker.cpp", "GenCode.cpp",
]
# Fuentes propias del IDE (driver con volcado de AST).
DRIVER_SOURCES = ["ide_main.cpp", "ast_json.cpp"]

DRIVER_EXE = os.path.join(BUILD_DIR, "ide_driver" + EXE_SUFFIX)


# --- Deteccion de toolchain -------------------------------------------------
# Ubicaciones tipicas de MSYS2 / MinGW en Windows (por si no estan en PATH).
_WIN_TOOLCHAIN_DIRS = [
    r"C:\msys64\ucrt64\bin",
    r"C:\msys64\mingw64\bin",
    r"C:\mingw64\bin",
    r"C:\ProgramData\mingw64\mingw64\bin",
    r"C:\Strawberry\c\bin",
]


class ToolError(Exception):
    """Error recuperable que el IDE muestra al usuario."""


def _find_tool(name):
    """Devuelve la ruta a una herramienta (g++, gcc), buscando en PATH y en
    ubicaciones tipicas de MinGW en Windows. None si no se encuentra."""
    exe = name + (".exe" if IS_WINDOWS else "")
    found = shutil.which(name) or shutil.which(exe)
    if found:
        return found
    if IS_WINDOWS:
        for d in _WIN_TOOLCHAIN_DIRS:
            cand = os.path.join(d, exe)
            if os.path.isfile(cand):
                return cand
    return None


def toolchain_info():
    """Diagnostico del toolchain para mostrar en el IDE."""
    gpp = _find_tool("g++")
    gcc = _find_tool("gcc")
    return {
        "g++": gpp,
        "gcc": gcc,
        "ok": bool(gpp and gcc),
        "project_dir": PROJECT_DIR,
        "project_ok": os.path.isdir(PROJECT_DIR),
    }


def _tool_dir_env(tool_path):
    """Entorno con el directorio del compilador al frente del PATH (para que
    encuentre sus DLLs de runtime en Windows)."""
    env = os.environ.copy()
    if tool_path:
        d = os.path.dirname(tool_path)
        env["PATH"] = d + os.pathsep + env.get("PATH", "")
    return env


def _run(cmd, cwd=None, env=None, stdin=None, timeout=60):
    """Ejecuta un comando capturando stdout/stderr como texto.

    Forzamos UTF-8 en la decodificacion: el driver del compilador emite
    mensajes con acentos (ej. "Error sintactico") en UTF-8, y sin esto Python
    en Windows los decodificaria con la codificacion local (cp1252),
    corrompiendo los acentos. errors='replace' evita que un byte suelto
    aborte la captura."""
    return subprocess.run(
        cmd, cwd=cwd, env=env, input=stdin,
        capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )


# --- 1. Compilar el driver del IDE -----------------------------------------
def build_driver(force=False):
    """Compila el compilador + driver del IDE a un unico ejecutable.
    Devuelve (ok, log). Cachea: no recompila si el .exe es mas nuevo que todas
    las fuentes, salvo force=True."""
    os.makedirs(BUILD_DIR, exist_ok=True)
    gpp = _find_tool("g++")
    if not gpp:
        raise ToolError(
            "No se encontro 'g++'. Instala MSYS2/MinGW y asegurate de que g++ "
            "este en el PATH (o en C:\\msys64\\ucrt64\\bin)."
        )
    if not os.path.isdir(PROJECT_DIR):
        raise ToolError(f"No se encontro el proyecto del compilador en:\n{PROJECT_DIR}")

    sources = (
        [os.path.join(PROJECT_DIR, s) for s in COMPILER_SOURCES]
        + [os.path.join(DRIVER_DIR, s) for s in DRIVER_SOURCES]
    )
    missing = [s for s in sources if not os.path.isfile(s)]
    if missing:
        raise ToolError("Faltan archivos fuente:\n" + "\n".join(missing))

    if not force and os.path.isfile(DRIVER_EXE):
        newest_src = max(os.path.getmtime(s) for s in sources)
        # incluir este backend y los headers como dependencias groseras
        if os.path.getmtime(DRIVER_EXE) >= newest_src:
            return True, "Driver ya compilado (cache).\n" + DRIVER_EXE

    cmd = [gpp, "-std=c++20", "-O1",
           "-I", PROJECT_DIR, "-I", DRIVER_DIR,
           *sources, "-o", DRIVER_EXE]
    env = _tool_dir_env(gpp)
    log = "Compilando driver:\n  " + " ".join(cmd) + "\n\n"
    res = _run(cmd, env=env, timeout=300)
    log += res.stdout + res.stderr
    if res.returncode != 0:
        raise ToolError("Error al compilar el driver del IDE:\n\n" + log)
    return True, log + "\nCompilacion del driver: OK\n" + DRIVER_EXE


# --- 2. Compilar un archivo fuente (correr las fases) -----------------------
_PHASE_LABELS = {
    "lexica":     "Analisis lexico (Scanner)",
    "sintactica": "Analisis sintactico (Parser)",
    "ast":        "Construccion del AST",
    "semantica":  "Analisis semantico (TypeChecker)",
    "codegen":    "Generacion de codigo x86-64",
}
_PHASE_ORDER = ["lexica", "sintactica", "ast", "semantica", "codegen"]


def compile_source(source_text, name="programa"):
    """Escribe `source_text` a un archivo, corre el driver y recopila los
    artefactos. Devuelve un dict con:
        phases: lista de {key,label,status,message}
        tokens: texto | None
        ast:    texto json | None
        asm:    texto (.s) | None
        asm_path: ruta al .s | None
        stdout/stderr/returncode del driver
        ok: True si llego hasta codegen
    """
    os.makedirs(WORK_DIR, exist_ok=True)
    # Limpiar artefactos previos de este nombre
    base = re.sub(r"[^A-Za-z0-9_]", "_", name) or "programa"
    src_path = os.path.join(WORK_DIR, base + ".src")
    tok_path = os.path.join(WORK_DIR, base + "_tokens.txt")
    ast_path = os.path.join(WORK_DIR, base + "_ast.json")
    asm_path = os.path.join(WORK_DIR, base + ".s")
    for p in (tok_path, ast_path, asm_path):
        if os.path.isfile(p):
            os.remove(p)

    with open(src_path, "w", encoding="utf-8") as f:
        f.write(source_text)

    if not os.path.isfile(DRIVER_EXE):
        build_driver()

    gpp = _find_tool("g++")
    env = _tool_dir_env(gpp)
    res = _run([DRIVER_EXE, src_path, WORK_DIR], env=env, timeout=60)

    # Parsear las lineas "FASE|<key>|<status>[|msg]" del stdout.
    status = {}
    messages = {}
    for line in res.stdout.splitlines():
        if not line.startswith("FASE|"):
            continue
        parts = line.split("|", 3)
        if len(parts) < 3:
            continue
        _, key, st = parts[0], parts[1], parts[2]
        msg = parts[3] if len(parts) > 3 else ""
        status[key] = st
        if msg:
            messages[key] = msg

    # El TypeChecker/GenCode del proyecto pueden abortar con exit(1) e imprimir
    # "Error semantico: ..." sin emitir la linea FASE|semantica|OK. Detectamos
    # ese caso por el marcador BEGIN sin OK.
    def resolve(key):
        st = status.get(key)
        if st == "OK":
            return "ok", messages.get(key, "")
        if st == "ERROR":
            return "error", messages.get(key, "Error")
        if st == "BEGIN":
            # comenzo pero no termino -> fallo (buscar mensaje en salida)
            err = _extract_error(res.stdout, res.stderr)
            return "error", err or "La fase se interrumpio."
        return "pending", ""

    phases = []
    hit_error = False
    for key in _PHASE_ORDER:
        if hit_error:
            phases.append({"key": key, "label": _PHASE_LABELS[key],
                           "status": "skipped", "message": ""})
            continue
        st, msg = resolve(key)
        phases.append({"key": key, "label": _PHASE_LABELS[key],
                       "status": st, "message": msg})
        if st == "error":
            hit_error = True

    def read(p):
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                return f.read()
        return None

    ok = status.get("codegen") == "OK"
    return {
        "phases": phases,
        "tokens": read(tok_path),
        "ast": read(ast_path),
        "asm": read(asm_path),
        "asm_path": asm_path if os.path.isfile(asm_path) else None,
        "stdout": res.stdout,
        "stderr": res.stderr,
        "returncode": res.returncode,
        "ok": ok,
    }


def _extract_error(stdout, stderr):
    """Busca un mensaje de error legible en la salida del compilador."""
    for blob in (stderr, stdout):
        for line in blob.splitlines():
            low = line.lower()
            if "error" in low and not line.startswith("FASE|"):
                return line.strip()
    return ""


# --- 3. Ensamblar el .s a un binario nativo ---------------------------------
# Reescrituras del .s (solo Windows): redirigir las llamadas SysV variadicas
# de printf y las de libc a los envoltorios sysv_abi de runtime_win.c.
_WIN_REWRITES = [
    ("leaq print_fmt_f(%rip), %rdi\n  movq $1, %rax\n  call printf@PLT",
     "leaq print_fmt_f(%rip), %rdi\n  movq $1, %rax\n  call __sysv_print_flt"),
    ("leaq print_fmt_s(%rip), %rdi\n  movq $0, %rax\n  call printf@PLT",
     "leaq print_fmt_s(%rip), %rdi\n  movq $0, %rax\n  call __sysv_print_str"),
    ("leaq print_fmt_ld(%rip), %rdi\n  movq $0, %rax\n  call printf@PLT",
     "leaq print_fmt_ld(%rip), %rdi\n  movq $0, %rax\n  call __sysv_print_int"),
    ("leaq nl_fmt(%rip), %rdi\n  movq $0, %rax\n  call printf@PLT",
     "leaq nl_fmt(%rip), %rdi\n  movq $0, %rax\n  call __sysv_print_nl"),
]
_WIN_LIBC = ["malloc", "calloc", "strlen", "strcpy", "strcat"]


def _prepare_asm_for_platform(asm_text):
    """Devuelve (asm_final, extra_sources). En Windows aplica el puente de ABI
    y agrega runtime_win.c como fuente adicional. En Linux, deja el .s igual."""
    if not IS_WINDOWS:
        return asm_text, []
    s = asm_text
    for a, b in _WIN_REWRITES:
        s = s.replace(a, b)
    for fn in _WIN_LIBC:
        s = s.replace(f"call {fn}@PLT", f"call __sysv_{fn}")
    s = s.replace("@PLT", "")
    # La nota GNU-stack es de ELF; en PE/COFF el ensamblador la ignora, pero
    # la quitamos para evitar advertencias.
    s = re.sub(r"^\s*\.section \.note\.GNU-stack.*$", "", s, flags=re.M)
    return s, [os.path.join(DRIVER_DIR, "runtime_win.c")]


def build_program(asm_path, name="programa"):
    """Ensambla el .s (con puente de ABI si hace falta) a un ejecutable nativo.
    Devuelve (exe_path, log)."""
    gcc = _find_tool("gcc")
    if not gcc:
        raise ToolError("No se encontro 'gcc' para ensamblar el codigo generado.")
    if not asm_path or not os.path.isfile(asm_path):
        raise ToolError("No hay archivo .s para ensamblar (¿fallo la generacion de codigo?).")

    with open(asm_path, encoding="utf-8", errors="replace") as f:
        asm_text = f.read()
    asm_final, extra = _prepare_asm_for_platform(asm_text)

    base = re.sub(r"[^A-Za-z0-9_]", "_", name) or "programa"
    build_s = os.path.join(WORK_DIR, base + "_link.s")
    with open(build_s, "w", encoding="utf-8") as f:
        f.write(asm_final)

    exe_path = os.path.join(WORK_DIR, base + EXE_SUFFIX)
    cmd = [gcc, build_s, *extra, "-o", exe_path]
    env = _tool_dir_env(gcc)
    res = _run(cmd, env=env, timeout=120)
    log = "Ensamblando:\n  " + " ".join(cmd) + "\n\n" + res.stdout + res.stderr
    if res.returncode != 0 or not os.path.isfile(exe_path):
        raise ToolError("Error al ensamblar el codigo generado:\n\n" + log)
    return exe_path, log + "\nEnsamblado: OK\n" + exe_path


# --- 4. Ejecutar el binario -------------------------------------------------
def run_program(exe_path, stdin_text="", timeout=15):
    """Ejecuta el binario compilado y devuelve un dict con stdout/stderr/exit."""
    gcc = _find_tool("gcc")
    env = _tool_dir_env(gcc)   # asegura DLLs de runtime en el PATH (Windows)
    try:
        res = _run([exe_path], env=env, stdin=stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"Tiempo excedido (> {timeout}s).",
                "returncode": None, "timeout": True}
    return {"stdout": res.stdout, "stderr": res.stderr,
            "returncode": res.returncode, "timeout": False}


# --- Uso por linea de comandos (pruebas rapidas) ----------------------------
if __name__ == "__main__":
    info = toolchain_info()
    print("Toolchain:", info)
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            src = f.read()
        build_driver()
        r = compile_source(src, name=os.path.basename(sys.argv[1]))
        for ph in r["phases"]:
            print(f"  [{ph['status']:8}] {ph['label']} {ph['message']}")
        if r["ok"]:
            exe, _ = build_program(r["asm_path"], name="cli_test")
            run = run_program(exe)
            print("--- salida ---")
            print(run["stdout"])
            print("exit:", run["returncode"])
