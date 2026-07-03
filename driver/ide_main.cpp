// ===========================================================================
// ide_main.cpp — Driver del compilador para el IDE
// ===========================================================================
// Sustituye a main.cpp del proyecto (NO se modifica el repo original: este
// archivo se compila junto a los .cpp del compilador desde la carpeta idle/).
//
// Ejecuta las 4 fases del compilador y produce artefactos separados que el
// IDE en Python lee y muestra:
//     <base>_tokens.txt   volcado lexico (lo escribe ejecutar_scanner)
//     <base>_ast.json     AST real del parser (dumpAstJson)
//     <base>.s            ensamblador x86-64 (GenCode)
//
// A stdout emite una linea "FASE|<nombre>|OK" o "FASE|<nombre>|ERROR|<msg>"
// por cada fase, para que el IDE muestre el estado de cada una sin parsear
// texto libre.
//
// Uso:  ide_driver <archivo.go-> <directorio_de_salida>
// ---------------------------------------------------------------------------
#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <cstdlib>

#include "scanner.h"
#include "parser.h"
#include "ast.h"
#include "GenCode.h"
#include "ast_json.h"

using namespace std;

// El TypeChecker/GenCode del proyecto abortan con exit(1) e imprimen
// "Error semantico: ..." a stdout/cerr. Para que el IDE capture ese mensaje
// como fallo de la fase semantica, redirigimos: nada especial hace falta,
// exit(1) tras un "FASE|semantica|..." no impreso => el IDE lo detecta por
// codigo de salida y por el texto capturado. Emitimos un marcador previo.

static string baseName(const string& path) {
    size_t slash = path.find_last_of("/\\");
    string f = (slash == string::npos) ? path : path.substr(slash + 1);
    size_t dot = f.find_last_of('.');
    return (dot == string::npos) ? f : f.substr(0, dot);
}

int main(int argc, const char* argv[]) {
    if (argc < 2) {
        cout << "Uso: " << argv[0] << " <archivo_entrada> [dir_salida]" << endl;
        return 2;
    }
    string inPath  = argv[1];
    string outDir  = (argc >= 3) ? argv[2] : ".";
    string base    = baseName(inPath);
    string tokPath = outDir + "/" + base + "_tokens.txt";
    string astPath = outDir + "/" + base + "_ast.json";
    string asmPath = outDir + "/" + base + ".s";

    ifstream infile(inPath);
    if (!infile.is_open()) {
        cout << "FASE|entrada|ERROR|No se pudo abrir el archivo: " << inPath << endl;
        return 1;
    }
    stringstream ss;
    ss << infile.rdbuf();
    string input = ss.str();
    infile.close();
    if (input.empty() || input.back() != '\n') input += '\n';

    // ---- Fase 1: lexica ----------------------------------------------------
    // ejecutar_scanner escribe "<base sin ext>_tokens.txt" JUNTO al input.
    // Le pasamos una ruta cuyo prefijo apunte al outDir para controlar donde
    // cae el volcado.
    Scanner scannerDump(input.c_str());
    string tokStem = outDir + "/" + base + ".ignore";  // -> <outDir>/<base>_tokens.txt
    ejecutar_scanner(&scannerDump, tokStem);
    cout << "FASE|lexica|OK" << endl;
    cout.flush();

    // ---- Fase 2: sintactica ------------------------------------------------
    Scanner scannerParse(input.c_str());
    Parser parser(&scannerParse);
    Programa* ast = nullptr;
    try {
        ast = parser.parseProgram();
    } catch (const std::exception& e) {
        cout << "FASE|sintactica|ERROR|" << e.what() << endl;
        return 1;
    } catch (...) {
        cout << "FASE|sintactica|ERROR|Error de sintaxis desconocido" << endl;
        return 1;
    }
    cout << "FASE|sintactica|OK" << endl;
    cout.flush();

    // Volcado del AST (siempre que el parseo haya sido exitoso).
    {
        ofstream astOut(astPath);
        if (astOut.is_open()) {
            dumpAstJson(ast, astOut);
            astOut.close();
            cout << "FASE|ast|OK" << endl;
        } else {
            cout << "FASE|ast|ERROR|No se pudo escribir " << astPath << endl;
        }
        cout.flush();
    }

    // ---- Fase 3: semantica -------------------------------------------------
    // GenCode::tipos.TypeCheker aborta con exit(1) si algo no valida (imprime
    // su propio "Error semantico: ..."). Marcamos ANTES para que, si sale por
    // exit, el IDE sepa que fue en la fase semantica.
    ostringstream asmBuffer;
    GenCode gen(asmBuffer);
    cout << "FASE|semantica|BEGIN" << endl;
    cout.flush();
    gen.tipos.TypeCheker(ast);
    cout << "FASE|semantica|OK" << endl;
    cout.flush();

    // ---- Fase 4: generacion de codigo x86-64 -------------------------------
    cout << "FASE|codegen|BEGIN" << endl;
    cout.flush();
    gen.generar(ast);

    ofstream asmOut(asmPath);
    if (!asmOut.is_open()) {
        cout << "FASE|codegen|ERROR|No se pudo crear " << asmPath << endl;
        delete ast;
        return 1;
    }
    asmOut << asmBuffer.str();
    asmOut.close();
    cout << "FASE|codegen|OK" << endl;
    cout.flush();

    delete ast;
    return 0;
}
