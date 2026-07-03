"""
ide.py — IDE del compilador (subconjunto de Go -> x86-64)
=========================================================
Aplicacion de escritorio (Tkinter) que demuestra las fases del compilador C++
del proyecto y las caracteristicas del lenguaje. Requisitos cubiertos:

  * Editor de codigo para el lenguaje disenado (con resaltado de sintaxis).
  * Visualizacion del AST (arbol real construido por el parser del compilador).
  * Generacion de codigo ensamblador x86-64 (salida real de GenCode).
  * Ejecucion/simulacion del programa compilado (ensambla y corre el binario).
  * Visualizacion de resultados de ejecucion (stdout/stderr/codigo de salida).

Toda la interaccion con el compilador vive en backend.py. La UI corre las
tareas pesadas (build/compile/run) en hilos para no congelar la ventana.
"""

import json
import os
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

import backend

# --- Paleta (tema oscuro azul/verde, tipo editor) --------------------------
BG        = "#0b1521"
BG_PANEL  = "#0e1c2b"
BG_EDITOR = "#0b1521"
BG_RAISED = "#122335"   # paneles ligeramente elevados (headers, tabs activos)
FG        = "#dbe9f4"
FG_DIM    = "#5f7c91"
ACCENT    = "#4fc3e0"   # azul-cian principal
ACCENT2   = "#4fd8b0"   # verde-turquesa secundario (AST, acentos)
OK_COLOR  = "#5fd88f"
ERR_COLOR = "#ef7b7b"
WARN_COLOR = "#e8c072"
GUTTER_BG = BG_EDITOR    # mismo fondo que el editor: sin costura visible
SEL_BG    = "#173247"
EDITOR_FONT = ("Consolas", 12)
MONO_FONT   = ("Consolas", 11)
UI_FONT     = ("Segoe UI", 10)

# Colores de tokens para el resaltado del editor
SYN = {
    "keyword": "#6fb8f2",
    "type":    "#4fd8b0",
    "builtin": "#e8c072",
    "string":  "#8fdc9a",
    "number":  "#67cde0",
    "comment": "#516575",
    "op":      "#4fc3e0",
}

# Estilo del arbol AST: (predicado sobre el label crudo) -> (icono, tag)
def _ast_icon_and_tag(label):
    if label == "Programa":
        return "✦", "root"                      # ✦
    if label.startswith("FunctionDecl") or label.startswith("MethodDecl"):
        return "ƒ", "func"                       # ƒ
    if label.startswith("Call:"):
        return "λ", "call"                       # λ
    if label.startswith("VarDecl") or label.startswith("var "):
        return "●", "var"                        # ●
    if label.startswith("ConstDecl") or label.startswith("const "):
        return "●", "const"
    if label.startswith("TypeDecl") or label.startswith("type ") or label.startswith("campo:"):
        return "◆", "type"                       # ◆
    if label.startswith("Literal ("):
        if "string" in label.split(")")[0]:
            return "❝", "lit_str"                # ❝
        return "❝", "lit_num"
    if label.startswith("Ident:"):
        return "◇", "ident"                      # ◇
    if (label.startswith("BinaryExp") or label.startswith("UnaryExp")
            or label.startswith("Assignment") or label.startswith("IncDecStmt")):
        return "±", "op"                         # ±
    if label in ("IfStmt", "ForStmt", "SwitchStmt", "ReturnStmt", "BreakStmt",
                 "ContinueStmt", "BlockStmt", "DeclStmt", "ExprStmt", "ForClause"):
        return "▸", "flow"                       # ▸
    if label in ("then", "else", "else-if", "condicion", "case", "default",
                 "cuerpo", "init", "post"):
        return "▸", "flow"
    return "·", "dim"                            # ·


AST_TAG_COLORS = {
    "root": ACCENT2,
    "func": ACCENT2,
    "call": ACCENT2,
    "var": ACCENT,
    "const": WARN_COLOR,
    "type": "#4fd8b0",
    "lit_str": OK_COLOR,
    "lit_num": "#67cde0",
    "ident": FG,
    "op": WARN_COLOR,
    "flow": ACCENT,
    "dim": FG_DIM,
}

KEYWORDS = {
    "break", "case", "const", "continue", "default", "else", "for", "func",
    "if", "return", "struct", "switch", "type", "var",
}
TYPES = {"int", "float64", "bool", "string"}
BUILTINS = {"println", "print", "true", "false", "new", "make", "len"}

INDENT_WIDTH = 4  # ancho de indentacion (en espacios) que inserta la tecla Tab

# --- Coloreado del volcado de tokens (TOKEN(TIPO, "texto") [line N]) --------
TOKEN_LINE_RE = re.compile(
    r'TOKEN\((?P<type>\w+)(?:,\s*"(?P<text>(?:[^"\\]|\\.)*)")?\)(?P<lineinfo>\s*\[line\s*\d+\])?'
)
TOK_KEYWORDS = {
    "BREAK", "CASE", "CHAN", "CONST", "CONTINUE", "DEFAULT", "DEFER", "ELSE",
    "FALLTHROUGH", "FOR", "FUNC", "GO", "GOTO", "IF", "IMPORT", "INTERFACE",
    "MAP", "PACKAGE", "RANGE", "RETURN", "SELECT", "STRUCT", "SWITCH", "TYPE",
    "VAR",
}
TOK_NUM = {"INT_LIT", "FLOAT_LIT", "IMAGINARY_LIT", "RUNE_LIT"}
TOK_STR = {"STRING_LIT"}


def _token_tag(type_name):
    if type_name in TOK_KEYWORDS:
        return "tok_keyword"
    if type_name in TOK_NUM:
        return "tok_num"
    if type_name in TOK_STR:
        return "tok_str"
    if type_name == "ID":
        return "tok_id"
    if type_name == "ERROR":
        return "tok_error"
    if type_name == "END":
        return "tok_end"
    return "tok_op"


EXAMPLE_DIR = os.path.join(backend.IDLE_DIR, "examples")


class CompilerIDE(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Compilador Go- → x86-64  |  IDE de fases de compilacion")
        self.geometry("1280x820")
        self.configure(bg=BG)
        self.minsize(1000, 640)

        self.current_file = None
        self.last_result = None      # ultimo dict de compile_source
        self._msgq = queue.Queue()   # mensajes de hilos de trabajo -> UI
        self._busy = False

        self._build_style()
        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()

        self.after(80, self._pump_queue)
        self._load_default_source()
        self._check_toolchain_async()

    # -- Estilos ttk ---------------------------------------------------------
    def _build_style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=BG, borderwidth=0, focuscolor=ACCENT)
        # 'clam' dibuja bordes/bisel en tonos claros por defecto (bordercolor,
        # lightcolor, darkcolor) sin importar el borderwidth; se fuerzan al
        # tono del panel para que no aparezcan lineas claras encima del tema oscuro.
        st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(2, 4, 2, 0),
                     bordercolor=BG, lightcolor=BG, darkcolor=BG)
        st.configure("TNotebook.Tab", background=BG_PANEL, foreground=FG_DIM,
                     padding=(16, 7), font=UI_FONT, borderwidth=0,
                     bordercolor=BG_PANEL, lightcolor=BG_PANEL, darkcolor=BG_PANEL)
        st.map("TNotebook.Tab",
               background=[("selected", BG_RAISED)], foreground=[("selected", ACCENT)],
               lightcolor=[("selected", BG_RAISED)], darkcolor=[("selected", BG_RAISED)],
               bordercolor=[("selected", BG_RAISED)])
        st.configure("Treeview", background=BG_EDITOR, fieldbackground=BG_EDITOR,
                     foreground=FG, borderwidth=0, font=MONO_FONT, rowheight=24,
                     indent=20)
        st.map("Treeview", background=[("selected", SEL_BG)],
               foreground=[("selected", ACCENT2)])
        st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.configure("Vertical.TScrollbar", background=BG_PANEL, troughcolor=BG,
                     borderwidth=0, arrowcolor=FG_DIM, width=10,
                     bordercolor=BG, lightcolor=BG_PANEL, darkcolor=BG_PANEL)
        st.map("Vertical.TScrollbar", background=[("active", SEL_BG)])
        st.configure("TPanedwindow", background=BG)
        st.configure("Sash", sashthickness=6, gripcount=0,
                     bordercolor=BG, lightcolor=BG, darkcolor=BG)

    # -- Menu ----------------------------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self)
        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="Nuevo", command=self.on_new, accelerator="Ctrl+N")
        m_file.add_command(label="Abrir...", command=self.on_open, accelerator="Ctrl+O")
        m_file.add_command(label="Guardar", command=self.on_save, accelerator="Ctrl+S")
        m_file.add_separator()
        m_file.add_command(label="Salir", command=self.destroy)
        menubar.add_cascade(label="Archivo", menu=m_file)

        m_ex = tk.Menu(menubar, tearoff=0)
        for label, fname in self._example_list():
            m_ex.add_command(label=label, command=lambda f=fname: self._load_example(f))
        menubar.add_cascade(label="Ejemplos", menu=m_ex)

        m_run = tk.Menu(menubar, tearoff=0)
        m_run.add_command(label="Compilar (fases)", command=self.on_compile, accelerator="F5")
        m_run.add_command(label="Compilar y ejecutar", command=self.on_compile_run, accelerator="F6")
        m_run.add_separator()
        m_run.add_command(label="Recompilar driver del compilador",
                          command=lambda: self._build_driver_async(force=True))
        menubar.add_cascade(label="Compilar", menu=m_run)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="Diagnostico del toolchain", command=self.on_diagnostics)
        m_help.add_command(label="Acerca de", command=self.on_about)
        menubar.add_cascade(label="Ayuda", menu=m_help)

        self.config(menu=menubar)
        self.bind_all("<Control-n>", lambda e: self.on_new())
        self.bind_all("<Control-o>", lambda e: self.on_open())
        self.bind_all("<Control-s>", lambda e: self.on_save())
        self.bind_all("<F5>", lambda e: self.on_compile())
        self.bind_all("<F6>", lambda e: self.on_compile_run())

    # -- Toolbar -------------------------------------------------------------
    def _build_toolbar(self):
        bar = tk.Frame(self, bg=BG_PANEL, highlightthickness=0)
        bar.pack(side=tk.TOP, fill=tk.X)

        def btn(text, cmd, accent=False):
            base_bg = ACCENT if accent else BG_RAISED
            base_fg = BG if accent else FG
            hover_bg = ACCENT2 if accent else SEL_BG
            b = tk.Button(bar, text=text, command=cmd, font=UI_FONT,
                          bg=base_bg, fg=base_fg,
                          activebackground=hover_bg, activeforeground=base_fg,
                          relief=tk.FLAT, padx=14, pady=6, cursor="hand2",
                          borderwidth=0, highlightthickness=0)
            b.pack(side=tk.LEFT, padx=(8, 0), pady=8)
            b.bind("<Enter>", lambda e: b.configure(bg=hover_bg))
            b.bind("<Leave>", lambda e: b.configure(bg=base_bg))
            return b

        self.btn_compile = btn("▶  Compilar  (F5)", self.on_compile)
        self.btn_run = btn("⚡  Compilar y ejecutar  (F6)", self.on_compile_run, accent=True)
        btn("\U0001F4C2  Abrir", self.on_open)
        btn("\U0001F4BE  Guardar", self.on_save)

        self.lbl_toolchain = tk.Label(bar, text="toolchain: comprobando...",
                                      bg=BG_PANEL, fg=FG_DIM, font=UI_FONT)
        self.lbl_toolchain.pack(side=tk.RIGHT, padx=12)

    # -- Cuerpo (editor | resultados) ----------------------------------------
    def _build_body(self):
        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # --- Izquierda: editor con numeros de linea ---
        left = tk.Frame(paned, bg=BG_EDITOR, highlightthickness=0)
        paned.add(left, weight=3)

        header = tk.Frame(left, bg=BG_PANEL, highlightthickness=0)
        header.pack(fill=tk.X)
        tk.Label(header, text="Editor  —  lenguaje Go- (subconjunto)",
                 bg=BG_PANEL, fg=ACCENT, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=10, pady=6)
        self.lbl_file = tk.Label(header, text="(sin titulo)", bg=BG_PANEL, fg=FG_DIM, font=UI_FONT)
        self.lbl_file.pack(side=tk.RIGHT, padx=10)

        edit_frame = tk.Frame(left, bg=BG_EDITOR, highlightthickness=0)
        edit_frame.pack(fill=tk.BOTH, expand=True)

        self.gutter = tk.Text(edit_frame, width=5, bg=GUTTER_BG, fg=FG_DIM,
                              font=EDITOR_FONT, relief=tk.FLAT, state=tk.DISABLED,
                              takefocus=0, padx=6, pady=8, cursor="arrow",
                              highlightthickness=0, borderwidth=0)
        self.gutter.pack(side=tk.LEFT, fill=tk.Y)

        self.editor = tk.Text(edit_frame, bg=BG_EDITOR, fg=FG, insertbackground=ACCENT,
                              font=EDITOR_FONT, relief=tk.FLAT, undo=True, wrap=tk.NONE,
                              padx=8, pady=8, selectbackground=SEL_BG,
                              highlightthickness=0, borderwidth=0)
        self.editor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Ancho de tabulacion real (en pixeles) equivalente a INDENT_WIDTH
        # espacios en la fuente del editor, para que un tab literal (o la
        # tecla Tab, ver mas abajo) siempre caiga alineado a la grilla.
        _tabstop = tkfont.Font(font=EDITOR_FONT).measure(" " * INDENT_WIDTH)
        self.editor.configure(tabs=(_tabstop,))

        yscroll = ttk.Scrollbar(edit_frame, orient=tk.VERTICAL, command=self._on_editor_scroll)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.editor.configure(yscrollcommand=self._editor_yscroll)
        self._yscroll = yscroll

        for tag, color in SYN.items():
            self.editor.tag_configure(tag, foreground=color)
        self.editor.tag_configure("errline", background="#3a2230")

        self.editor.bind("<KeyRelease>", self._on_editor_change)
        self.editor.bind("<MouseWheel>", lambda e: self.after(1, self._sync_gutter))
        self.editor.bind("<Configure>", lambda e: self._sync_gutter())
        self.editor.bind("<Tab>", self._on_tab)
        self.editor.bind("<Shift-Tab>", self._on_shift_tab)
        self.editor.bind("<ISO_Left_Tab>", self._on_shift_tab)  # Shift-Tab en Linux/X11

        # --- Derecha: pestanas de fases ---
        right = tk.Frame(paned, bg=BG, highlightthickness=0)
        paned.add(right, weight=4)
        self._build_phase_strip(right)

        self.nb = ttk.Notebook(right)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=(6, 4))
        self._build_tab_tokens()
        self._build_tab_ast()
        self._build_tab_asm()
        self._build_tab_run()

    def _build_phase_strip(self, parent):
        """Fila de indicadores de estado de las 5 fases, como una linea de tiempo fluida."""
        strip = tk.Frame(parent, bg=BG_PANEL, highlightthickness=0)
        strip.pack(fill=tk.X, padx=4, pady=(4, 0))
        self.phase_labels = {}
        phases = [
            ("lexica", "Lexico"),
            ("sintactica", "Sintaxis"),
            ("ast", "AST"),
            ("semantica", "Semantica"),
            ("codegen", "Codegen"),
        ]
        for i, (key, text) in enumerate(phases):
            if i > 0:
                tk.Label(strip, text="―", bg=BG_PANEL, fg="#233850",
                         font=("Segoe UI", 9)).pack(side=tk.LEFT)
            lbl = tk.Label(strip, text="○ " + text, bg=BG_PANEL, fg=FG_DIM,
                           font=("Segoe UI", 9), padx=8, pady=8)
            lbl.pack(side=tk.LEFT)
            self.phase_labels[key] = lbl

    def _build_tab_tokens(self):
        frame = tk.Frame(self.nb, bg=BG_EDITOR)
        self.nb.add(frame, text="  Tokens  ")
        self.txt_tokens = self._make_output_text(frame)
        self.txt_tokens.tag_configure("tok_keyword", foreground=SYN["keyword"])
        self.txt_tokens.tag_configure("tok_num", foreground=SYN["number"])
        self.txt_tokens.tag_configure("tok_str", foreground=SYN["string"])
        self.txt_tokens.tag_configure("tok_id", foreground=ACCENT2)
        self.txt_tokens.tag_configure("tok_op", foreground=SYN["op"])
        self.txt_tokens.tag_configure("tok_error", foreground=ERR_COLOR)
        self.txt_tokens.tag_configure("tok_end", foreground=FG_DIM)
        self.txt_tokens.tag_configure("tok_line", foreground=FG_DIM)
        self.txt_tokens.tag_configure("tok_header", foreground=ACCENT,
                                       font=(MONO_FONT[0], MONO_FONT[1], "bold"))
        self.txt_tokens.tag_configure("tok_ok", foreground=OK_COLOR)
        self.txt_tokens.tag_configure("tok_fail", foreground=ERR_COLOR)

    def _build_tab_ast(self):
        frame = tk.Frame(self.nb, bg=BG_EDITOR)
        self.nb.add(frame, text="  AST  ")
        bar = tk.Frame(frame, bg=BG_EDITOR, highlightthickness=0)
        bar.pack(fill=tk.X)

        def tbtn(text, cmd):
            b = tk.Button(bar, text=text, command=cmd, font=UI_FONT, bg=BG_EDITOR,
                          fg=FG_DIM, activebackground=BG_EDITOR, activeforeground=ACCENT2,
                          relief=tk.FLAT, padx=8, pady=4, cursor="hand2", borderwidth=0,
                          highlightthickness=0)
            b.pack(side=tk.LEFT, padx=(8, 0), pady=6)
            b.bind("<Enter>", lambda e: b.configure(fg=ACCENT2))
            b.bind("<Leave>", lambda e: b.configure(fg=FG_DIM))
            return b

        tbtn("▾ Expandir todo", lambda: self._expand_tree(True))
        tbtn("▸ Colapsar todo", lambda: self._expand_tree(False))

        tree_frame = tk.Frame(frame, bg=BG_EDITOR, highlightthickness=0)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=(4, 0))
        self.ast_tree = ttk.Treeview(tree_frame, show="tree")
        self.ast_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for tag, color in AST_TAG_COLORS.items():
            self.ast_tree.tag_configure(tag, foreground=color)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.ast_tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.ast_tree.configure(yscrollcommand=sb.set)

    def _build_tab_asm(self):
        frame = tk.Frame(self.nb, bg=BG_EDITOR)
        self.nb.add(frame, text="  Ensamblador x86-64  ")
        self.txt_asm = self._make_output_text(frame)
        self.txt_asm.tag_configure("directive", foreground="#6fb8f2")
        self.txt_asm.tag_configure("label", foreground="#e8c072")
        self.txt_asm.tag_configure("mnem", foreground="#4fd8b0")
        self.txt_asm.tag_configure("comment", foreground="#516575")

    def _build_tab_run(self):
        frame = tk.Frame(self.nb, bg=BG_EDITOR)
        self.nb.add(frame, text="  Ejecucion  ")

        tk.Label(frame, text="Entrada estandar (stdin) opcional:",
                 bg=BG_EDITOR, fg=FG_DIM, font=UI_FONT, anchor="w").pack(fill=tk.X, padx=8, pady=(6, 0))
        self.txt_stdin = tk.Text(frame, height=3, bg=BG_RAISED, fg=FG, insertbackground=ACCENT,
                                 font=MONO_FONT, relief=tk.FLAT, padx=8, pady=4,
                                 highlightthickness=0, borderwidth=0)
        self.txt_stdin.pack(fill=tk.X, padx=8, pady=(2, 6))

        tk.Label(frame, text="Salida del programa:",
                 bg=BG_EDITOR, fg=FG_DIM, font=UI_FONT, anchor="w").pack(fill=tk.X, padx=8)
        self.txt_run = self._make_output_text(frame)
        self.txt_run.tag_configure("stderr", foreground=ERR_COLOR)
        self.txt_run.tag_configure("meta", foreground=FG_DIM)
        self.txt_run.tag_configure("ok", foreground=OK_COLOR)

    def _make_output_text(self, parent):
        wrap = tk.Frame(parent, bg=BG_EDITOR, highlightthickness=0)
        wrap.pack(fill=tk.BOTH, expand=True)
        txt = tk.Text(wrap, bg=BG_EDITOR, fg=FG, insertbackground=FG, font=MONO_FONT,
                      relief=tk.FLAT, wrap=tk.NONE, padx=8, pady=6, state=tk.DISABLED,
                      highlightthickness=0, borderwidth=0)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=txt.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.configure(yscrollcommand=sb.set)
        return txt

    # -- Barra de estado -----------------------------------------------------
    def _build_statusbar(self):
        self.status = tk.Label(self, text="Listo.", bg=BG_PANEL, fg=FG_DIM,
                               font=UI_FONT, anchor="w", padx=10, pady=4)
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    # ======================================================================
    #  Editor: numeros de linea + resaltado
    # ======================================================================
    def _editor_yscroll(self, *args):
        self._yscroll.set(*args)
        self._sync_gutter()

    def _on_editor_scroll(self, *args):
        self.editor.yview(*args)
        self._sync_gutter()

    def _sync_gutter(self):
        self.gutter.configure(state=tk.NORMAL)
        self.gutter.delete("1.0", tk.END)
        total = int(self.editor.index("end-1c").split(".")[0])
        nums = "\n".join(str(i) for i in range(1, total + 1))
        self.gutter.insert("1.0", nums)
        self.gutter.configure(state=tk.DISABLED)
        self.gutter.yview_moveto(self.editor.yview()[0])

    def _on_editor_change(self, event=None):
        self._highlight()
        self._sync_gutter()

    # -- Tecla Tab: indenta a espacios fijos en vez de un caracter de tab
    #    real (que caia en una posicion inconsistente con la grilla). ------
    def _on_tab(self, event=None):
        try:
            sel_start = self.editor.index(tk.SEL_FIRST)
            sel_end = self.editor.index(tk.SEL_LAST)
        except tk.TclError:
            sel_start = sel_end = None

        if sel_start and int(sel_start.split(".")[0]) != int(sel_end.split(".")[0]):
            self._indent_lines(sel_start, sel_end, INDENT_WIDTH)
        else:
            col = int(self.editor.index(tk.INSERT).split(".")[1])
            width = INDENT_WIDTH - (col % INDENT_WIDTH)
            self.editor.insert(tk.INSERT, " " * width)
        self._on_editor_change()
        return "break"

    def _on_shift_tab(self, event=None):
        try:
            sel_start = self.editor.index(tk.SEL_FIRST)
            sel_end = self.editor.index(tk.SEL_LAST)
        except tk.TclError:
            sel_start = sel_end = None

        if sel_start and int(sel_start.split(".")[0]) != int(sel_end.split(".")[0]):
            self._indent_lines(sel_start, sel_end, -INDENT_WIDTH)
        else:
            line_start = f"{self.editor.index(tk.INSERT).split('.')[0]}.0"
            line_text = self.editor.get(line_start, f"{line_start} lineend")
            stripped = len(line_text) - len(line_text.lstrip(" "))
            remove = min(INDENT_WIDTH, stripped)
            if remove:
                self.editor.delete(line_start, f"{line_start}+{remove}c")
        self._on_editor_change()
        return "break"

    def _indent_lines(self, sel_start, sel_end, delta):
        first = int(sel_start.split(".")[0])
        last = int(sel_end.split(".")[0])
        if sel_end.split(".")[1] == "0" and last > first:
            last -= 1
        for ln in range(first, last + 1):
            line_start = f"{ln}.0"
            if delta > 0:
                self.editor.insert(line_start, " " * delta)
            else:
                line_text = self.editor.get(line_start, f"{line_start} lineend")
                stripped = len(line_text) - len(line_text.lstrip(" "))
                remove = min(-delta, stripped)
                if remove:
                    self.editor.delete(line_start, f"{line_start}+{remove}c")

    def _highlight(self):
        text = self.editor.get("1.0", tk.END)
        for tag in SYN:
            self.editor.tag_remove(tag, "1.0", tk.END)
        self.editor.tag_remove("errline", "1.0", tk.END)

        # Comentarios de linea //...
        for m in re.finditer(r"//[^\n]*", text):
            self._tag_span("comment", m.start(), m.end(), text)
        # Cadenas "..."
        for m in re.finditer(r'"(?:\\.|[^"\\])*"', text):
            self._tag_span("string", m.start(), m.end(), text)
        # Numeros
        for m in re.finditer(r"\b\d+(?:\.\d+)?\b", text):
            self._tag_span("number", m.start(), m.end(), text)
        # Identificadores / palabras clave
        for m in re.finditer(r"\b[A-Za-z_]\w*\b", text):
            w = m.group(0)
            if w in KEYWORDS:
                self._tag_span("keyword", m.start(), m.end(), text)
            elif w in TYPES:
                self._tag_span("type", m.start(), m.end(), text)
            elif w in BUILTINS:
                self._tag_span("builtin", m.start(), m.end(), text)

    def _tag_span(self, tag, start, end, text):
        s = f"1.0+{start}c"
        e = f"1.0+{end}c"
        self.editor.tag_add(tag, s, e)

    # ======================================================================
    #  Acciones de archivo / ejemplos
    # ======================================================================
    def _example_list(self):
        items = []
        if os.path.isdir(EXAMPLE_DIR):
            for fn in sorted(os.listdir(EXAMPLE_DIR)):
                if fn.endswith(".go-") or fn.endswith(".txt"):
                    items.append((fn, os.path.join(EXAMPLE_DIR, fn)))
        return items

    def _load_example(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                self._set_editor_text(f.read())
            self.current_file = None
            self.lbl_file.configure(text="ejemplo: " + os.path.basename(path))
            self._set_status(f"Ejemplo cargado: {os.path.basename(path)}")
        except OSError as e:
            messagebox.showerror("Error", str(e))

    def _load_default_source(self):
        ex = self._example_list()
        if ex:
            self._load_example(ex[0][1])
        else:
            self._set_editor_text(DEFAULT_SOURCE)

    def _set_editor_text(self, text):
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", text)
        self._highlight()
        self._sync_gutter()

    def on_new(self):
        self._set_editor_text("")
        self.current_file = None
        self.lbl_file.configure(text="(sin titulo)")

    def on_open(self):
        path = filedialog.askopenfilename(
            initialdir=EXAMPLE_DIR,
            filetypes=[("Fuente Go-", "*.go- *.txt"), ("Todos", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                self._set_editor_text(f.read())
            self.current_file = path
            self.lbl_file.configure(text=os.path.basename(path))
            self._set_status(f"Abierto: {path}")
        except OSError as e:
            messagebox.showerror("Error", str(e))

    def on_save(self):
        if not self.current_file:
            path = filedialog.asksaveasfilename(
                defaultextension=".go-", initialdir=EXAMPLE_DIR,
                filetypes=[("Fuente Go-", "*.go-"), ("Texto", "*.txt")])
            if not path:
                return
            self.current_file = path
        try:
            with open(self.current_file, "w", encoding="utf-8") as f:
                f.write(self.editor.get("1.0", "end-1c"))
            self.lbl_file.configure(text=os.path.basename(self.current_file))
            self._set_status(f"Guardado: {self.current_file}")
        except OSError as e:
            messagebox.showerror("Error", str(e))

    # ======================================================================
    #  Toolchain / driver
    # ======================================================================
    def _check_toolchain_async(self):
        def work():
            info = backend.toolchain_info()
            self._post(("toolchain", info))
        threading.Thread(target=work, daemon=True).start()

    def on_diagnostics(self):
        info = backend.toolchain_info()
        msg = (
            f"g++:  {info['g++'] or 'NO ENCONTRADO'}\n"
            f"gcc:  {info['gcc'] or 'NO ENCONTRADO'}\n\n"
            f"Proyecto del compilador:\n{info['project_dir']}\n"
            f"  {'encontrado' if info['project_ok'] else 'NO ENCONTRADO'}\n\n"
            f"Driver compilado: {'si' if os.path.isfile(backend.DRIVER_EXE) else 'no'}"
        )
        messagebox.showinfo("Diagnostico del toolchain", msg)

    def on_about(self):
        messagebox.showinfo(
            "Acerca de",
            "IDE del Compilador Go- → x86-64\n\n"
            "Demuestra las fases de compilacion (lexico, sintaxis, AST, "
            "semantica, generacion de codigo) y la ejecucion del binario x86-64 "
            "generado por el compilador C++ del proyecto.\n\n"
            "El AST y el ensamblador mostrados son la salida REAL del compilador.")

    def _build_driver_async(self, force=False, then=None):
        if self._busy:
            return
        self._set_busy(True, "Compilando el driver del compilador (una sola vez)...")

        def work():
            try:
                ok, log = backend.build_driver(force=force)
                self._post(("driver_ok", log, then))
            except backend.ToolError as e:
                self._post(("driver_err", str(e)))
            except Exception as e:  # noqa
                self._post(("driver_err", repr(e)))
        threading.Thread(target=work, daemon=True).start()

    # ======================================================================
    #  Compilar / ejecutar
    # ======================================================================
    def on_compile(self):
        self._start_pipeline(run_after=False)

    def on_compile_run(self):
        self._start_pipeline(run_after=True)

    def _start_pipeline(self, run_after):
        if self._busy:
            return
        # Asegura que el driver este compilado; luego compila la fuente.
        if not os.path.isfile(backend.DRIVER_EXE):
            self._build_driver_async(then=lambda: self._compile_async(run_after))
        else:
            self._compile_async(run_after)

    def _compile_async(self, run_after):
        source = self.editor.get("1.0", "end-1c")
        if not source.strip():
            self._set_status("Nada que compilar.")
            return
        self._reset_phase_indicators()
        self._set_busy(True, "Compilando fuente (5 fases)...")

        def work():
            try:
                result = backend.compile_source(source, name="programa")
                self._post(("compiled", result, run_after))
            except backend.ToolError as e:
                self._post(("compile_err", str(e)))
            except Exception as e:  # noqa
                self._post(("compile_err", repr(e)))
        threading.Thread(target=work, daemon=True).start()

    def _run_async(self):
        if not self.last_result or not self.last_result.get("asm_path"):
            return
        stdin_text = self.txt_stdin.get("1.0", "end-1c")
        self._set_busy(True, "Ensamblando y ejecutando el binario x86-64...")

        def work():
            try:
                exe, log = backend.build_program(self.last_result["asm_path"], name="programa")
                run = backend.run_program(exe, stdin_text=stdin_text)
                self._post(("ran", run, log))
            except backend.ToolError as e:
                self._post(("run_err", str(e)))
            except Exception as e:  # noqa
                self._post(("run_err", repr(e)))
        threading.Thread(target=work, daemon=True).start()

    # ======================================================================
    #  Cola de mensajes de hilos -> UI (Tkinter no es thread-safe)
    # ======================================================================
    def _post(self, msg):
        self._msgq.put(msg)

    def _pump_queue(self):
        try:
            while True:
                msg = self._msgq.get_nowait()
                self._handle_msg(msg)
        except queue.Empty:
            pass
        self.after(80, self._pump_queue)

    def _handle_msg(self, msg):
        kind = msg[0]
        if kind == "toolchain":
            self._apply_toolchain(msg[1])
        elif kind == "driver_ok":
            self._set_busy(False)
            self._set_status("Driver del compilador listo.")
            then = msg[2]
            if then:
                then()
        elif kind == "driver_err":
            self._set_busy(False)
            self._set_status("Error al compilar el driver.")
            messagebox.showerror("Error de compilacion del driver", msg[1])
        elif kind == "compiled":
            self._set_busy(False)
            self._apply_compile_result(msg[1], run_after=msg[2])
        elif kind == "compile_err":
            self._set_busy(False)
            self._set_status("Error al compilar la fuente.")
            messagebox.showerror("Error", msg[1])
        elif kind == "ran":
            self._set_busy(False)
            self._apply_run_result(msg[1], msg[2])
        elif kind == "run_err":
            self._set_busy(False)
            self._set_status("Error al ejecutar.")
            self._show_run_error(msg[1])

    # ======================================================================
    #  Aplicar resultados a la UI
    # ======================================================================
    def _apply_toolchain(self, info):
        if info["ok"]:
            self.lbl_toolchain.configure(text="toolchain: g++/gcc OK", fg=OK_COLOR)
        else:
            self.lbl_toolchain.configure(text="toolchain: g++/gcc NO encontrado", fg=ERR_COLOR)
            self._set_status("Falta g++/gcc. Menu Ayuda > Diagnostico del toolchain.")

    def _reset_phase_indicators(self):
        for lbl in self.phase_labels.values():
            lbl.configure(text="○ " + lbl.cget("text")[2:], fg=FG_DIM)

    def _apply_compile_result(self, result, run_after):
        self.last_result = result
        # Indicadores de fase
        icon = {"ok": "●", "error": "✖", "skipped": "○",
                "pending": "○"}
        color = {"ok": OK_COLOR, "error": ERR_COLOR, "skipped": FG_DIM,
                 "pending": FG_DIM}
        first_error = None
        for ph in result["phases"]:
            lbl = self.phase_labels[ph["key"]]
            base = lbl.cget("text")[2:]
            lbl.configure(text=icon[ph["status"]] + " " + base, fg=color[ph["status"]])
            if ph["status"] == "error" and first_error is None:
                first_error = ph

        # Tokens
        self._populate_tokens(result.get("tokens"))
        # AST
        self._populate_ast(result.get("ast"))
        # ASM
        self._populate_asm(result.get("asm"))

        if first_error:
            self._set_status(f"[{first_error['label']}] {first_error['message']}")
            self.nb.select(0)
            self._mark_error_line(first_error["message"])
        elif result["ok"]:
            self._set_status("Compilacion exitosa: las 5 fases OK.")
            if run_after:
                self._run_async()
                self.nb.select(3)
            else:
                self.nb.select(2)
        else:
            self._set_status("Compilacion incompleta.")

    def _mark_error_line(self, message):
        m = re.search(r"l[ií]nea\s+(\d+)", message, re.IGNORECASE)
        if not m:
            m = re.search(r"line\s+(\d+)", message, re.IGNORECASE)
        if m:
            ln = int(m.group(1))
            self.editor.tag_add("errline", f"{ln}.0", f"{ln}.end+1c")
            self.editor.see(f"{ln}.0")

    def _populate_tokens(self, text):
        self.txt_tokens.configure(state=tk.NORMAL)
        self.txt_tokens.delete("1.0", tk.END)
        if not text:
            self.txt_tokens.insert("1.0", "(sin volcado de tokens)")
            self.txt_tokens.configure(state=tk.DISABLED)
            return
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if stripped == "Scanner":
                self.txt_tokens.insert(tk.END, raw_line + "\n", "tok_header")
                continue
            if stripped == "Scanner exitoso":
                self.txt_tokens.insert(tk.END, raw_line + "\n", "tok_ok")
                continue
            if stripped in ("Scanner no exitoso", "Caracter invalido"):
                self.txt_tokens.insert(tk.END, raw_line + "\n", "tok_fail")
                continue
            m = TOKEN_LINE_RE.search(raw_line)
            if not m:
                self.txt_tokens.insert(tk.END, raw_line + "\n")
                continue
            lineinfo = m.group("lineinfo") or ""
            core_end = m.end() - len(lineinfo)
            self.txt_tokens.insert(tk.END, raw_line[:m.start()])
            self.txt_tokens.insert(tk.END, raw_line[m.start():core_end], _token_tag(m.group("type")))
            if lineinfo:
                self.txt_tokens.insert(tk.END, lineinfo, "tok_line")
            self.txt_tokens.insert(tk.END, raw_line[m.end():] + "\n")
        self.txt_tokens.configure(state=tk.DISABLED)

    def _populate_ast(self, ast_json):
        self.ast_tree.delete(*self.ast_tree.get_children())
        if not ast_json:
            return
        try:
            data = json.loads(ast_json)
        except json.JSONDecodeError:
            self.ast_tree.insert("", tk.END, text="(AST no disponible)")
            return

        def insert(node, parent, depth):
            label = node.get("label", "?")
            icon, tag = _ast_icon_and_tag(label)
            nid = self.ast_tree.insert(parent, tk.END, text=f"{icon}  {label}",
                                        open=(depth < 2), tags=(tag,))
            for ch in node.get("children", []):
                insert(ch, nid, depth + 1)

        insert(data, "", 0)

    def _expand_tree(self, opened):
        def walk(item):
            self.ast_tree.item(item, open=opened)
            for ch in self.ast_tree.get_children(item):
                walk(ch)
        for it in self.ast_tree.get_children(""):
            walk(it)

    def _populate_asm(self, asm):
        self.txt_asm.configure(state=tk.NORMAL)
        self.txt_asm.delete("1.0", tk.END)
        if not asm:
            self.txt_asm.insert("1.0", "(no se genero ensamblador)")
            self.txt_asm.configure(state=tk.DISABLED)
            return
        for line in asm.splitlines():
            stripped = line.strip()
            tag = None
            if stripped.startswith("."):
                tag = "directive"
            elif stripped.endswith(":"):
                tag = "label"
            elif stripped.startswith("#") or stripped.startswith("/*"):
                tag = "comment"
            elif stripped:
                tag = "mnem"
            self.txt_asm.insert(tk.END, line + "\n", tag)
        self.txt_asm.configure(state=tk.DISABLED)

    def _apply_run_result(self, run, build_log):
        self.txt_run.configure(state=tk.NORMAL)
        self.txt_run.delete("1.0", tk.END)
        if run.get("timeout"):
            self.txt_run.insert(tk.END, "[Tiempo de ejecucion excedido]\n", "stderr")
        out = run.get("stdout", "")
        err = run.get("stderr", "")
        if out:
            self.txt_run.insert(tk.END, out)
        if err:
            self.txt_run.insert(tk.END, "\n[stderr]\n", "meta")
            self.txt_run.insert(tk.END, err, "stderr")
        rc = run.get("returncode")
        self.txt_run.insert(tk.END, f"\n\n--- Proceso finalizado (codigo de salida: {rc}) ---\n",
                            "ok" if rc == 0 else "stderr")
        self.txt_run.configure(state=tk.DISABLED)
        self.nb.select(3)
        self._set_status("Ejecucion finalizada." if rc == 0 else f"El programa termino con codigo {rc}.")

    def _show_run_error(self, text):
        self.txt_run.configure(state=tk.NORMAL)
        self.txt_run.delete("1.0", tk.END)
        self.txt_run.insert("1.0", text, "stderr")
        self.txt_run.configure(state=tk.DISABLED)
        self.nb.select(3)

    # ======================================================================
    #  Utilidades UI
    # ======================================================================
    def _set_text(self, widget, text):
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state=tk.DISABLED)

    def _set_status(self, text):
        self.status.configure(text=text)

    def _set_busy(self, busy, text=None):
        self._busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.btn_compile.configure(state=state)
        self.btn_run.configure(state=state)
        if text:
            self._set_status(text)
        self.configure(cursor="watch" if busy else "")
        self.update_idletasks()


DEFAULT_SOURCE = """func main() {
    var a int = 7;
    var b int = 5;
    println(a + b);
};
"""


def main():
    app = CompilerIDE()
    app.mainloop()


if __name__ == "__main__":
    main()
