"""
simulation_core.py
-------------------
Núcleo de simulação do sistema inteligente de gerenciamento de recarga de
veículos elétricos (VE) para estacionamentos de prédios comerciais.

Este módulo é independente da interface (Streamlit) para poder ser testado
isoladamente e reaproveitado por outras camadas (ex.: um futuro backend
FastAPI que exponha os mesmos cálculos via API REST, alinhado ao conceito
de "Charging Station Management System" descrito no protocolo OCPP).

Princípios de energia e sustentabilidade embutidos na lógica:
1. Eficiência energética: perdas de conversão AC/DC do carregador (92%)
   são explicitamente contabilizadas, evitando subestimar o consumo real.
2. Tarifa Branca (ANEEL): o custo depende do horário de consumo, incentivando
   o deslocamento de carga para períodos fora de ponta.
3. Alinhamento com geração solar: o sistema pode atrasar o início da recarga
   para maximizar o uso da energia solar gerada localmente (autoconsumo),
   reduzindo a dependência da rede elétrica (grid) e a pegada de carbono.
4. Taxa de permanência (idle fee): desestimula o uso ocioso do ponto de
   recarga após a conclusão, aumentando o giro/eficiência da infraestrutura
   compartilhada (menos pontos físicos necessários = menos material e energia
   embutida na infraestrutura).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
import math

# ---------------------------------------------------------------------------
# 1. Parâmetros técnicos e regulatórios (valores ilustrativos para o protótipo)
# ---------------------------------------------------------------------------

CHARGER_EFFICIENCY = 0.92  # eficiência de conversão AC/DC do carregador (92%)

# Tarifa Branca simulada (R$/kWh) — três postos tarifários, valores
# ilustrativos baseados na estrutura real publicada pela ANEEL (ponta,
# intermediário e fora de ponta). Cada distribuidora tem valores próprios;
# aqui usamos números plausíveis para fins de prova de conceito acadêmica.
TARIFF_SCHEDULE = {
    "ponta": {"hours": range(18, 21), "price": 1.20},          # 18h-21h
    "intermediaria": {"hours": [17, 21], "price": 0.85},        # 17h-18h e 21h-22h
    "fora_ponta": {"hours": None, "price": 0.55},                # demais horas
}

LATE_FEE_GRACE_MINUTES = 5      # tolerância antes de cobrar taxa extra
LATE_FEE_PER_MINUTE = 2.00      # R$/min cobrado após a tolerância


def tariff_price(hour_float: float) -> float:
    """Retorna o preço da energia (R$/kWh) para uma hora do dia (0-24, fracionária)."""
    hour_int = int(hour_float) % 24
    if hour_int in TARIFF_SCHEDULE["ponta"]["hours"]:
        return TARIFF_SCHEDULE["ponta"]["price"]
    if hour_int in TARIFF_SCHEDULE["intermediaria"]["hours"]:
        return TARIFF_SCHEDULE["intermediaria"]["price"]
    return TARIFF_SCHEDULE["fora_ponta"]["price"]


def solar_generation_kw(hour_float: float, peak_kw: float = 30.0) -> float:
    """
    Modela a geração solar local do prédio como uma curva senoidal entre
    6h e 18h, com pico ao meio-dia — aproximação didática de uma curva de
    irradiância real, suficiente para demonstrar o conceito de autoconsumo.
    """
    h = hour_float % 24
    if h < 6 or h > 18:
        return 0.0
    # sin vai de 0 (6h) a 1 (12h) a 0 (18h)
    return peak_kw * math.sin(math.pi * (h - 6) / 12)


# ---------------------------------------------------------------------------
# 2. Cálculos fundamentais de energia e tempo de carga
# ---------------------------------------------------------------------------

def energy_needed_kwh(capacity_kwh: float, soc_initial: float, soc_target: float,
                       efficiency: float = CHARGER_EFFICIENCY) -> float:
    """
    Energia que deve ser retirada da rede/fonte para elevar o SOC da bateria
    de soc_initial para soc_target, já compensando as perdas de conversão
    do carregador (energia_da_rede = energia_util / eficiência).
    """
    if soc_target <= soc_initial:
        return 0.0
    energy_battery = capacity_kwh * (soc_target - soc_initial) / 100.0
    return energy_battery / efficiency


def charging_time_minutes(energy_kwh: float, charger_power_kw: float) -> float:
    """Tempo estimado de carga em minutos, dado o consumo de energia da rede."""
    if charger_power_kw <= 0:
        return float("inf")
    return (energy_kwh / charger_power_kw) * 60.0


# ---------------------------------------------------------------------------
# 3. Simulação minuto a minuto de uma sessão de recarga
# ---------------------------------------------------------------------------

@dataclass
class ChargingSessionResult:
    timeline: List[Dict]                 # série temporal minuto a minuto
    energy_needed_kwh: float
    charging_time_minutes: float
    total_energy_cost: float
    renewable_energy_kwh: float          # energia coberta por geração solar local
    grid_energy_kwh: float               # energia efetivamente puxada da rede
    late_fee: float
    total_amount_due: float
    removal_delay_minutes: float


def simulate_charging_session(
    capacity_kwh: float,
    soc_initial: float,
    soc_target: float,
    charger_power_kw: float,
    start_hour: float,
    removal_delay_minutes: float = 0.0,
    solar_peak_kw: float = 30.0,
    efficiency: float = CHARGER_EFFICIENCY,
) -> ChargingSessionResult:
    """
    Simula, minuto a minuto, uma sessão completa de recarga:
      1. Lê o SOC do veículo (simulado) e calcula o tempo até o SOC alvo;
      2. Avança o relógio minuto a minuto, atualizando SOC, custo acumulado
         e quanto dessa energia foi coberta pela geração solar local;
      3. Ao atingir o SOC alvo, "notifica" o usuário (marcado na timeline);
      4. Aplica a taxa de permanência (late fee) se o veículo não for
         removido dentro da tolerância de 5 minutos.
    """
    energy_total = energy_needed_kwh(capacity_kwh, soc_initial, soc_target, efficiency)
    total_minutes = charging_time_minutes(energy_total, charger_power_kw)

    timeline: List[Dict] = []
    soc = soc_initial
    cost_accum = 0.0
    renewable_kwh = 0.0
    grid_kwh = 0.0

    minute = 0
    # dt de 1 minuto -> fração de hora
    dt_hours = 1.0 / 60.0
    max_minutes = int(math.ceil(total_minutes)) if math.isfinite(total_minutes) else 0

    for minute in range(max_minutes + 1):
        current_hour = (start_hour + minute / 60.0) % 24
        # energia entregue neste minuto (limitada ao que falta para 100% do
        # tempo total, para o último passo fracionário)
        step_fraction = min(1.0, total_minutes - minute) if minute < total_minutes else 0.0
        energy_step_from_grid = charger_power_kw * dt_hours * max(step_fraction, 0.0)

        # quanto da geração solar local está disponível neste minuto e pode
        # ser usada para autoconsumo (limitado ao que o carregador está puxando)
        solar_kw = solar_generation_kw(current_hour, solar_peak_kw)
        solar_covering = min(solar_kw * dt_hours, energy_step_from_grid)
        grid_covering = energy_step_from_grid - solar_covering

        price = tariff_price(current_hour)
        cost_step = grid_covering * price  # autoconsumo solar direto não é tarifado
        cost_accum += cost_step
        renewable_kwh += solar_covering
        grid_kwh += grid_covering

        soc_gain = (energy_step_from_grid * efficiency / capacity_kwh) * 100.0
        soc = min(soc_target, soc + soc_gain)

        timeline.append({
            "minuto": minute,
            "hora_relogio": f"{int(current_hour):02d}:{int((current_hour % 1) * 60):02d}",
            "soc_percent": round(soc, 2),
            "potencia_kw": round(charger_power_kw * max(step_fraction, 0.0), 2),
            "tarifa_rs_kwh": price,
            "custo_acumulado_rs": round(cost_accum, 2),
            "energia_solar_kwh_acum": round(renewable_kwh, 4),
            "energia_rede_kwh_acum": round(grid_kwh, 4),
            "meta_atingida": soc >= soc_target,
        })

        if soc >= soc_target:
            break

    late_fee = 0.0
    if removal_delay_minutes > LATE_FEE_GRACE_MINUTES:
        late_fee = (removal_delay_minutes - LATE_FEE_GRACE_MINUTES) * LATE_FEE_PER_MINUTE

    return ChargingSessionResult(
        timeline=timeline,
        energy_needed_kwh=round(energy_total, 3),
        charging_time_minutes=round(total_minutes, 1),
        total_energy_cost=round(cost_accum, 2),
        renewable_energy_kwh=round(renewable_kwh, 3),
        grid_energy_kwh=round(grid_kwh, 3),
        late_fee=round(late_fee, 2),
        total_amount_due=round(cost_accum + late_fee, 2),
        removal_delay_minutes=removal_delay_minutes,
    )


# ---------------------------------------------------------------------------
# 4. Otimização: agendamento inteligente alinhado à geração solar
# ---------------------------------------------------------------------------

def find_best_smart_start(
    capacity_kwh: float,
    soc_initial: float,
    soc_target: float,
    charger_power_kw: float,
    earliest_start_hour: float,
    deadline_hour: float,
    solar_peak_kw: float = 30.0,
    efficiency: float = CHARGER_EFFICIENCY,
    step_minutes: int = 15,
) -> Tuple[float, ChargingSessionResult]:
    """
    Busca, entre earliest_start_hour e deadline_hour, o horário de início
    que minimiza o custo total da recarga (proxy de maximizar o uso de
    energia solar / horários fora de ponta), respeitando o prazo de entrega
    do veículo (deadline_hour).

    Estratégia: busca exaustiva em passos de `step_minutes` — abordagem
    simples e explicável, adequada para uma prova de conceito acadêmica
    (um sistema real usaria um otimizador mais sofisticado, ex. programação
    linear, mas o princípio de deslocamento de carga é o mesmo).
    """
    energy_total = energy_needed_kwh(capacity_kwh, soc_initial, soc_target, efficiency)
    duration_hours = charging_time_minutes(energy_total, charger_power_kw) / 60.0

    best_start = earliest_start_hour
    best_result = None
    best_cost = float("inf")

    candidate = earliest_start_hour
    latest_possible_start = deadline_hour - duration_hours

    if latest_possible_start < earliest_start_hour:
        # não há folga: precisa começar imediatamente
        result = simulate_charging_session(
            capacity_kwh, soc_initial, soc_target, charger_power_kw,
            earliest_start_hour, 0.0, solar_peak_kw, efficiency
        )
        return earliest_start_hour, result

    while candidate <= latest_possible_start + 1e-9:
        result = simulate_charging_session(
            capacity_kwh, soc_initial, soc_target, charger_power_kw,
            candidate, 0.0, solar_peak_kw, efficiency
        )
        if result.total_energy_cost < best_cost:
            best_cost = result.total_energy_cost
            best_start = candidate
            best_result = result
        candidate += step_minutes / 60.0

    return best_start, best_result
