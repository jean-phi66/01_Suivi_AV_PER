from pathlib import Path

import streamlit as st
from streamlit import session_state as ss

import pandas as pd
import plotly.express as px

from analyse_SRI import generate_fig_SRI
from reporting_helpers import build_composition_figures, prepare_portfolio_lines_table

st.title("Analyse de l'allocation")

BASE_DIR = Path(__file__).resolve().parents[1]
MAPPING_PATH = BASE_DIR / "defaults" / "typage_fonds_portefeuille.json"

df_allocations_client = ss['df_allocations_client']
df_contrat_selected = ss['df_contrat_selected']

st.write(df_contrat_selected['Titulaire(s)'].iloc[0], '-', 
         df_contrat_selected['Enveloppe'].iloc[0], '-',
         df_contrat_selected['Partenaire'].iloc[0], '-',
         df_contrat_selected['N° de contrat'].iloc[0])

# Analyse typologie
col_typologie, col_typologie_simplifiee = st.columns(2)

df_allocations_client, fig_typologie, fig_typologie_simplifiee, fig_supports = build_composition_figures(
    df_allocations_client,
    mapping_path=MAPPING_PATH,
)

with col_typologie:
    if fig_typologie is not None:
        st.plotly_chart(fig_typologie, use_container_width=False)

with col_typologie_simplifiee:
    if fig_typologie_simplifiee is not None:
        st.plotly_chart(fig_typologie_simplifiee, use_container_width=False)

# Analyse Supports
if fig_supports is not None:
    st.plotly_chart(fig_supports, use_container_width=False)
    
# Tableau des lignes du portefeuille groupé par type (simplifié)
st.subheader("Détail des lignes du portefeuille")

df_portfolio_lines, _, _, meta_lines = prepare_portfolio_lines_table(
    df_allocations_client,
    mapping_path=MAPPING_PATH,
)

if not df_portfolio_lines.empty:
    m1, m2, m3 = st.columns(3)
    m1.metric("Nombre de supports", f"{meta_lines.get('n_supports', len(df_portfolio_lines))}")
    m2.metric("Encours total", f"{meta_lines.get('total_encours', 0.0):,.2f} €".replace(",", " "))
    m3.metric(
        "Plus-value latente globale",
        f"{meta_lines.get('total_pct', 0.0):+.2f} %",
        help="Plus/moins-value latente non réalisée sur les fonds actuellement détenus (par rapport à leur prix de revient)",
    )

    def _highlight_portfolio_row(row):
        val = row.get("Évolution (%)", 0.0)
        if isinstance(val, (int, float)):
            if val > 0:
                return ["background-color: #F0F9F4; color: #1F2937;"] * len(row)
            elif val < 0:
                return ["background-color: #FDF4F4; color: #1F2937;"] * len(row)
        return [""] * len(row)

    def _color_evol_cell(val):
        if isinstance(val, (int, float)):
            if val > 0:
                return "background-color: #DCF2E4; color: #137333; font-weight: 600;"
            elif val < 0:
                return "background-color: #FDEDEC; color: #C5221F; font-weight: 600;"
        return ""

    styled_portfolio = (
        df_portfolio_lines.style
        .apply(_highlight_portfolio_row, axis=1)
        .map(_color_evol_cell, subset=["Évolution (%)"])
        .format({
            "Encours (€)": lambda x: f"{x:,.2f} €".replace(",", " ").replace(".", ","),
            "Évolution (%)": lambda x: f"{x:+.2f} %".replace(".", ","),
        })
    )

    st.dataframe(
        styled_portfolio,
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("Aucune ligne de portefeuille disponible pour ce contrat.")

with st.expander("Voir toutes les données détaillées d'allocation"):
    cols_to_drop = [
        col for col in ["Prestation", "Nom", "Prénom", "Civilité", "Identifiant",
                        "Numéro contrat", "SRRI", "Consultant", "Titulaire(s)",
                        "Date valeur", "Date d'import"]
        if col in df_allocations_client.columns
    ]
    st.dataframe(df_allocations_client.drop(cols_to_drop, axis=1) if cols_to_drop else df_allocations_client)


df_allocations_client_SRI, fig_distribution_SRI, fig_SRI_contrat = generate_fig_SRI(
    df_allocations_client)


st.plotly_chart(fig_SRI_contrat, use_container_width=True)
st.plotly_chart(fig_distribution_SRI, use_container_width=True)

ss['fig_supports'] = fig_supports
ss['fig_typologie'] = fig_typologie
ss['fig_typologie_simplifiee'] = fig_typologie_simplifiee
ss['fig_distribution_SRI'] = fig_distribution_SRI
ss['fig_SRI_contrat'] = fig_SRI_contrat
