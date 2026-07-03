/* ===========================================================================
 * runtime_win.c — Puente de ABI para ejecutar el x86-64 generado en Windows
 * ===========================================================================
 * El compilador emite ensamblador con la ABI System V de Linux: los
 * argumentos enteros/punteros viajan en %rdi, %rsi, ... y los flotantes en
 * %xmm0, y las llamadas van a printf/malloc/... con esa convencion.
 *
 * En Windows (mingw/ucrt) la libc usa la ABI Win64 (argumentos en
 * %rcx, %rdx, %r8, %r9). Llamar directo a printf desde ese codigo produce un
 * segfault porque los argumentos quedan en los registros equivocados.
 *
 * Solucion: exponer envoltorios NO variadicos marcados __attribute__((sysv_abi)).
 * El codigo generado los llama con la ABI SysV (que es como fue emitido) y
 * cada envoltorio reenvia a la libc nativa con la ABI por defecto (Win64).
 * Al ser no variadicos, no hace falta trasladar un va_list entre ABIs.
 *
 * El script de build (backend.py) reescribe las llamadas del .s hacia estos
 * simbolos SOLO en Windows. En Linux no se usa: se ensambla el .s tal cual.
 * ===========================================================================
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SYSV __attribute__((sysv_abi))

/* --- Impresion (los formatos vienen de .data del propio .s) --------------- */
SYSV int __sysv_print_int(const char *fmt, long v)          { return printf(fmt, v); }
SYSV int __sysv_print_str(const char *fmt, const char *s)   { return printf(fmt, s ? s : "(null)"); }
SYSV int __sysv_print_flt(const char *fmt, double v)        { return printf(fmt, v); }
SYSV int __sysv_print_nl (const char *fmt)                  { return fputs(fmt, stdout); }

/* --- Memoria y cadenas ---------------------------------------------------- */
SYSV void *__sysv_malloc(long n)                            { return malloc((size_t)n); }
SYSV void *__sysv_calloc(long n, long s)                   { return calloc((size_t)n, (size_t)s); }
SYSV long  __sysv_strlen(const char *s)                    { return (long)strlen(s); }
SYSV char *__sysv_strcpy(char *d, const char *s)           { return strcpy(d, s); }
SYSV char *__sysv_strcat(char *d, const char *s)           { return strcat(d, s); }
