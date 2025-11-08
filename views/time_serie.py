import streamlit as st
from streamlit import session_state as ss

import pandas as pd
import plotly.express as px

import os


base_path = './00_Exports/old/'
all_files = os.listdir(base_path)
csv_files_history = list(filter(lambda f: f.endswith('.csv'), all_files))
#filename_contrats = base_path + csv_files_contrats[0]
csv_files_contrats = [k for k in csv_files_history if 'selection_actif' in k]

df_contrat_agg = pd.DataFrame()
for csv in csv_files_contrats:
    df_contrats = pd.read_csv(base_path + csv, header=1,
                              sep=';', decimal=',', thousands=' ',
                              parse_dates=['Date de valorisation'], dayfirst=True)

    df_contrats = df_contrats[df_contrats['Agrégé auto'].str.contains(
        "Oui") == True]
    df_contrats.drop(['Crédit', 'Consultant', 'Agrégé auto'],
                     inplace=True, axis=1)
    df_contrats = df_contrats[~df_contrats['Titulaire(s)'].isin(
        ["NAVARRO Camille", "NAVARRO Emilie", "CALMET Jean-marc", "DAVID Lionel"])]
    df_contrats = df_contrats[df_contrats['Enveloppe'].str.contains(
        "Fip") == False]
    df_contrats = df_contrats[df_contrats['Enveloppe'].str.contains(
        "PEA") == False]

    df_contrats['Montant total des versements bruts'][
        df_contrats['Titulaire(s)'] == 'ROUCHOUSE Laure'] = 70000.
    df_contrats['Montant total des versements nets'][df_contrats[
        'Titulaire(s)'] == 'ROUCHOUSE Laure'] = 70000. * (1-.036)

    df_contrats['Frais'] = df_contrats['Montant total des versements bruts'] - \
        df_contrats['Montant total des versements nets']
    df_contrats['Frais'] = - df_contrats['Frais']

    df_contrats['Ouverture'] = pd.to_datetime(
        df_contrats['Ouverture'], format="mixed").dt.normalize()
    df_contrats['Date de valorisation'] = pd.to_datetime(
        df_contrats['Date de valorisation'], format="format='%d/%m/%Y").dt.normalize()
    
    df_contrat_agg = pd.concat([df_contrat_agg, df_contrats])
    

st.write(csv_files_contrats)
st.dataframe(df_contrat_agg)

client = st.selectbox(
    'Sélectionner client',
    df_contrats.sort_values(by="Titulaire(s)")['Titulaire(s)'].unique()
)
df_contrats_client = df_contrats[df_contrats['Titulaire(s)'] == client]

# Select contract of client
st.dataframe(df_contrats_client[[
                      'Titulaire(s)', 'N° de contrat', 'Enveloppe', 'Partenaire']].drop_duplicates())
st.divider()
contrat = st.selectbox(
    'Sélectionner contrat',
    df_contrats_client['N° de contrat'].unique()
)

df_contrat_selected = df_contrat_agg[df_contrat_agg['N° de contrat'] == contrat]
st.dataframe(df_contrat_selected[['Titulaire(s)', 'Date de valorisation', 'Valorisation']])
fig_evol = px.scatter(df_contrat_selected, x='Date de valorisation', y='Valorisation')
st.plotly_chart(fig_evol)