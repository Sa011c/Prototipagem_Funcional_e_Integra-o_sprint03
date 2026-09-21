"""
app.py
------
Prototipo funcional (Sprint 1) do Sistema Inteligente de Gerenciamento de
Recarga de Veiculos Eletricos para predios comerciais.

Interface construida em Streamlit. Toda a logica de negocio/energia esta
isolada em simulation_core.py (ver docstring daquele modulo para os
principios tecnicos e de sustentabilidade aplicados).

Como executar:
    pip install -r requirements.txt
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

from simulation_core import (
    simulate_charging_session,
    find_best_smart_start,
    energy_needed_kwh,
    charging_time_minutes,
    solar_generation_kw,
    LATE_FEE_GRACE_MINUTES,
    LATE_FEE_PER_MINUTE,
    CHARGER_EFFICIENCY,
)
import database as db

db.init_db()  # garante que a tabela 'recargas' existe antes de qualquer consulta

st.set_page_config(page_title="EV Smart Charging — Prototipo", layout="wide")

st.title(" Sistema Inteligente de Gerenciamento de Recarga de VEs")
st.caption(
    "Prototipo de prova de conceito — Sprint 1 · Conecta-se (de forma simulada) ao "
    "ponto de recarga, le o SOC do veiculo, calcula o tempo ate a meta, notifica o "
    "usuario e cobra por energia + eventual taxa de permanencia."
)

# ---------------------------------------------------------------------------
# Barra lateral — parametros da sessao de recarga (simulando os dados que, em
# producao, viriam do carregador via protocolo OCPP e do app do usuario)
# ---------------------------------------------------------------------------
st.sidebar.header("Parametros da sessao")

capacity_kwh = st.sidebar.slider("Capacidade da bateria (kWh)", 20, 100, 60, step=5)
soc_initial = st.sidebar.slider("SOC inicial do veiculo (%)", 0, 95, 20, step=5)
soc_target = st.sidebar.slider("SOC desejado pelo usuario (%)", soc_initial + 5, 100, 80, step=5)
charger_power_kw = st.sidebar.select_slider(
    "Potencia do carregador (kW)", options=[7, 11, 22, 50], value=22
)
start_hour = st.sidebar.slider("Horario de inicio da recarga (h)", 0.0, 23.5, 19.0, step=0.5)
removal_delay = st.sidebar.slider(
    "Tempo ate o usuario retirar o veiculo apos a meta (min)", 0, 30, 2
)
solar_peak_kw = st.sidebar.slider(
    "Geracao solar de pico do predio ao meio-dia (kW)", 0, 60, 30, step=5
)

st.sidebar.markdown("---")
st.sidebar.caption(
    f"Eficiencia do carregador (AC/DC): **{int(CHARGER_EFFICIENCY*100)}%** · "
    f"Tolerancia antes da taxa de permanencia: **{LATE_FEE_GRACE_MINUTES} min** · "
    f"Taxa de atraso: **R$ {LATE_FEE_PER_MINUTE:.2f}/min**"
)

tab1, tab2 = st.tabs(["▶️ Simulacao da sessao", "Comparativo: imediato vs. inteligente"])

# ---------------------------------------------------------------------------
# ABA 1 — Simulacao de uma sessao de recarga (funcionalidade operacional)
# ---------------------------------------------------------------------------
with tab1:
    if st.button("Iniciar simulacao de recarga", type="primary"):
        result = simulate_charging_session(
            capacity_kwh, soc_initial, soc_target, charger_power_kw,
            start_hour, removal_delay, solar_peak_kw
        )

        st.success(
            f"Meta de {soc_target}% atingida em {result.charging_time_minutes:.1f} minutos "
            f"usuario notificado automaticamente."
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Energia consumida (rede)", f"{result.grid_energy_kwh:.2f} kWh")
        c2.metric("Energia solar aproveitada", f"{result.renewable_energy_kwh:.2f} kWh")
        c3.metric("Custo de energia", f"R$ {result.total_energy_cost:.2f}")
        c4.metric(
            "Taxa de permanencia",
            f"R$ {result.late_fee:.2f}",
            delta=("Atraso detectado" if result.late_fee > 0 else "Dentro do prazo"),
            delta_color="inverse" if result.late_fee > 0 else "normal",
        )

        st.markdown(f"###Valor total a pagar: **R$ {result.total_amount_due:.2f}**")
        if result.late_fee > 0:
            st.warning(
                f"O veiculo permaneceu conectado {removal_delay:.0f} min apos a meta ser "
                f"atingida — {removal_delay - LATE_FEE_GRACE_MINUTES:.0f} min alem da "
                f"tolerancia de {LATE_FEE_GRACE_MINUTES} min, gerando a taxa extra."
            )

        # --- Persiste esta sessao no banco de dados (historico) ---
        record = {
            "capacidade_kwh": capacity_kwh,
            "soc_inicial_pct": soc_initial,
            "soc_alvo_pct": soc_target,
            "potencia_carregador_kw": charger_power_kw,
            "horario_inicio_h": start_hour,
            "atraso_retirada_min": removal_delay,
            "tempo_carga_min": result.charging_time_minutes,
            "energia_necessaria_kwh": result.energy_needed_kwh,
            "energia_rede_kwh": result.grid_energy_kwh,
            "energia_solar_kwh": result.renewable_energy_kwh,
            "custo_energia_rs": result.total_energy_cost,
            "taxa_atraso_rs": result.late_fee,
            "valor_total_rs": result.total_amount_due,
        }
        db.insert_session(record)

        st.markdown("####Tabela-resumo desta recarga")
        resumo_df = pd.DataFrame([record])
        st.dataframe(resumo_df, use_container_width=True, hide_index=True)

        df = pd.DataFrame(result.timeline)

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))

        ax1.plot(df["minuto"], df["soc_percent"], color="#2E7D32")
        ax1.axhline(soc_target, color="gray", linestyle="--", linewidth=1)
        ax1.set_title("Evolução do SOC da bateria")
        ax1.set_xlabel("Minutos desde o inicio")
        ax1.set_ylabel("SOC (%)")

        ax2.plot(df["minuto"], df["custo_acumulado_rs"], color="#1565C0", label="Custo acumulado")
        ax2.set_title("Custo acumulado da recarga")
        ax2.set_xlabel("Minutos desde o inicio")
        ax2.set_ylabel("R$")

        st.pyplot(fig)

        with st.expander("Ver dados detalhados minuto a minuto (dados gerados pelo sistema)"):
            st.dataframe(df, use_container_width=True)
    else:
        st.info("Ajuste os parametros na barra lateral e clique em **Iniciar simulacao de recarga**.")

    # --- Historico persistente de todas as sessoes ja simuladas ---
    st.markdown("---")
    st.markdown("#### Historico de recargas (banco de dados)")
    historico_df = db.fetch_all_sessions()
    if historico_df.empty:
        st.caption("Nenhuma recarga simulada ainda. Rode uma simulacao acima para comecar o historico.")
    else:
        st.dataframe(historico_df, use_container_width=True, hide_index=True)
        col_a, col_b = st.columns([1, 4])
        with col_a:
            if st.button("Limpar historico"):
                db.clear_sessions()
                st.rerun()
        with col_b:
            st.caption(f"{len(historico_df)} sessso(oes) registrada(s) no banco de dados local (recargas.db).")

# ---------------------------------------------------------------------------
# ABA 2 — Comparativo imediato vs. agendamento inteligente (sustentabilidade)
# ---------------------------------------------------------------------------
with tab2:
    st.write(
        "Esta aba demonstra o nucleo de **eficiencia energetica e sustentabilidade** da "
        "solucao: o sistema pode atrasar o inicio da recarga (dentro de um prazo definido "
        "pelo usuario) para maximizar o aproveitamento da energia solar gerada no proprio "
        "predio e evitar o horario de ponta, sem comprometer o horario de saida do veiculo."
    )

    deadline_hour = st.slider(
        "Horario limite para o veiculo estar pronto (h)",
        float(start_hour) + 1, 23.5, min(23.5, start_hour + 6), step=0.5
    )

    if st.button("Comparar cenarios"):
        immediate = simulate_charging_session(
            capacity_kwh, soc_initial, soc_target, charger_power_kw,
            start_hour, 0.0, solar_peak_kw
        )
        best_start, smart = find_best_smart_start(
            capacity_kwh, soc_initial, soc_target, charger_power_kw,
            earliest_start_hour=start_hour, deadline_hour=deadline_hour,
            solar_peak_kw=solar_peak_kw,
        )

        colA, colB = st.columns(2)
        with colA:
            st.subheader("Recarga imediata")
            st.metric("Inicio", f"{start_hour:.1f} h")
            st.metric("Custo", f"R$ {immediate.total_energy_cost:.2f}")
            st.metric("Energia solar usada", f"{immediate.renewable_energy_kwh:.2f} kWh")
        with colB:
            st.subheader("Recarga inteligente (solar-aligned)")
            st.metric("Inicio otimizado", f"{best_start:.2f} h")
            st.metric("Custo", f"R$ {smart.total_energy_cost:.2f}")
            st.metric("Energia solar usada", f"{smart.renewable_energy_kwh:.2f} kWh")

        savings = immediate.total_energy_cost - smart.total_energy_cost
        renewable_gain = smart.renewable_energy_kwh - immediate.renewable_energy_kwh
        st.markdown(
            f"### Resultado: economia de **R$ {savings:.2f}** e **+{renewable_gain:.2f} kWh** "
            f"de energia solar aproveitada ao adiar o inicio da recarga."
        )

        hours = np.arange(0, 24, 0.25)
        solar_curve = [solar_generation_kw(h, solar_peak_kw) for h in hours]
        fig2, ax = plt.subplots(figsize=(10, 3.5))
        ax.plot(hours, solar_curve, color="#F9A825", label="Geração solar do prédio (kW)")
        ax.axvspan(start_hour, start_hour + immediate.charging_time_minutes / 60,
                   color="#EF5350", alpha=0.3, label="Janela: recarga imediata")
        ax.axvspan(best_start, best_start + smart.charging_time_minutes / 60,
                   color="#66BB6A", alpha=0.4, label="Janela: recarga inteligente")
        ax.set_xlabel("Hora do dia")
        ax.set_ylabel("kW")
        ax.set_title("Alinhamento da recarga com a curva de geracao solar do predio")
        ax.legend(loc="upper right", fontsize=8)
        st.pyplot(fig2)

st.markdown("---")
st.caption(
    "Prototipo simulado desenvolvido para fins academicos — arquitetura de referencia "
    "inspirada no protocolo OCPP (Open Charge Point Protocol). Ver README.md para "
    "detalhes de arquitetura, diagramas e justificativas tecnicas."
)
