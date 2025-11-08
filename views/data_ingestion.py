import streamlit as st
from streamlit import session_state as ss

import os
import pandas as pd

import_data_checkbox = st.checkbox("Importer données", value=False)

if import_data_checkbox:
    filename_contrats = st.file_uploader(
        "Données des contrats", type={"csv"})
    filename_allocations = st.file_uploader(
        "Données détaillées", type={"csv"})
else:
    #base_path = '/Users/jean-philippenavarro/Documents/10_CGP/99_Data_analytics/UC2024/Suivi clients/00_Exports/1_Selection_Actifs/'
    base_path = './00_Exports/1_Selection_Actifs/'
    all_files = os.listdir(base_path)
    csv_files_contrats = list(filter(lambda f: f.endswith('.csv'), all_files))
    filename_contrats = base_path + csv_files_contrats[0]

    #base_path = '/Users/jean-philippenavarro/Documents/10_CGP/99_Data_analytics/UC2024/Suivi clients/00_Exports/2_Situations_Detaillées/'
    base_path = './00_Exports/2_Situations_Detaillées/'
    all_files = os.listdir(base_path)
    csv_files_contrats = list(filter(lambda f: f.endswith('.csv'), all_files))
    filename_allocations = base_path + csv_files_contrats[0]

# Ingest information from contracts
if (filename_contrats is not None):
    df_contrats = pd.read_csv(filename_contrats, header=1,
                              sep=';', decimal=',', thousands=' ')

    df_contrats = df_contrats[df_contrats['Agrégé auto'].str.contains(
        "Oui") == True]
    df_contrats.drop(['Crédit', 'Consultant', 'Agrégé auto'],
                     inplace=True, axis=1)
    df_contrats = df_contrats[~df_contrats['Titulaire(s)'].isin(
        ["NAVARRO Camille", "NAVARRO Emilie", "CALMET Jean-marc", "DAVID Lionel"])]
    
    #df_contrats = df_contrats[df_contrats['Titulaire(s)'].str.contains('ORTOCHAU|LESTRA')]
    
    
    df_contrats = df_contrats[df_contrats['Enveloppe'].str.contains(
        "Fip") == False]
    df_contrats = df_contrats[df_contrats['Enveloppe'].str.contains(
        "PEA") == False]

    df_contrats['Montant total des versements bruts'][
        df_contrats['Titulaire(s)'] == 'ROUCHOUSE Laure'] = 70000.
    df_contrats['Montant total des versements nets'][df_contrats[
        'Titulaire(s)'] == 'ROUCHOUSE Laure'] = 70000. * (1-.036)

    # Assurer que 'Montant total des rachats bruts' est numérique et gérer les NaN
    if 'Montant total des rachats bruts' in df_contrats.columns:
        df_contrats['Montant total des rachats bruts'] = pd.to_numeric(df_contrats['Montant total des rachats bruts'], errors='coerce').fillna(0)
    else:
        # Si la colonne n'existe pas, la créer et la remplir avec 0
        df_contrats['Montant total des rachats bruts'] = 0.0

    df_contrats['Frais'] = df_contrats['Montant total des versements bruts'] - \
        df_contrats['Montant total des versements nets']
    df_contrats['Frais'] = - df_contrats['Frais']

    df_contrats['Ouverture'] = pd.to_datetime(
        df_contrats['Ouverture'], format="mixed", errors='coerce').dt.normalize()
    if 'Date de valorisation' in df_contrats.columns:
        df_contrats['Date de valorisation'] = pd.to_datetime(
            df_contrats['Date de valorisation'], format="%d/%m/%Y", errors='coerce'
        ).dt.normalize()


    st.dataframe(df_contrats)

# Ingest allocations
if (filename_allocations is not None):
    df_allocations = pd.read_csv(
        filename_allocations, sep=';', decimal=',', thousands=' ')
    df_allocations['Titulaire(s)'] = df_allocations[['Nom', 'Prénom']].apply(
        lambda x: ' '.join(x), axis=1)
    df_allocations = df_allocations[~df_allocations['Titulaire(s)'].isin(
        ["NAVARRO Camille", "NAVARRO Emilie", "CALMET Jean-marc", "DAVID Lionel"])]
    df_allocations = df_allocations[~df_allocations['Prestation'].str.contains(
        "PEA PME")]
    df_allocations = df_allocations[~df_allocations['Prestation'].str.contains(
        "FIP")]
    df_allocations['Type'][df_allocations['Support']
                           == 'NextStage Croissance A'] = 'Capital Risque'
    df_allocations['Type'][df_allocations['Support'] ==
                           'EXCELTIS RENDEMENT OCTOBRE 24'] = 'Fonds Structurés'
    df_allocations['Type'][df_allocations['Support'] ==
                           'SUNNY OPPORTUNITÉS 2025 R'] = 'Obligations à Echéance'
    df_allocations['Type'][df_allocations['Support'] ==
                           'R-co Target 2027 HY F EUR'] = 'Obligations à Echéance'
    
    # Updating contracts with allocation performance
    df_summary_allocations = df_allocations[~df_allocations['Type'].isin(["Fonds en Euros"])]
    df_summary_allocations = df_summary_allocations.groupby(
        'Numéro contrat')['+/- value (en €)'].sum().reset_index('Numéro contrat')
    
    if (filename_contrats is not None):
        df_contrats_upd = pd.merge(df_contrats, df_summary_allocations,
                                how='left', left_on='N° de contrat', right_on='Numéro contrat')
        df_contrats_upd['Performance embarquée'] = df_contrats_upd[
            'Performance financière en euros (perf du contrat)'] - df_contrats_upd['+/- value (en €)']
        df_contrats_upd.rename(
            columns={'+/- value (en €)': 'Performance allocation'}, inplace=True)


# Ingest portfolio
filename_portfolio = './00_Exports/3_Fonds/3_Export_2024-12-21_210957_Complet.csv'
df_portfolio = pd.read_csv(
    filename_portfolio, encoding='utf-16-LE', sep=';', decimal=',')

df_portfolio = df_portfolio[['Nom du fonds', 'Code ISIN',
                                'Société de gestion', 'SRI', 'Catégorie Quantalys', 'VL',
                                'Perf 6 mois', 'Perf YTD', 'Perf cumulée glissante 1 an']]

# Ingest historical data
base_path = './00_Exports/old/'
all_files = os.listdir(base_path)
csv_files_history = list(filter(lambda f: f.endswith('.csv'), all_files))
#filename_contrats = base_path + csv_files_contrats[0]
csv_files_contrats = [k for k in csv_files_history if 'selection_actif' in k]

df_contrat_agg = pd.DataFrame()
for csv in csv_files_contrats:
    df_contrats_a = pd.read_csv(base_path + csv, header=1,
                              sep=';', decimal=',', thousands=' ',
                              parse_dates=['Date de valorisation'], dayfirst=True)

    df_contrats_a = df_contrats_a[df_contrats_a['Agrégé auto'].str.contains(
        "Oui") == True]
    df_contrats_a.drop(['Crédit', 'Consultant', 'Agrégé auto'],
                     inplace=True, axis=1)
    df_contrats_a = df_contrats_a[~df_contrats_a['Titulaire(s)'].isin(
        ["NAVARRO Camille", "NAVARRO Emilie", "CALMET Jean-marc", "DAVID Lionel"])]
    df_contrats_a = df_contrats_a[df_contrats_a['Enveloppe'].str.contains(
        "Fip") == False]
    df_contrats_a = df_contrats_a[df_contrats_a['Enveloppe'].str.contains(
        "PEA") == False]

    df_contrats_a['Montant total des versements bruts'][
        df_contrats_a['Titulaire(s)'] == 'ROUCHOUSE Laure'] = 70000.
    df_contrats_a['Montant total des versements nets'][df_contrats_a[
        'Titulaire(s)'] == 'ROUCHOUSE Laure'] = 70000. * (1-.036)

    # Assurer que 'Montant total des rachats bruts' est numérique et gérer les NaN pour l'historique
    if 'Montant total des rachats bruts' in df_contrats_a.columns:
        df_contrats_a['Montant total des rachats bruts'] = pd.to_numeric(df_contrats_a['Montant total des rachats bruts'], errors='coerce').fillna(0)
    else:
        # Si la colonne n'existe pas, la créer et la remplir avec 0
        df_contrats_a['Montant total des rachats bruts'] = 0.0

    df_contrats_a['Frais'] = df_contrats_a['Montant total des versements bruts'] - \
        df_contrats_a['Montant total des versements nets']
    df_contrats_a['Frais'] = - df_contrats_a['Frais']

    df_contrats_a['Ouverture'] = pd.to_datetime(
        df_contrats_a['Ouverture'], format="mixed").dt.normalize()
    df_contrats_a['Date de valorisation'] = pd.to_datetime(
        df_contrats_a['Date de valorisation'], format="%d/%m/%Y", errors='coerce').dt.normalize()
    
    df_contrat_agg = pd.concat([df_contrat_agg, df_contrats_a])

if 'df_allocations' not in ss:
    ss['df_allocations'] = pd.DataFrame()
if 'df_contrats' not in ss :
    ss['df_contrats'] = pd.DataFrame()
if 'df_contrats_upd' not in ss :
    ss['df_contrats_upd'] = pd.DataFrame()
if 'df_summary_allocations' not in ss :
    ss['df_summary_allocations'] = pd.DataFrame()
if 'df_portfolio' not in ss:
    ss['df_portfolio'] = pd.DataFrame()
if 'df_contrat_agg' not in ss:
    ss['df_contrat_agg'] = pd.DataFrame()

ss['df_allocations'] = df_allocations
ss['df_contrats'] = df_contrats 
ss['df_contrats_upd'] = df_contrats_upd
ss['df_summary_allocations'] = df_summary_allocations
ss['df_portfolio'] = df_portfolio
ss['df_contrat_agg'] = df_contrat_agg
