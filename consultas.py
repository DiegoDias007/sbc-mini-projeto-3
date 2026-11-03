"""Consultas sobre a base de conhecimento de Hunter x Hunter (hxh.ttl).

Fluxo:
  1. Carrega os fatos declarados em hxh.ttl (a "base").
  2. Roda um raciocinador OWL 2 RL (owlrl) para deduzir os fatos implícitos
     (inversas, simetria, transitividade, classes definidas, domínios).
  3. Executa as consultas com g.triples() e com SPARQL sobre o grafo inferido.
  4. Aplica atualizações SPARQL na base, raciocina de novo e mostra o efeito.

O arquivo hxh.ttl nunca é alterado: as atualizações acontecem só em memória.
"""

from pathlib import Path

import owlrl
from rdflib import RDF, RDFS, BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL

HXH = Namespace("http://example.org/hxh#")
ARQUIVO_BASE = Path(__file__).parent / "hxh.ttl"
PREFIXOS = {"hxh": HXH, "rdf": RDF, "rdfs": RDFS, "owl": OWL}


# ---------------------------------------------------------------------------
# Carga e raciocínio
# ---------------------------------------------------------------------------

def carregar_base() -> Graph:
    base = Graph()
    base.parse(ARQUIVO_BASE, format="turtle")
    for prefixo, ns in PREFIXOS.items():
        base.bind(prefixo, ns)
    return base


def do_dominio(termo) -> bool:
    return isinstance(termo, URIRef) and termo.startswith(str(HXH))


def contradicoes(base: Graph) -> list[str]:
    """Roda o raciocinador e devolve as contradições lógicas que ele encontrou.

    O owlrl não lança exceção quando a base é inconsistente: ele registra cada
    problema como uma tripla com o predicado "error" e uma mensagem em texto.
    """
    fechamento = Graph()
    fechamento += base
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(fechamento)
    return sorted(str(o) for _, p, o in fechamento if p.endswith("#error"))


def raciocinar(base: Graph) -> Graph:
    """Devolve a base acrescida dos fatos que o raciocinador OWL deduz.

    O owlrl também gera centenas de triplas genéricas da própria linguagem
    (ex.: "owl:Thing é uma classe"). Ficamos só com as deduções sobre o
    domínio: triplas cujo sujeito é do domínio e cujo predicado é do domínio,
    ou que dizem a qual classe do domínio um indivíduo pertence.
    """
    fechamento = Graph()
    fechamento += base
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(fechamento)

    inferido = Graph()
    for prefixo, ns in PREFIXOS.items():
        inferido.bind(prefixo, ns)
    inferido += base
    for s, p, o in fechamento:
        if not do_dominio(s):
            continue
        if do_dominio(p) or (p == RDF.type and do_dominio(o)):
            inferido.add((s, p, o))
    return inferido


# ---------------------------------------------------------------------------
# Impressão
# ---------------------------------------------------------------------------

def rotulo(g: Graph, termo) -> str:
    """Nome legível de um termo: o rdfs:label, ou o nome local do IRI."""
    if isinstance(termo, Literal):
        return str(termo)
    label = g.value(termo, RDFS.label)
    if label is not None:
        return str(label)
    if do_dominio(termo):
        return "hxh:" + termo.removeprefix(str(HXH))
    return g.namespace_manager.normalizeUri(termo)


def titulo_secao(texto: str) -> None:
    print("\n" + "=" * 78)
    print(texto)
    print("=" * 78)


def titulo_consulta(codigo: str, proposito: str) -> None:
    print(f"\n--- {codigo}: {proposito}")


def tabela(cabecalhos: list[str], linhas: list[list[str]]) -> None:
    if not linhas:
        print("    (nenhum resultado)")
        return
    larguras = [
        max(len(cabecalhos[i]), *(len(linha[i]) for linha in linhas))
        for i in range(len(cabecalhos))
    ]
    def fmt(celulas):
        return "    " + "  ".join(c.ljust(w) for c, w in zip(celulas, larguras)).rstrip()
    print(fmt(cabecalhos))
    print(fmt(["-" * w for w in larguras]))
    for linha in linhas:
        print(fmt(linha))


def triplas_legiveis(g: Graph, padrao) -> None:
    """Imprime as triplas que casam com um padrão de g.triples(), ordenadas.

    Nós anônimos (blank nodes) são omitidos: são estruturas internas do OWL,
    como a lista de seis tipos do owl:oneOf, e não têm nome para mostrar.
    """
    linhas = sorted(
        [rotulo(g, s), rotulo(g, p), rotulo(g, o)]
        for s, p, o in g.triples(padrao)
        if not isinstance(s, BNode)
    )
    tabela(["sujeito", "predicado", "objeto"], linhas)


def select(g: Graph, consulta: str) -> None:
    resultado = g.query(consulta, initNs=PREFIXOS)
    cabecalhos = [str(v) for v in resultado.vars]
    linhas = [[rotulo(g, valor) if valor is not None else "-" for valor in linha]
              for linha in resultado]
    tabela(cabecalhos, linhas)


def ask(g: Graph, consulta: str) -> bool:
    return bool(g.query(consulta, initNs=PREFIXOS).askAnswer)


# ---------------------------------------------------------------------------
# Estatísticas da base
# ---------------------------------------------------------------------------

def estatisticas(base: Graph, g: Graph) -> None:
    titulo_secao("A BASE DE CONHECIMENTO")

    def contar(tipo) -> int:
        return sum(1 for s in base.subjects(RDF.type, tipo) if do_dominio(s))

    classes = {s for s in base.subjects(RDF.type, OWL.Class) if do_dominio(s)}
    individuos = {
        s for s, o in base.subject_objects(RDF.type) if o in classes and do_dominio(s)
    }
    construcoes_owl = [
        ("owl:FunctionalProperty", contar(OWL.FunctionalProperty)),
        ("owl:inverseOf", len(list(base.triples((None, OWL.inverseOf, None))))),
        ("owl:SymmetricProperty", contar(OWL.SymmetricProperty)),
        ("owl:TransitiveProperty", contar(OWL.TransitiveProperty)),
        ("owl:IrreflexiveProperty", contar(OWL.IrreflexiveProperty)),
        ("owl:disjointWith", len(list(base.triples((None, OWL.disjointWith, None))))),
        ("owl:oneOf", len(list(base.triples((None, OWL.oneOf, None))))),
        ("owl:equivalentClass", len(list(base.triples((None, OWL.equivalentClass, None))))),
    ]

    tabela(["item", "quantidade"], [
        ["triplas declaradas no hxh.ttl", str(len(base))],
        ["triplas deduzidas pelo raciocinador", str(len(g) - len(base))],
        ["contradições lógicas encontradas", str(len(contradicoes(base)))],
        ["classes", str(len(classes))],
        ["propriedades de objeto", str(contar(OWL.ObjectProperty))],
        ["propriedades de dados", str(contar(OWL.DatatypeProperty))],
        ["indivíduos", str(len(individuos))],
    ])
    print()
    tabela(["construção OWL", "usos"], [[n, str(q)] for n, q in construcoes_owl])


# ---------------------------------------------------------------------------
# Parte 1: consultas com g.triples()
# ---------------------------------------------------------------------------

def parte1_triples(g: Graph) -> None:
    titulo_secao("PARTE 1 - CONSULTAS COM g.triples()")

    # T1. Sujeito fixo: (Gon, None, None)
    # Busca tudo o que se sabe sobre o Gon.
    # Esperado: além dos fatos declarados (idade, licença, tipo de Nen,
    # habilidade, arcos), aparecem fatos DEDUZIDOS: que ele é Hunter (tem
    # licença), Personagem (todo Humano é), e discípulo de Wing e Biscuit
    # (inverso de "mestre de").
    titulo_consulta("T1", "Tudo o que a base sabe sobre o Gon (sujeito fixo)")
    triplas_legiveis(g, (HXH.Gon, None, None))

    # T2. Predicado fixo: (None, mestreDe, None)
    # Busca todas as relações de mestre e discípulo.
    # Esperado: 8 pares. Biscuit ensinou Wing, Gon e Killua; Wing ensinou Gon,
    # Killua e Zushi; Ging ensinou Kite; Izunavi ensinou Kurapika.
    titulo_consulta("T2", "Todas as relações de mestre e discípulo (predicado fixo)")
    triplas_legiveis(g, (None, HXH.mestreDe, None))

    # T3. Objeto fixo: (None, None, Intensificacao)
    # Busca tudo o que aponta para o tipo Intensificação, seja qual for a relação.
    # Esperado: os usuários desse tipo (Gon, Wing, Nobunaga, Uvogin), as
    # habilidades dessa categoria (Jajanken, Big Bang Impact) e os dois tipos
    # vizinhos no hexágono (Transformação e Emissão).
    titulo_consulta("T3", "Tudo o que se liga à Intensificação (objeto fixo)")
    triplas_legiveis(g, (None, None, HXH.Intensificacao))

    # T4. Sujeito e predicado fixos: (Kurapika, possuiHabilidade, None)
    # Busca as habilidades de um personagem específico.
    # Esperado: Corrente da Prisão e Emperor Time.
    titulo_consulta("T4", "Habilidades do Kurapika (sujeito + predicado fixos)")
    triplas_legiveis(g, (HXH.Kurapika, HXH.possuiHabilidade, None))

    # T5. Predicado e objeto fixos: (None, rdf:type, Hunter)
    # Busca quem é Hunter. Nenhum personagem foi declarado Hunter no .ttl:
    # todos são deduzidos pelo raciocinador, por terem licença ou estrelas.
    # Esperado: Gon, Kurapika, Leorio, Netero, Biscuit, Ging, Kite, Izunavi,
    # Cheadle, Pariston, Illumi e Hisoka. Killua NÃO aparece (sem licença).
    titulo_consulta("T5", "Quem é Hunter (predicado + objeto fixos)")
    triplas_legiveis(g, (None, RDF.type, HXH.Hunter))

    # T6. Sujeito e objeto fixos: (MontanhaKukuroo, None, Padokea)
    # Busca como dois recursos se relacionam, sem saber o predicado.
    # Esperado: "localizado em". O .ttl só diz Kukuroo -> Dentora -> Padokea;
    # a ligação direta vem da transitividade de hxh:localizadoEm.
    titulo_consulta("T6", "Como a Montanha Kukuroo se liga a Padokea (sujeito + objeto fixos)")
    triplas_legiveis(g, (HXH.MontanhaKukuroo, None, HXH.Padokea))


# ---------------------------------------------------------------------------
# Parte 2: consultas SPARQL
# ---------------------------------------------------------------------------

Q_MEMBROS_TRUPE = """
    SELECT ?numero ?membro ?tipo WHERE {
        hxh:TrupeFantasma hxh:temMembro ?p .
        ?p rdfs:label ?membro ;
           hxh:numeroNaTrupe ?numero .
        OPTIONAL { ?p hxh:tipoNenNatural/rdfs:label ?tipo }
    }
    ORDER BY ?numero
"""

Q_ALGUM_HUNTER_NA_TRUPE = """
    ASK {
        ?p hxh:membroDe hxh:TrupeFantasma ;
           a hxh:Hunter .
    }
"""

Q_KILLUA_E_HUNTER = "ASK { hxh:Killua a hxh:Hunter }"

Q_ZODIACOS = """
    SELECT ?membro WHERE {
        hxh:Zodiacos hxh:temMembro/rdfs:label ?membro .
    }
    ORDER BY ?membro
"""


def parte2_sparql(g: Graph) -> None:
    titulo_secao("PARTE 2 - CONSULTAS SPARQL")

    # S1. SELECT com FILTER
    # O hexágono de Nen diz que é mais fácil aprender o próprio tipo e os dois
    # vizinhos. Quem tem tipo igual ou vizinho ao do Gon seria um bom mestre ou
    # parceiro de treino para ele.
    # A adjacência só foi declarada numa direção; a simetria completa o resto.
    titulo_consulta("S1", "Personagens com tipo de Nen igual ou vizinho ao do Gon (FILTER)")
    select(g, """
        SELECT ?personagem ?tipo ?relacao WHERE {
            hxh:Gon hxh:tipoNenNatural ?tipoGon .
            ?p hxh:tipoNenNatural ?t ;
               rdfs:label ?personagem .
            ?t rdfs:label ?tipo .
            FILTER (?p != hxh:Gon)
            FILTER (?t = ?tipoGon || EXISTS { ?tipoGon hxh:adjacenteA ?t })
            BIND (IF(?t = ?tipoGon, "mesmo tipo", "tipo vizinho") AS ?relacao)
        }
        ORDER BY ?relacao ?tipo ?personagem
    """)

    # S2. SELECT com agregação (COUNT + GROUP BY) e ORDER BY
    # Quantos usuários conhecidos tem cada tipo de Nen. O OPTIONAL garante que
    # um tipo sem usuários conhecidos apareça com zero.
    titulo_consulta("S2", "Quantos usuários conhecidos tem cada tipo de Nen (agregação)")
    select(g, """
        SELECT ?tipo (COUNT(?p) AS ?usuarios) WHERE {
            ?t a hxh:TipoDeNen ;
               rdfs:label ?tipo .
            OPTIONAL { ?p hxh:tipoNenNatural ?t }
        }
        GROUP BY ?tipo
        ORDER BY DESC(?usuarios) ?tipo
    """)

    # S3. SELECT com ORDER BY
    # Membros da Trupe Fantasma em ordem de número da aranha. A base só diz
    # "X é membro da Trupe"; o "Trupe tem membro X" usado aqui vem do inverso.
    titulo_consulta("S3", "Membros da Trupe Fantasma pelo número da aranha (ORDER BY)")
    select(g, Q_MEMBROS_TRUPE)

    # S4. SELECT com caminho de propriedade (mestreDe+)
    # "Mestre de" não é transitiva: Biscuit ensinou Wing, Wing ensinou Zushi,
    # mas Biscuit nunca treinou Zushi. Mesmo assim é útil ver a LINHAGEM
    # completa, e isso o SPARQL resolve com o operador "+" (um ou mais passos)
    # sem precisar declarar uma transitividade falsa na ontologia.
    titulo_consulta("S4", "Linhagem de discípulos da Biscuit: diretos e indiretos (caminho +)")
    select(g, """
        SELECT ?discipulo ?forma WHERE {
            hxh:Biscuit hxh:mestreDe+ ?d .
            ?d rdfs:label ?discipulo .
            BIND (IF(EXISTS { hxh:Biscuit hxh:mestreDe ?d }, "direto", "indireto") AS ?forma)
        }
        ORDER BY ?forma ?discipulo
    """)

    # S5. SELECT que depende da transitividade de localizadoEm
    # Quem nasceu em Padokea? Ninguém tem "nasceuEm Padokea" declarado: os
    # Zoldyck nasceram na Montanha Kukuroo, que fica em Dentora, que fica em
    # Padokea.
    titulo_consulta("S5", "Personagens nascidos em qualquer lugar de Padokea (transitividade)")
    select(g, """
        SELECT ?personagem ?localDeNascimento WHERE {
            ?p hxh:nasceuEm ?l ;
               rdfs:label ?personagem .
            ?l rdfs:label ?localDeNascimento .
            FILTER (?l = hxh:Padokea || EXISTS { ?l hxh:localizadoEm hxh:Padokea })
        }
        ORDER BY ?personagem
    """)

    # S6. SELECT com expressão calculada, agregação e ORDER BY
    # Arcos do anime do mais longo para o mais curto, com quantos personagens
    # da base aparecem em cada um.
    titulo_consulta("S6", "Arcos do mais longo ao mais curto, com elenco da base (agregação)")
    select(g, """
        SELECT ?arco ?episodios (COUNT(?p) AS ?personagens) WHERE {
            ?a a hxh:Arco ;
               rdfs:label ?arco ;
               hxh:episodioInicial ?ini ;
               hxh:episodioFinal ?fim .
            OPTIONAL { ?p hxh:apareceEm ?a }
            BIND (?fim - ?ini + 1 AS ?episodios)
        }
        GROUP BY ?arco ?episodios
        ORDER BY DESC(?episodios)
    """)

    # A1. ASK
    # Gon e Killua são a dupla central da história. Os tipos deles são
    # vizinhos no hexágono (Intensificação e Transformação)?
    # Esperado: True.
    titulo_consulta("A1", "Os tipos de Nen de Gon e Killua são vizinhos no hexágono? (ASK)")
    resposta = ask(g, """
        ASK {
            hxh:Gon    hxh:tipoNenNatural ?a .
            hxh:Killua hxh:tipoNenNatural ?b .
            ?a hxh:adjacenteA ?b .
        }
    """)
    print(f"    Resposta: {resposta}")

    # A2. ASK
    # A Trupe Fantasma é um grupo de ladrões procurados. Mesmo assim, algum
    # membro tem licença Hunter? Esperado: True (Hisoka). Essa mesma pergunta
    # é refeita depois do DELETE (U1).
    titulo_consulta("A2", "Algum membro da Trupe Fantasma é Hunter? (ASK)")
    print(f"    Resposta: {ask(g, Q_ALGUM_HUNTER_NA_TRUPE)}")

    # C1. CONSTRUCT
    # Gera um grafo NOVO, que não existe na base: para cada protagonista, os
    # tipos de Nen que ele aprende com facilidade (o próprio e os vizinhos).
    titulo_consulta("C1", "Grafo de afinidade de Nen dos protagonistas (CONSTRUCT)")
    construido = g.query("""
        CONSTRUCT { ?p hxh:aprendeComFacilidade ?t }
        WHERE {
            VALUES ?p { hxh:Gon hxh:Killua hxh:Kurapika hxh:Leorio }
            ?p hxh:tipoNenNatural ?natural .
            { BIND (?natural AS ?t) }
            UNION
            { ?natural hxh:adjacenteA ?t }
        }
    """, initNs=PREFIXOS).graph
    construido.bind("hxh", HXH)
    print(f"    {len(construido)} triplas geradas:")
    for s, p, o in sorted(construido):
        print(f"    {rotulo(g, s):20} aprendeComFacilidade  {rotulo(g, o)}")


# ---------------------------------------------------------------------------
# Parte 2 (continuação): atualizações SPARQL
# ---------------------------------------------------------------------------

def parte2_updates(base: Graph) -> None:
    titulo_secao("PARTE 2 - ATUALIZAÇÕES SPARQL (a história avança)")
    print("As atualizações mudam a base em memória. Depois de cada uma, o")
    print("raciocinador roda de novo e as consultas mostram o antes e o depois.")

    # U1. DELETE DATA
    # No arco de Yorknew descobre-se que a aranha de Hisoka era falsa: ele
    # entrou na Trupe só para lutar com Chrollo. Removemos o vínculo.
    # Efeito esperado: a pergunta A2 passa de True para False, porque Hisoka
    # era o único Hunter da Trupe.
    titulo_consulta("U1", "Hisoka deixa a Trupe Fantasma (DELETE)")
    g = raciocinar(base)
    print(f"    Antes:  algum membro da Trupe é Hunter? {ask(g, Q_ALGUM_HUNTER_NA_TRUPE)}")
    base.update("""
        DELETE DATA {
            hxh:Hisoka hxh:membroDe hxh:TrupeFantasma ;
                       hxh:numeroNaTrupe 4 .
        }
    """, initNs=PREFIXOS)
    g = raciocinar(base)
    print(f"    Depois: algum membro da Trupe é Hunter? {ask(g, Q_ALGUM_HUNTER_NA_TRUPE)}")

    # U2. INSERT DATA
    # Kalluto Zoldyck assume a vaga número 4 deixada por Hisoka.
    # Efeito esperado: Kalluto aparece na lista da Trupe com o número 4.
    titulo_consulta("U2", "Kalluto entra na Trupe Fantasma como número 4 (INSERT)")
    print("    Antes:")
    select(g, Q_MEMBROS_TRUPE)
    base.update("""
        INSERT DATA {
            hxh:Kalluto hxh:membroDe hxh:TrupeFantasma ;
                        hxh:numeroNaTrupe 4 .
        }
    """, initNs=PREFIXOS)
    g = raciocinar(base)
    print("    Depois:")
    select(g, Q_MEMBROS_TRUPE)

    # U3. DELETE/INSERT
    # Killua foi desclassificado no primeiro Exame Hunter, mas passou no do ano
    # seguinte. "possuiLicenca" é funcional (uma pessoa tem um único valor),
    # então o "false" precisa ser trocado por "true", não só acompanhado
    # dele. Nenhuma tripla diz "Killua é Hunter": a
    # classificação vem da definição de Hunter (humano com licença).
    # Efeito esperado: "Killua é Hunter?" passa de False para True.
    titulo_consulta("U3", "Killua passa no Exame Hunter seguinte (DELETE/INSERT)")
    print(f"    Antes:  Killua é Hunter? {ask(g, Q_KILLUA_E_HUNTER)}")
    base.update("""
        DELETE { ?k hxh:possuiLicenca false }
        INSERT { ?k hxh:possuiLicenca true }
        WHERE  { ?k rdfs:label "Killua Zoldyck"@pt ;
                    hxh:possuiLicenca false . }
    """, initNs=PREFIXOS)
    g = raciocinar(base)
    print(f"    Depois: Killua é Hunter? {ask(g, Q_KILLUA_E_HUNTER)}")

    # U4. DELETE/INSERT com padrão genérico
    # No arco da Eleição, Ging renuncia ao posto de Javali nos Zodíacos e
    # Leorio assume o lugar. O WHERE localiza quem sai pelo padrão, sem
    # depender de valores fixos no DELETE.
    # Efeito esperado: Ging some da lista dos Zodíacos e Leorio aparece.
    titulo_consulta("U4", "Leorio substitui Ging nos Zodíacos (DELETE/INSERT)")
    print("    Antes:")
    select(g, Q_ZODIACOS)
    base.update("""
        DELETE { ?saindo hxh:membroDe hxh:Zodiacos }
        INSERT { hxh:Leorio hxh:membroDe hxh:Zodiacos }
        WHERE  { ?saindo rdfs:label "Ging Freecss"@pt ;
                         hxh:membroDe hxh:Zodiacos . }
    """, initNs=PREFIXOS)
    g = raciocinar(base)
    print("    Depois:")
    select(g, Q_ZODIACOS)


# ---------------------------------------------------------------------------
# Bônus: o raciocinador recusa fatos que contradizem a ontologia
# ---------------------------------------------------------------------------

def bonus_consistencia() -> None:
    titulo_secao("BÔNUS - O RACIOCINADOR DETECTA CONTRADIÇÕES")

    # B1. Humano e Formiga Quimera são classes disjuntas (owl:disjointWith).
    # Se alguém inserir por engano que o Rei Meruem é humano, a base fica
    # contraditória e o raciocinador aponta exatamente onde.
    titulo_consulta("B1", "Inserindo por engano que Meruem é humano")
    base = carregar_base()
    base.update("INSERT DATA { hxh:Meruem a hxh:Humano }", initNs=PREFIXOS)
    for mensagem in contradicoes(base):
        print(f"    Contradição: {mensagem.replace(str(HXH), 'hxh:')}")


# ---------------------------------------------------------------------------

def main() -> None:
    base = carregar_base()
    g = raciocinar(base)

    estatisticas(base, g)
    parte1_triples(g)
    parte2_sparql(g)
    parte2_updates(base)
    bonus_consistencia()
    print()


if __name__ == "__main__":
    main()
