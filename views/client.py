import streamlit as st
from streamlit import session_state as ss

import pandas as pd

df_contrats = ss['df_contrats']
df_allocations = ss['df_allocations']

# Select client
client = st.selectbox(
    'Sélectionner client',
    df_contrats.sort_values(by="Titulaire(s)")['Titulaire(s)'].unique()
)
df_contrats_client = df_contrats[df_contrats['Titulaire(s)'] == client]

# Select contract of client
st.dataframe(df_contrats_client[[
                      'Titulaire(s)', 'N° de contrat', 'Enveloppe', 'Partenaire', 'Valorisation']])
st.divider()
contrat = st.selectbox(
    'Sélectionner contrat',
    df_contrats_client['N° de contrat'].unique()
)
df_allocations_client = df_allocations[df_allocations['Numéro contrat'] == contrat]


# IR reduction option
df_contrat_selected = df_contrats_client[df_contrats_client['N° de contrat'] == contrat]

st.dataframe(df_contrat_selected)

    

# Update od session_state
if 'client' not in ss:
    ss['client'] = ''
if 'contrat' not in ss:
    ss['contrat'] = ''
if 'df_contrat_selected' not in ss:
    ss['df_contrat_selected'] = pd.DataFrame()
if 'df_allocations_client' not in ss:
    ss['df_allocations_client'] = df_allocations_client

ss['client'] = client
ss['contrat'] = contrat
ss['df_contrat_selected'] = df_contrat_selected
ss['df_allocations_client'] = df_allocations_client

