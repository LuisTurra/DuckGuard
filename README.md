# DuckGuard V6.0 🦆🔍

[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Streamlit App](https://img.shields.io/badge/Streamlit-App-FF4B4B?logo=streamlit)](https://streamlit.io/)
[![DuckDB](https://img.shields.io/badge/DuckDB-1.0+-orange?logo=duckdb)](https://duckdb.org/)

Ferramenta interativa para analisar queries SQL no **DuckDB**.  
Diagnostica planos de execução, visualiza grafos, avalia saúde da query (score 0–100) e sugere otimizações.

### Funcionalidades

- Editor SQL + EXPLAIN JSON
- Diagrama do plano (Graphviz)
- Avaliação de saúde com alertas e sugestões
- Upload CSV/Parquet + TPC-H demo (sf=0.01)
- Histórico de análises
- Explicação de operadores DuckDB

### Instalação rápida

```bash
# Clone o projeto
git clone https://github.com/seu-usuario/duckguard.git
cd duckguard

# Ambiente virtual
python -m venv venv
source venv/bin/activate          # Linux/macOS
# ou: venv\Scripts\activate       # Windows

# Dependências
pip install -r requirements.txt

# Executar
streamlit run streamlit_app.py