import streamlit as st
from streamlit import session_state as ss

import pandas as pd

df_contrats = ss.get('df_contrats', pd.DataFrame())
df_allocations = ss.get('df_allocations', pd.DataFrame())

required_contrats_cols = {'Titulaire(s)', 'N° de contrat', 'Enveloppe', 'Partenaire', 'Valorisation'}
required_alloc_cols = {'Numéro contrat'}

if (
    df_contrats.empty
    or df_allocations.empty
    or not required_contrats_cols.issubset(df_contrats.columns)
    or not required_alloc_cols.issubset(df_allocations.columns)
):
    st.warning("Aucune donnée contrats/allocations disponible.")
    st.info("Cliquez sur le bouton ci-dessous pour ouvrir l'onglet Données et charger automatiquement les exports.")
    if st.button("Ouvrir Données"):
        st.switch_page("views/data_ingestion.py")
    st.stop()

# Defaults in session_state
if 'client' not in ss:
    ss['client'] = None
if 'contrat' not in ss:
    ss['contrat'] = None
if 'df_contrat_selected' not in ss:
    ss['df_contrat_selected'] = pd.DataFrame()
if 'df_allocations_client' not in ss:
    ss['df_allocations_client'] = pd.DataFrame()

# Select client with persisted default
clients_options = df_contrats.sort_values(by="Titulaire(s)")['Titulaire(s)'].unique().tolist()
client_default = ss['client'] if ss['client'] in clients_options else (clients_options[0] if clients_options else None)
client_index = clients_options.index(client_default) if client_default in clients_options else 0
client = st.selectbox(
    'Sélectionner client',
    options=clients_options,
    index=client_index,
    key="client_select"
)
df_contrats_client = df_contrats[df_contrats['Titulaire(s)'] == client]

# Select contract of client
st.dataframe(df_contrats_client[[
                      'Titulaire(s)', 'N° de contrat', 'Enveloppe', 'Partenaire', 'Valorisation']])
st.divider()
contrats_options = df_contrats_client['N° de contrat'].unique().tolist()
contrat_default = ss['contrat'] if ss['contrat'] in contrats_options else (contrats_options[0] if contrats_options else None)
contrat_index = contrats_options.index(contrat_default) if contrat_default in contrats_options else 0
contrat = st.selectbox(
    'Sélectionner contrat',
    options=contrats_options,
    index=contrat_index,
    key="contrat_select"
)
df_allocations_client = df_allocations[df_allocations['Numéro contrat'] == contrat]


# IR reduction option
df_contrat_selected = df_contrats_client[df_contrats_client['N° de contrat'] == contrat]

st.dataframe(df_contrat_selected)

    

# Update session_state
ss['client'] = client
ss['contrat'] = contrat
ss['df_contrat_selected'] = df_contrat_selected
ss['df_allocations_client'] = df_allocations_client

