"""
database.py
-----------
Camada de persistência do protótipo. Usa SQLite (arquivo local, sem
necessidade de servidor) para guardar o histórico de todas as sessões de
recarga simuladas — isto é o que permite "apresentar dados gerados pelo
sistema" de forma acumulada, e não apenas a última simulação rodada.

Cada linha da tabela `recargas` corresponde a uma sessão de recarga
completa, com todos os parâmetros de entrada e os resultados calculados
por simulation_core.py.
"""

import sqlite3
import pandas as pd
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "recargas.db"

# Nome e ordem das colunas da tabela — usado tanto na criação quanto nas
# consultas, para manter a tabela e o DataFrame sempre alinhados.
COLUMNS = [
    "id",
    "data_hora",
    "capacidade_kwh",
    "soc_inicial_pct",
    "soc_alvo_pct",
    "potencia_carregador_kw",
    "horario_inicio_h",
    "atraso_retirada_min",
    "tempo_carga_min",
    "energia_necessaria_kwh",
    "energia_rede_kwh",
    "energia_solar_kwh",
    "custo_energia_rs",
    "taxa_atraso_rs",
    "valor_total_rs",
]


def get_connection() -> sqlite3.Connection:
    """Abre (ou cria) o arquivo de banco de dados local."""
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """Cria a tabela de recargas caso ainda não exista. Seguro para chamar
    toda vez que a aplicação inicia (CREATE TABLE IF NOT EXISTS)."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recargas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_hora TEXT NOT NULL,
                capacidade_kwh REAL,
                soc_inicial_pct REAL,
                soc_alvo_pct REAL,
                potencia_carregador_kw REAL,
                horario_inicio_h REAL,
                atraso_retirada_min REAL,
                tempo_carga_min REAL,
                energia_necessaria_kwh REAL,
                energia_rede_kwh REAL,
                energia_solar_kwh REAL,
                custo_energia_rs REAL,
                taxa_atraso_rs REAL,
                valor_total_rs REAL
            )
            """
        )
        conn.commit()


def insert_session(record: dict) -> int:
    """
    Insere uma sessão de recarga concluída no banco.
    `record` deve conter as chaves de COLUMNS, exceto 'id' e 'data_hora'
    (preenchidos automaticamente). Retorna o id da linha inserida.
    """
    data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fields = COLUMNS[2:]  # todas menos id e data_hora
    values = [record[f] for f in fields]

    with get_connection() as conn:
        cursor = conn.execute(
            f"INSERT INTO recargas (data_hora, {', '.join(fields)}) "
            f"VALUES (?, {', '.join(['?'] * len(fields))})",
            [data_hora] + values,
        )
        conn.commit()
        return cursor.lastrowid


def fetch_all_sessions() -> pd.DataFrame:
    """Retorna todo o histórico de recargas como DataFrame, mais recente primeiro."""
    with get_connection() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM recargas ORDER BY id DESC", conn
        )
    return df


def clear_sessions() -> None:
    """Apaga todo o histórico (usado pelo botão 'Limpar histórico' na interface)."""
    with get_connection() as conn:
        conn.execute("DELETE FROM recargas")
        conn.commit()
