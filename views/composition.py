from pathlib import Path

import streamlit as st
from streamlit import session_state as ss

import pandas as pd
import plotly.express as px

from analyse_SRI import generate_fig_SRI
from reporting_helpers import build_composition_figures

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
    
st.dataframe(df_allocations_client.drop(["Prestation", "Nom", "Prénom", "Civilité",
                                                      "Identifiant", "Numéro contrat", "SRRI", "Consultant", "Titulaire(s)",
                                                      "Date valeur", "Date d'import"], axis=1))


df_allocations_client_SRI, fig_distribution_SRI, fig_SRI_contrat = generate_fig_SRI(
    df_allocations_client)


st.plotly_chart(fig_SRI_contrat, use_container_width=True)
st.plotly_chart(fig_distribution_SRI, use_container_width=True)

ss['fig_supports'] = fig_supports
ss['fig_typologie'] = fig_typologie
ss['fig_typologie_simplifiee'] = fig_typologie_simplifiee
ss['fig_distribution_SRI'] = fig_distribution_SRI
ss['fig_SRI_contrat'] = fig_SRI_contrat
