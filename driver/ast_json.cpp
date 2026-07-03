// ===========================================================================
// ast_json.cpp — Volcado del AST REAL del compilador a JSON
// ===========================================================================
// Recorre el arbol que construyo el parser (los mismos nodos de ast.h que
// consume el TypeChecker y GenCode) y lo emite como un arbol JSON simple que
// el IDE en Python dibuja en un widget de arbol. No reimplementa el parser:
// es el AST autentico, por eso sirve para la defensa del proyecto.
// ---------------------------------------------------------------------------
#include "ast_json.h"
#include "ast.h"
#include "token.h"
#include <ostream>
#include <string>
#include <vector>

using namespace std;

namespace {

// --- Escritor JSON minimo con indentacion legible -------------------------
struct J {
    ostream& o;
    explicit J(ostream& os) : o(os) {}

    static string esc(const string& s) {
        string r;
        for (char c : s) {
            switch (c) {
                case '"':  r += "\\\""; break;
                case '\\': r += "\\\\"; break;
                case '\n': r += "\\n";  break;
                case '\t': r += "\\t";  break;
                case '\r': r += "\\r";  break;
                default:   r += c;      break;
            }
        }
        return r;
    }
};

// Un nodo del arbol de salida. Se construye en memoria y luego se serializa.
struct Node {
    string label;                 // texto que ve el usuario
    vector<Node> children;
    Node() = default;
    explicit Node(string l) : label(std::move(l)) {}
    Node& add(Node n) { children.push_back(std::move(n)); return children.back(); }
    Node& add(const string& l) { children.emplace_back(l); return children.back(); }
};

void writeNode(ostream& o, const Node& n, int indent) {
    string pad(indent * 2, ' ');
    o << pad << "{\"label\":\"" << J::esc(n.label) << "\"";
    if (!n.children.empty()) {
        o << ",\"children\":[\n";
        for (size_t i = 0; i < n.children.size(); ++i) {
            writeNode(o, n.children[i], indent + 1);
            o << (i + 1 < n.children.size() ? ",\n" : "\n");
        }
        o << pad << "]";
    }
    o << "}";
}

// --- Utilidades de formato de tipos y expresiones -------------------------
string tipoToStr(Type* t);   // fwd

string exprToStr(Exp* e);    // fwd

string identListToStr(IdentifierList* il) {
    if (!il) return "";
    string r;
    bool first = true;
    for (const string& s : il->lista_ids) { if (!first) r += ", "; r += s; first = false; }
    return r;
}

string tipoToStr(Type* t) {
    if (!t) return "<inferido>";
    if (auto b = dynamic_cast<BasicType*>(t))   return b->tipo;
    if (auto p = dynamic_cast<PointerType*>(t)) return "*" + tipoToStr(p->basetype);
    if (auto a = dynamic_cast<ArrayType*>(t))   return "[" + exprToStr(a->length) + "]" + tipoToStr(a->elementtype);
    if (dynamic_cast<StructType*>(t))           return "struct{...}";
    return "?";
}

string litKind(Token::Type t) {
    switch (t) {
        case Token::INT_LIT:    return "int";
        case Token::FLOAT_LIT:  return "float64";
        case Token::STRING_LIT: return "string";
        default:                return "lit";
    }
}

string exprToStr(Exp* e) {
    if (!e) return "";
    if (auto b = dynamic_cast<BasicLitExp*>(e))   return b->valor;
    if (auto o = dynamic_cast<OperandNameExp*>(e)) return o->name;
    if (auto p = dynamic_cast<ParenExp*>(e))       return "(" + exprToStr(p->expresion) + ")";
    if (auto bi = dynamic_cast<BinaryExp*>(e))
        return exprToStr(bi->left) + " " + Exp::binopToString(bi->op) + " " + exprToStr(bi->right);
    if (auto u = dynamic_cast<UnaryExprExp*>(e)) {
        string s = Exp::unopToString(u->op);
        return u->postfix ? exprToStr(u->expresion) + s : s + exprToStr(u->expresion);
    }
    if (auto s = dynamic_cast<SelectorExp*>(e))  return exprToStr(s->expresion) + "." + s->campo;
    if (auto ix = dynamic_cast<IndexExp*>(e))    return exprToStr(ix->expresion) + "[" + exprToStr(ix->indice) + "]";
    return "expr";
}

// --- Constructores de nodos del arbol -------------------------------------
Node makeExpr(Exp* e);   // fwd
Node makeStmt(Stmt* s);  // fwd
Node makeBlock(Block* b, const string& label);

Node makeType(Type* t, const string& role) {
    Node n(role + ": " + tipoToStr(t));
    if (auto st = dynamic_cast<StructType*>(t)) {
        n.label = role + ": struct";
        for (FieldDecl* f : st->declaraciones) {
            if (!f) continue;
            n.add("campo: " + identListToStr(f->identifierlist) + " " + tipoToStr(f->type));
        }
    }
    return n;
}

Node makeExpr(Exp* e) {
    if (!e) return Node("<null>");

    if (auto b = dynamic_cast<BinaryExp*>(e)) {
        Node n("BinaryExp (" + Exp::binopToString(b->op) + ")");
        n.add(makeExpr(b->left));
        n.add(makeExpr(b->right));
        return n;
    }
    if (auto u = dynamic_cast<UnaryExprExp*>(e)) {
        Node n(string("UnaryExp (") + Exp::unopToString(u->op) + (u->postfix ? ", postfijo" : "") + ")");
        n.add(makeExpr(u->expresion));
        return n;
    }
    if (auto p = dynamic_cast<ParenExp*>(e)) {
        Node n("ParenExp");
        n.add(makeExpr(p->expresion));
        return n;
    }
    if (auto o = dynamic_cast<OperandNameExp*>(e))
        return Node("Ident: " + o->name);
    if (auto bl = dynamic_cast<BasicLitExp*>(e))
        return Node("Literal (" + litKind(bl->tipoLiteral) + "): " + bl->valor);
    if (auto s = dynamic_cast<SelectorExp*>(e)) {
        Node n("Selector (." + s->campo + ")");
        n.add(makeExpr(s->expresion));
        return n;
    }
    if (auto ix = dynamic_cast<IndexExp*>(e)) {
        Node n("Index");
        n.add(makeExpr(ix->expresion)).label = "base: " + exprToStr(ix->expresion);
        n.add(makeExpr(ix->indice)).label   = "indice: " + exprToStr(ix->indice);
        return n;
    }
    if (auto a = dynamic_cast<ArgumentsExp*>(e)) {
        Node n("Call: " + exprToStr(a->funcion) + "()");
        Node fn("funcion");
        fn.add(makeExpr(a->funcion));
        n.add(fn);
        if (a->args && !a->args->lista_exp.empty()) {
            Node args("args");
            for (Exp* arg : a->args->lista_exp) args.add(makeExpr(arg));
            n.add(args);
        }
        return n;
    }
    if (auto c = dynamic_cast<CompositeLitExp*>(e)) {
        Node n("CompositeLit: " + tipoToStr(c->tipo));
        for (KeyedElement* k : c->elementos) {
            if (!k) continue;
            string key = k->key ? exprToStr(k->key) + ": " : "";
            Node el(key + exprToStr(k->value));
            n.add(el);
        }
        return n;
    }
    if (auto sl = dynamic_cast<SliceExp*>(e)) {
        Node n("Slice");
        n.add(makeExpr(sl->expresion));
        if (sl->low)  n.add("low: "  + exprToStr(sl->low));
        if (sl->high) n.add("high: " + exprToStr(sl->high));
        if (sl->max)  n.add("max: "  + exprToStr(sl->max));
        return n;
    }
    if (auto ta = dynamic_cast<TypeAssertionExp*>(e)) {
        Node n("TypeAssertion (." + tipoToStr(ta->tipo) + ")");
        n.add(makeExpr(ta->expresion));
        return n;
    }
    return Node("Exp");
}

Node makeExpList(ExpList* el, const string& label) {
    Node n(label);
    if (el) for (Exp* e : el->lista_exp) n.add(makeExpr(e));
    return n;
}

Node makeStmt(Stmt* s) {
    if (!s) return Node("<null-stmt>");

    if (auto d = dynamic_cast<DeclarationStmt*>(s)) {
        Node n("DeclStmt");
        // Reutiliza la impresion de declaraciones de nivel superior:
        Declaration* decl = d->declaration;
        if (auto vd = dynamic_cast<VarDecl*>(decl)) {
            n.label = "VarDecl";
            for (VarSpec* vs : vd->varspecList) {
                if (!vs) continue;
                Node v("var " + identListToStr(vs->identifierlist) +
                       (vs->tipo ? " " + tipoToStr(vs->tipo) : ""));
                if (vs->expresionlist) v.add(makeExpList(vs->expresionlist, "= valores"));
                n.add(v);
            }
        } else if (auto cd = dynamic_cast<ConstDecl*>(decl)) {
            n.label = "ConstDecl";
            for (ConstSpec* cs : cd->constspecList) {
                if (!cs) continue;
                Node v("const " + identListToStr(cs->identifierList) +
                       (cs->tipo ? " " + tipoToStr(cs->tipo) : ""));
                if (cs->expresionlist) v.add(makeExpList(cs->expresionlist, "= valores"));
                n.add(v);
            }
        } else if (auto td = dynamic_cast<TypeDecl*>(decl)) {
            n.label = "TypeDecl";
            for (TypeSpec* ts : td->typespecList)
                if (ts) n.add(makeType(ts->tipo, "type " + ts->id));
        }
        return n;
    }
    if (auto b = dynamic_cast<BlockStmt*>(s))
        return makeBlock(b->block, "BlockStmt");
    if (auto e = dynamic_cast<ExpresionStmt*>(s)) {
        Node n("ExprStmt");
        n.add(makeExpr(e->expresion));
        return n;
    }
    if (auto id = dynamic_cast<IncDecStmt*>(s)) {
        Node n(string("IncDecStmt (") + Exp::unopToString(id->op) + ")");
        n.add(makeExpr(id->expresion));
        return n;
    }
    if (auto a = dynamic_cast<Assigment*>(s)) {
        static const char* ops[] = {"+=", "-=", "*=", "/=", "="};
        Node n(string("Assignment (") + ops[a->op] + ")");
        n.add(makeExpList(a->expresion_list_id, "izquierda"));
        n.add(makeExpList(a->expresion_list_values, "derecha"));
        return n;
    }
    if (auto r = dynamic_cast<ReturnStmt*>(s)) {
        Node n("ReturnStmt");
        if (r->expresion_list) n.add(makeExpList(r->expresion_list, "valores"));
        return n;
    }
    if (dynamic_cast<BreakStmt*>(s))    return Node("BreakStmt");
    if (dynamic_cast<ContinueStmt*>(s)) return Node("ContinueStmt");
    if (auto f = dynamic_cast<IfStmt*>(s)) {
        Node n("IfStmt");
        Node cond("condicion");
        cond.add(makeExpr(f->expresion));
        n.add(cond);
        n.add(makeBlock(f->cuerpo_if, "then"));
        if (f->if_anidado) { Node e("else-if"); e.add(makeStmt(f->if_anidado)); n.add(e); }
        else if (f->cuerpo_else) n.add(makeBlock(f->cuerpo_else, "else"));
        return n;
    }
    if (auto sw = dynamic_cast<SwitchStmt*>(s)) {
        Node n("SwitchStmt");
        if (sw->expresion) { Node c("expresion"); c.add(makeExpr(sw->expresion)); n.add(c); }
        for (ExpCaseClause* cc : sw->exp_case_clause) {
            if (!cc) continue;
            Node caseN(cc->expresion_list ? "case" : "default");
            if (cc->expresion_list) caseN.add(makeExpList(cc->expresion_list, "valores"));
            if (cc->statement_list) {
                Node body("cuerpo");
                for (Stmt* st : cc->statement_list->statements) body.add(makeStmt(st));
                caseN.add(body);
            }
            n.add(caseN);
        }
        return n;
    }
    if (auto fo = dynamic_cast<ForStmt*>(s)) {
        Node n("ForStmt");
        if (fo->for_clause) {
            ForClause* fc = fo->for_clause;
            Node clause("ForClause");
            if (fc->asignacion1) clause.add(makeStmt(fc->asignacion1)).label = "init";
            if (fc->expresion) { Node c("condicion"); c.add(makeExpr(fc->expresion)); clause.add(c); }
            if (fc->asignacion2) clause.add(makeStmt(fc->asignacion2)).label = "post";
            if (fc->inc_dec_stmt) clause.add(makeStmt(fc->inc_dec_stmt)).label = "post";
            n.add(clause);
        } else if (fo->expresion) {
            Node c("condicion");
            c.add(makeExpr(fo->expresion));
            n.add(c);
        } else {
            n.add("(bucle infinito)");
        }
        n.add(makeBlock(fo->block, "cuerpo"));
        return n;
    }
    return Node("Stmt");
}

Node makeBlock(Block* b, const string& label) {
    Node n(label);
    if (b && b->lista_statements)
        for (Stmt* s : b->lista_statements->statements)
            n.add(makeStmt(s));
    return n;
}

Node makeParams(ParameterList* pl) {
    Node n("Parametros");
    if (pl) for (ParameterDecl* pd : pl->parameterList)
        if (pd) n.add(identListToStr(pd->identifierlist) + " " + tipoToStr(pd->type));
    return n;
}

Node makeTopLevel(TopLevelDecl* d) {
    if (auto fn = dynamic_cast<FunctionDecl*>(d)) {
        Node n("FunctionDecl: " + fn->name);
        n.add(makeParams(fn->lista_de_parametros));
        if (fn->tipo) n.add("retorna: " + tipoToStr(fn->tipo));
        n.add(makeBlock(fn->cuerpo, "cuerpo"));
        return n;
    }
    if (auto m = dynamic_cast<MethodDecl*>(d)) {
        Node n("MethodDecl: " + m->NombreTipoBase + "." + m->nombreMethod);
        n.add("receptor: " + m->nombreId + " " + (m->puntero ? "*" : "") + m->NombreTipoBase);
        n.add(makeParams(m->lista_de_parametros));
        if (m->tipo) n.add("retorna: " + tipoToStr(m->tipo));
        n.add(makeBlock(m->cuerpo, "cuerpo"));
        return n;
    }
    if (auto vd = dynamic_cast<VarDecl*>(d)) {
        Node n("VarDecl");
        for (VarSpec* vs : vd->varspecList) {
            if (!vs) continue;
            Node v("var " + identListToStr(vs->identifierlist) +
                   (vs->tipo ? " " + tipoToStr(vs->tipo) : ""));
            if (vs->expresionlist) v.add(makeExpList(vs->expresionlist, "= valores"));
            n.add(v);
        }
        return n;
    }
    if (auto cd = dynamic_cast<ConstDecl*>(d)) {
        Node n("ConstDecl");
        for (ConstSpec* cs : cd->constspecList) {
            if (!cs) continue;
            Node v("const " + identListToStr(cs->identifierList) +
                   (cs->tipo ? " " + tipoToStr(cs->tipo) : ""));
            if (cs->expresionlist) v.add(makeExpList(cs->expresionlist, "= valores"));
            n.add(v);
        }
        return n;
    }
    if (auto td = dynamic_cast<TypeDecl*>(d)) {
        Node n("TypeDecl");
        for (TypeSpec* ts : td->typespecList)
            if (ts) n.add(makeType(ts->tipo, "type " + ts->id));
        return n;
    }
    return Node("TopLevelDecl");
}

} // namespace

void dumpAstJson(Programa* programa, std::ostream& out) {
    Node root("Programa");
    if (programa)
        for (TopLevelDecl* d : programa->listatopleveldecl)
            if (d) root.add(makeTopLevel(d));
    writeNode(out, root, 0);
    out << "\n";
}
