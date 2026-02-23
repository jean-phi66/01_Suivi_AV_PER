from pathlib import Path

import streamlit as st
from streamlit import session_state as ss

import pandas as pd
import plotly.express as px

from analyse_SRI import generate_fig_SRI
from typage_fonds_utils import load_typage_config, map_simplified_type

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

mapping_simplifie, support_rules = load_typage_config(MAPPING_PATH)
df_allocations_client = df_allocations_client.copy()


df_allocations_client['Type simplifié'] = df_allocations_client.apply(
    lambda row: map_simplified_type(row.get('Type'), row.get('Support'), mapping_simplifie, support_rules),
    axis=1
)

fig_typologie = px.pie(df_allocations_client,
                       values='Encours en €', names='Type', hole=.5)
fig_typologie.update_layout(
    title="Typologie des supports")
with col_typologie:
    st.plotly_chart(fig_typologie, use_container_width=False)

fig_typologie_simplifiee = px.pie(
    df_allocations_client,
    values='Encours en €',
    names='Type simplifié',
    hole=.5,
)
fig_typologie_simplifiee.update_layout(
    title="Typologie simplifiée des supports"
)
with col_typologie_simplifiee:
    st.plotly_chart(fig_typologie_simplifiee, use_container_width=False)

# Analyse Supports
fig_supports = px.pie(df_allocations_client,
                      values='Encours en €', names='Support', hole=.5)
fig_supports.update_layout(
    title="Répartition par support")
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
