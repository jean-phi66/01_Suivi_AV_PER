import streamlit as st
from streamlit import session_state as ss

import os
import sys
import pandas as pd
from config import DEMO_MODE, DEMO_DATA_CONTRATS_FILE, DEMO_DATA_ALLOCATIONS_FILE, REAL_DATA_CONTRATS_PATH, REAL_DATA_ALLOCATIONS_PATH


def detect_export_outliers(df_base: pd.DataFrame, seuil_filtrage_val: float = 0.25, seuil_filtrage_vn: float = 0.05):
    """Identifie les exports aberrants (variations anormales) et retourne un résumé et le détail."""
    exclusions_resume = []
    exclusions_details = []

    required_cols = {'Date export', 'Valorisation', 'Montant total des versements nets'}
    if df_base.empty or not required_cols.issubset(df_base.columns):
        return exclusions_resume, exclusions_details

    df_temp = df_base[df_base['Date export'].notna()].copy()
    if df_temp.empty:
        return exclusions_resume, exclusions_details

    export_test = df_temp.groupby('Date export').agg({
        'Valorisation': 'sum',
        'Montant total des versements nets': 'sum'
    }).reset_index().sort_values('Date export')

    for idx in range(1, len(export_test)):
        val_actuelle = export_test.iloc[idx]['Valorisation']
        val_precedente = export_test.iloc[idx-1]['Valorisation']
        vn_actuel = export_test.iloc[idx]['Montant total des versements nets']
        vn_precedent = export_test.iloc[idx-1]['Montant total des versements nets']

        exclure = False
        raison = []

        if val_precedente > 0:
            variation_val = abs((val_actuelle - val_precedente) / val_precedente)
            if variation_val > seuil_filtrage_val:
                exclure = True
                raison.append(f"Variation valorisation: {variation_val*100:.1f}%")

        if vn_precedent > 0:
            variation_vn = (vn_actuel - vn_precedent) / vn_precedent
            if variation_vn < -seuil_filtrage_vn:
                exclure = True
                raison.append(f"Versements nets en baisse: {variation_vn*100:.1f}%")

        if exclure:
            date_export = export_test.iloc[idx]['Date export']
            exclusions_resume.append({
                'date': date_export,
                'raison': ' | '.join(raison)
            })
            exclusions_details.append({
                'Date export': date_export,
                'Val précédente': val_precedente,
                'Val actuelle (exclue)': val_actuelle,
                'VN précédent': vn_precedent,
                'VN actuel': vn_actuel,
                'Raison': ' | '.join(raison)
            })

    return exclusions_resume, exclusions_details

# Afficher le statut du mode démo
if DEMO_MODE:
    st.info("📊 Utilisation des données de démonstration")

import_data_checkbox = st.checkbox("Importer données", value=False)

if import_data_checkbox:
    filename_contrats = st.file_uploader(
        "Données des contrats", type={"csv"})
    filename_allocations = st.file_uploader(
        "Données détaillées", type={"csv"})
else:
    if DEMO_MODE:
        # Mode démo : utiliser les fichiers de démo
        filename_contrats = DEMO_DATA_CONTRATS_FILE
        filename_allocations = DEMO_DATA_ALLOCATIONS_FILE
    else:
        # Mode normal : utiliser les dossiers réels
        base_path = REAL_DATA_CONTRATS_PATH
        all_files = os.listdir(base_path)
        csv_files_contrats = list(filter(lambda f: f.endswith('.csv'), all_files))
        filename_contrats = base_path + csv_files_contrats[0]

        base_path = REAL_DATA_ALLOCATIONS_PATH
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
    
    df_contrats = df_contrats[df_contrats['Enveloppe'].str.contains(
        "Fip") == False]
    df_contrats = df_contrats[df_contrats['Enveloppe'].str.contains(
        "PEA") == False]


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


# Portfolio data (non utilisé actuellement)
df_portfolio = pd.DataFrame()

# Ingest historical data
base_path = '/Users/jean-philippenavarro/Documents/10_CGP/20_Outils - Simulateurs/01_Suivi_AV_PER/00_Exports/old/'
all_files = os.listdir(base_path)
csv_files_history = list(filter(lambda f: f.endswith('.csv'), all_files))
#filename_contrats = base_path + csv_files_contrats[0]
csv_files_contrats = [k for k in csv_files_history if 'selection_actif' in k]

df_contrat_agg = pd.DataFrame()
for csv in csv_files_contrats:
    df_contrats_a = pd.read_csv(base_path + csv, header=1,
                              sep=';', decimal=',', thousands=' ',
                              parse_dates=['Date de valorisation'], dayfirst=True)

    # Extraire la date d'export du nom de fichier
    # Format: Export_selection_actifs_adv_XXXXXX_DD_MM_YYYY_HH_MM.csv
    import re
    match = re.search(r'(\d{2})_(\d{2})_(\d{4})', csv)
    if match:
        day, month, year = match.groups()
        date_export = pd.to_datetime(f"{year}-{month}-{day}")
        df_contrats_a['Date export'] = date_export
    else:
        df_contrats_a['Date export'] = pd.NaT

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

# Filtrer les exports aberrants dès l'ingestion pour uniformiser les sorties (une seule fois)
exports_a_exclure_resume, exports_a_exclure_details = detect_export_outliers(df_contrat_agg)
dates_a_exclure = [d['date'] for d in exports_a_exclure_resume]

if dates_a_exclure:
    df_contrat_agg_filtered = df_contrat_agg[~df_contrat_agg['Date export'].isin(dates_a_exclure)].copy()
    st.warning(f"⚠️ {len(dates_a_exclure)} export(s) avec données aberrantes exclu(s) dès l'ingestion")
    with st.expander("Voir les exports exclus"):
        for d in exports_a_exclure_resume:
            st.write(f"- **{d['date'].strftime('%d/%m/%Y')}** : {d['raison']}")
else:
    df_contrat_agg_filtered = df_contrat_agg.copy()

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
if 'df_contrat_agg_filtered' not in ss:
    ss['df_contrat_agg_filtered'] = pd.DataFrame()
if 'export_exclusion_dates' not in ss:
    ss['export_exclusion_dates'] = []
if 'export_exclusion_details' not in ss:
    ss['export_exclusion_details'] = []
if 'df_contrat_agg_raw' not in ss:
    ss['df_contrat_agg_raw'] = pd.DataFrame()

ss['df_allocations'] = df_allocations
ss['df_contrats'] = df_contrats 
ss['df_contrats_upd'] = df_contrats_upd
ss['df_summary_allocations'] = df_summary_allocations
ss['df_portfolio'] = df_portfolio
ss['df_contrat_agg_raw'] = df_contrat_agg
ss['df_contrat_agg'] = df_contrat_agg_filtered
ss['df_contrat_agg_filtered'] = df_contrat_agg_filtered
ss['export_exclusion_dates'] = exports_a_exclure_resume
ss['export_exclusion_details'] = exports_a_exclure_details
