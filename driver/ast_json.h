#ifndef AST_JSON_H
#define AST_JSON_H
#include <ostream>
class Programa;
// Vuelca el AST real construido por el parser del compilador como un arbol
// JSON ({"n","label","children":[...]}) que el IDE en Python renderiza.
void dumpAstJson(Programa* programa, std::ostream& out);
#endif
