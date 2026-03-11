import streamlit as st
import duckdb
import pandas as pd
import json
import graphviz
import re
import time
from datetime import datetime

# =============================================================================
# CONFIGURAÇÃO INICIAL DO APLICATIVO
# =============================================================================
st.set_page_config(page_title="DuckGuard V6.0", page_icon="🔍", layout="wide")

# Conexão persistente com DuckDB em memória 
if "con" not in st.session_state:
    st.session_state.con = duckdb.connect(database=':memory:')
    # Instala e carrega extensões necessárias
    st.session_state.con.execute("INSTALL httpfs; LOAD httpfs; INSTALL tpch; LOAD tpch;")
con = st.session_state.con

# Histórico de análises
if "history" not in st.session_state:
    st.session_state.history = []

# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

def get_tables_list():
    """Retorna lista de tabelas criadas no schema 'main'"""
    return con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").df()

def get_query_health(plan_json, exec_time, actual_rows=None, query_text=""):
    """
    Calcula a 'saúde' da query de forma profissional e realista.
    
    Critérios principais:
    - Penaliza padrões que degradam em escala maior (mesmo que rode rápido na demo)
    - Dá bônus para boas práticas do DuckDB (filter pushdown, late materialization, LIMIT baixo)
    - Considera tempo real, operadores caros e heurísticas específicas do TPC-H
    
    Score final: 0–100
    Faixas:
      ≥ 90 → Excelente
      70–89 → Boa
      45–69 → Regular
      < 45 → Problemática
    """
    issues = []
    suggestions = []
    score = 100.0

    # Flags detectadas durante a travessia do plano
    ops = set()
    has_filter_pushdown = False
    has_late_materialization = False
    table_scanned = ""
    group_by_cols_wide = False
    join_large_tables = False

    def walk(node):
        nonlocal has_filter_pushdown, has_late_materialization, table_scanned
        nonlocal group_by_cols_wide, join_large_tables

        name = node.get("name", "").upper()
        ops.add(name)

        # Converte extra_info para string e lowercase de forma segura
        extra = str(node.get("extra_info", "")).lower()

        # Detecção de boas práticas
        if "filter" in extra and "pushdown" in extra:
            has_filter_pushdown = True
        if "late materialization" in extra or "late" in extra:
            has_late_materialization = True

        # Detecção de padrões problemáticos
        if name == "SEQ_SCAN" and "lineitem" in extra:
            table_scanned = "lineitem"

        if name in ["HASH_GROUP_BY", "GROUP_BY"] and any(word in extra for word in ["address", "phone", "comment", "name"]):
            group_by_cols_wide = True

        if name == "HASH_JOIN" and len(node.get("children", [])) == 2:
            node_str = str(node).lower()
            if "lineitem" in node_str and not has_filter_pushdown:
                join_large_tables = True

        for child in node.get("children", []):
            walk(child)

    # Percorre todo o plano JSON
    for p in plan_json:
        walk(p)

    # Penalizações - padrões que pioram em escala maior
    if "SEQ_SCAN" in ops:
        if has_filter_pushdown:
            score -= 8
        else:
            issues.append("Leitura sequencial (SEQ_SCAN) sem pushdown de filtro → alto custo em tabelas grandes")
            score -= 35
            suggestions.append("Adicione condições WHERE mais seletivas ou reorganize a query")

    if join_large_tables:
        issues.append("JOIN envolvendo tabela grande (ex: lineitem) sem filtro seletivo prévio")
        score -= 25
        suggestions.append("Aplique filtros fortes na tabela grande ANTES do JOIN")

    if "ORDER_BY" in ops:
        if actual_rows is not None and actual_rows > 500:
            issues.append("Ordenação global (ORDER BY) em resultado grande → custoso")
            score -= 28
            suggestions.append("Use LIMIT baixo ou remova ORDER BY se não for essencial")
        else:
            score -= 10

    if "HASH_GROUP_BY" in ops or "GROUP_BY" in ops:
        if group_by_cols_wide:
            issues.append("GROUP BY inclui colunas largas (ex: nome, endereço, telefone) → alto uso de memória")
            score -= 18
            suggestions.append("Agrupe preferencialmente por chaves numéricas ou curtas")

    if "HASH_JOIN" in ops and table_scanned == "lineitem":
        score -= 15
        if not has_late_materialization:
            score -= 10

    # Penalidades por tempo de execução 
    if exec_time > 1.5:
        issues.append(f"Tempo alto: {exec_time:.3f}s (pode piorar muito em escala maior)")
        score -= 35
    elif exec_time > 0.5:
        score -= 18
    elif exec_time > 0.15:
        score -= 8

    # Bônus para boas práticas
    if has_filter_pushdown:
        score += 5
    if has_late_materialization:
        score += 8
    if "LIMIT" in ops and actual_rows is not None and actual_rows < 100:
        score += 10

    # Finaliza score e classifica
    score = max(0, min(100, round(score)))

    if score >= 90:
        health = "Excelente"
    elif score >= 70:
        health = "Boa"
    elif score >= 45:
        health = "Regular"
    else:
        health = "Problemática"

    positive_notes = []
    if has_filter_pushdown:
        positive_notes.append("Ótimo: filtro foi empurrado cedo (pushdown)")
    if has_late_materialization:
        positive_notes.append("Ótimo: late materialization presente")

    return {
        "health": health,
        "score": score,
        "issues": issues[:5],
        "suggestions": suggestions[:4],
        "positive_notes": positive_notes
    }

def analyze_query(query):
    """Executa EXPLAIN + execução real e coleta métricas + saúde"""
    if not query.strip():
        return None, None, None, "Query vazia."

    try:
        # Obtém plano de execução em formato JSON (sem executar ainda)
        res = con.execute(f"EXPLAIN (FORMAT JSON) {query}").fetchone()
        plan_json = json.loads(res[1])  # índice 1 contém o JSON string

        # Executa a query de verdade para medir tempo e linhas reais
        start_time = time.time()
        result = con.execute(query)
        exec_time = time.time() - start_time
        actual_rows = result.row_count() if hasattr(result, 'row_count') else len(result.fetchdf())

        # Contagens simples de operadores
        raw_str = str(plan_json).upper()
        scans = raw_str.count("SCAN")
        joins = raw_str.count("JOIN")

        metrics = {
            "exec_time_s": round(exec_time, 4),
            "rows_returned": actual_rows,
            "scans": scans,
            "joins": joins,
            "operators": len(set(n.get("name","") for n in plan_json if n.get("name")))
        }

        # Calcula saúde
        health_info = get_query_health(plan_json, exec_time, actual_rows, query)

        return plan_json, metrics, health_info, None

    except Exception as e:
        return None, None, None, str(e)

def explain_operators(plan_json):
    """Extrai e explica os operadores encontrados no plano de execução"""
    ops = set()
    def walk(node):
        ops.add(node.get("name", ""))
        for child in node.get("children", []): walk(child)
    for p in plan_json: walk(p)

    definitions = {
        "SEQ_SCAN": "Leitura sequencial de toda a tabela (lento em tabelas grandes)",
        "PROJECTION": "Seleção de colunas e expressões simples",
        "HASH_GROUP_BY": "Agrupamento usando tabela hash na memória",
        "FILTER": "Aplicação de condições WHERE",
        "HASH_JOIN": "Junção usando hash (eficiente, mas consome memória)",
        "ORDER_BY": "Ordenação dos resultados (cara em CPU/memória)",
        "LIMIT": "Limita o número de linhas retornadas",
        "AGGREGATE": "Cálculo de agregações (SUM, COUNT, AVG...)"
    }
    return {op: definitions.get(op, "Operador interno.") for op in ops if op}

def build_graph(plan_json):
    """Constrói diagrama visual do plano de execução usando Graphviz"""
    dot = graphviz.Digraph(graph_attr={'rankdir': 'BT'},
                           node_attr={'shape': 'box', 'style': 'filled', 'fillcolor': 'lightblue'})

    def add_node(node, parent_id=None):
        node_id = str(id(node))
        label = node.get("name", "Unknown")
        extra = node.get("extra_info", "")
        if extra:
            label += f"\n{extra[:60]}..." if len(extra) > 60 else f"\n{extra}"
        card = node.get("cardinality")
        if card is not None:
            label += f"\nEst: {card:,}"
        dot.node(node_id, label)
        if parent_id:
            dot.edge(parent_id, node_id)
        for child in node.get("children", []):
            add_node(child, node_id)

    if plan_json:
        add_node(plan_json[0])
    return dot

# =============================================================================
# INTERFACE LATERAL (SIDEBAR)
# =============================================================================
with st.sidebar:
    st.title("🦆 DuckGuard V6.0")
    
    with st.expander("📥 Carregar Arquivos", expanded=True):
        files = st.file_uploader("CSV ou Parquet", accept_multiple_files=True)
        if files:
            for f in files:
                name = re.sub(r'[^a-z0-9_]', '_', f.name.split('.')[0].lower())
                if f.name.endswith('.parquet'):
                    con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM read_parquet('{f.name}')")
                else:
                    df = pd.read_csv(f)
                    con.register(name, df)
                    con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM {name}")
                st.success(f"Tabela '{name}' criada!")

    if st.button("📊 Gerar Dados TPC-H (Vendas)", use_container_width=True):
        con.execute("CALL dbgen(sf=0.01);")
        st.rerun()

    st.subheader("📋 Tabelas Ativas")
    st.dataframe(get_tables_list(), hide_index=True)
    
    if st.button("🗑️ Resetar Tudo", use_container_width=True):
        st.session_state.con = duckdb.connect(database=':memory:')
        st.session_state.history = []
        st.rerun()

# =============================================================================
# ABAS PRINCIPAL
# =============================================================================
tab_diag, tab_expl, tab_res, tab_hist, tab_saude = st.tabs(
    ["⚡ Diagnóstico", "📖 O que significa?", "▶️ Resultado", "📜 Histórico", "Como funciona a Saúde"]
)

# Aba Diagnóstico (principal)
with tab_diag:
    if "sql_code" not in st.session_state:
        st.session_state.sql_code = ""

    sql_input = st.text_area("Editor SQL:", value=st.session_state.sql_code, height=200, key="editor")

    c1, c2, _ = st.columns([1, 1, 3])
    with c1:
        if st.button("🔍 Analisar", type="primary", use_container_width=True):
            st.session_state.sql_code = sql_input
            plan, metrics, health, err = analyze_query(sql_input)
            if err:
                st.error(err)
            else:
                st.session_state.current_plan = plan
                st.session_state.current_metrics = metrics
                st.session_state.current_health = health
                
                # Registra no histórico
                st.session_state.history.append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "query": sql_input.strip()[:80] + "..." if len(sql_input.strip()) > 80 else sql_input.strip(),
                    "health": health["health"],
                    "score": health["score"],
                    "time_s": metrics["exec_time_s"],
                    "rows": metrics["rows_returned"]
                })
    with c2:
        if st.button("🗑️ Limpar Código", use_container_width=True):
            st.session_state.sql_code = ""
            for key in ["current_plan", "current_metrics", "current_health"]:
                st.session_state.pop(key, None)
            st.rerun()

    if "current_plan" in st.session_state:
        m = st.session_state.current_metrics
        h = st.session_state.current_health

        col1, col2, col3 = st.columns(3)
        col1.metric("Tempo Execução", f"{m['exec_time_s']:.4f} s")
        col2.metric("Linhas Retornadas", f"{m['rows_returned']:,}")
        col3.metric("Saúde da Query", h["health"], delta=f"Score: {h['score']}%")

        st.divider()

        st.subheader("Avaliação Profissional")
        
        if h["positive_notes"]:
            for note in h["positive_notes"]:
                st.success(note)

        if h["issues"]:
            for issue in h["issues"]:
                st.warning(issue)
        else:
            st.success("Nenhum problema grave identificado!")

        if h["suggestions"]:
            st.info("Sugestões de melhoria:\n" + "\n".join(f"• {s}" for s in h["suggestions"]))

        st.divider()
        st.graphviz_chart(build_graph(st.session_state.current_plan))

# Aba Explicação de Operadores
with tab_expl:
    if "current_plan" in st.session_state:
        st.subheader("Operadores encontrados na query:")
        explanations = explain_operators(st.session_state.current_plan)
        for op, desc in explanations.items():
            st.markdown(f"### {op}")
            st.write(desc)
    else:
        st.info("Analise uma query primeiro para ver os operadores.")

# Aba Resultado da Execução
with tab_res:
    if "sql_code" in st.session_state and st.session_state.sql_code.strip():
        if st.button("▶️ Executar e Ver Dados"):
            try:
                df = con.execute(st.session_state.sql_code).df()
                st.dataframe(df)
            except Exception as e:
                st.error(f"Erro ao executar: {e}")
    else:
        st.info("Digite uma query no editor para executar.")

# Aba Histórico
with tab_hist:
    if st.session_state.history:
        hist_df = pd.DataFrame(st.session_state.history)
        hist_df = hist_df.sort_values("timestamp", ascending=False)
        st.dataframe(hist_df, use_container_width=True, hide_index=True)
        
        st.markdown("**Legenda de Saúde**")
        st.markdown("- **Excelente**: ≥ 90%")
        st.markdown("- **Boa**: 70–89%")
        st.markdown("- **Regular**: 45–69%")
        st.markdown("- **Problemática**: < 45%")
    else:
        st.info("Nenhuma análise registrada ainda.")

# Nova aba: Como funciona a Saúde
with tab_saude:
    st.title("Como o DuckGuard calcula a Saúde da Query")
    st.markdown("""
    O cálculo de saúde é baseado em heurísticas reais de performance no DuckDB e em bancos analíticos columnares.

    ### Como o score é calculado (0–100)
    - Inicia em **100**
    - **Penaliza** padrões que degradam em escala maior:
      - SEQ_SCAN sem filtro pushdown (-35)
      - JOIN em tabela grande sem filtro prévio (-25)
      - ORDER BY em muitos registros (-28 se >500 linhas)
      - GROUP BY com colunas longas (endereço, telefone...) (-18)
      - Tempo de execução alto (>1.5s = -35, >0.5s = -18, >0.15s = -8)
    - **Bonifica** boas práticas:
      - Filter pushdown (+5)
      - Late materialization (+8)
      - LIMIT baixo (<100 linhas) (+10)

    ### Faixas de classificação
    - **Excelente** ≥ 90% → query muito eficiente, adequada para produção
    - **Boa** 70–89% → aceitável, mas pode melhorar em escala
    - **Regular** 45–69% → cuidado: pode ficar lenta com mais dados
    - **Problemática** < 45% → contém anti-patterns claros

    ### Dicas gerais para melhorar a saúde
    1. Sempre filtre tabelas grandes (ex: lineitem, orders) **antes** de fazer joins
    2. Use condições no WHERE que possam ser empurradas cedo (pushdown)
    3. Evite ORDER BY sem LIMIT em consultas exploratórias
    4. Agrupe apenas por colunas curtas/numéricas quando possível
    5. Teste com LIMIT para validar lógica antes de rodar sem limite
    6. Prefira datas em formato DATE 'YYYY-MM-DD' (mais eficiente)

    O objetivo é alertar sobre riscos que aparecem em produção (sf=1, sf=10+), mesmo que na demonstração (sf=0.01) a query rode rápido.
    """)