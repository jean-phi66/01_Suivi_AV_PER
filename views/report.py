import streamlit as st
from streamlit import session_state as ss

import pandas as pd
import plotly.io as pio

# Import du module de génération de rapport
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from report_generator import generate_rapport_pdf
from reporting_helpers import build_evolution_figure, build_kpi_overrides, build_tri_figure, resolve_payment_source
from tri_integration import load_tri_analyses, match_tri_analyses_to_contracts

pio.templates.default = "none"

# Récupération des données depuis la session
df_contrats = ss['df_contrats']
df_allocations = ss['df_allocations']
client = ss['client']
contrat = ss['contrat']
df_contrat_selected = ss['df_contrat_selected']
df_allocations_client = ss['df_allocations_client']

# Récupération des figures depuis la session
fig_supports = ss['fig_supports']
fig_typologie = ss['fig_typologie']
fig_distribution_SRI = ss['fig_distribution_SRI']
fig_SRI_contrat = ss['fig_SRI_contrat']
fig_waterfall_contract = ss['fig_waterfall_contract'] 
fig_waterfall_allocation = ss['fig_waterfall_allocation']

fig_evol = ss.get('fig_evol')  # Récupérer fig_evol, .get() est plus sûr
fig_tri = ss.get('fig_tri')

preferred_source = st.radio(
    "Source des versements pour le rapport",
    options=["CSV contrats", "Releve d'operations TRI"],
    horizontal=True,
    help="Si le relevé TRI n'est pas disponible pour ce contrat, le rapport repasse automatiquement sur les valeurs CSV.",
)

tri_contracts_df, tri_contracts_map = match_tri_analyses_to_contracts(
    load_tri_analyses(),
    df_contrats[["N° de contrat", "Titulaire(s)", "Enveloppe", "Partenaire"]].drop_duplicates().copy(),
)
tri_analysis = tri_contracts_map.get(str(contrat))
source_context = resolve_payment_source(df_contrat_selected, tri_analysis, preferred_source)
kpi_overrides = build_kpi_overrides(df_contrat_selected, source_context)
is_per_contract = (
    not df_contrat_selected.empty
    and 'Enveloppe' in df_contrat_selected.columns
    and 'PER' in str(df_contrat_selected['Enveloppe'].iloc[0]).upper()
)

df_contrat_agg = ss.get('df_contrat_agg_filtered', ss.get('df_contrat_agg', pd.DataFrame()))
df_historical_for_contract = df_contrat_agg[df_contrat_agg['N° de contrat'] == contrat].copy() if not df_contrat_agg.empty else pd.DataFrame(columns=df_contrat_selected.columns)

fig_evol_report = build_evolution_figure(
    df_historical_for_contract,
    df_contrat_selected.copy(),
    contrat,
    tri_analysis,
    source_context,
    add_reduction_ir=is_per_contract,
    ir_num=0.30,
) or fig_evol
fig_tri_report = build_tri_figure(
    df_historical_for_contract,
    df_contrat_selected.copy(),
    contrat,
    tri_analysis,
) or fig_tri

# Bouton de téléchargement du rapport
st.download_button(
    label="Enregistrer rapport amélioré",
    data=generate_rapport_pdf(
        client_name=client, 
        contrat_num=contrat, 
        df_contrat_sel=df_contrat_selected,
        fig_typologie_plot=fig_typologie, 
        fig_supports_plot=fig_supports,
        fig_waterfall_contract_plot=fig_waterfall_contract, 
        fig_waterfall_allocation_plot=fig_waterfall_allocation,
        fig_distribution_SRI_plot=fig_distribution_SRI, 
        fig_SRI_contrat_plot=fig_SRI_contrat,
        fig_evol_plot=fig_evol_report, 
        df_alloc_client_data=df_allocations_client,
        fig_tri_plot=fig_tri_report,
        kpi_overrides=kpi_overrides,
    ),
    file_name=f"{client} - {contrat} - Rapport Ameliore.pdf",
    mime="application/pdf",
    key="download_rapport_ameliore"
)
