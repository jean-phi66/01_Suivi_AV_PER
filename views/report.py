import streamlit as st
from streamlit import session_state as ss

import plotly.io as pio

# Import du module de génération de rapport
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from report_generator import generate_rapport_pdf

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
        fig_evol_plot=fig_evol, 
        df_alloc_client_data=df_allocations_client
    ),
    file_name=f"{client} - {contrat} - Rapport Ameliore.pdf",
    mime="application/pdf",
    key="download_rapport_ameliore"
)
