import streamlit as st
from streamlit import session_state as ss

import os
import sys
import json
import pandas as pd
from pathlib import Path
from config import DEMO_MODE, DEMO_DATA_CONTRATS_FILE, DEMO_DATA_ALLOCATIONS_FILE, REAL_DATA_CONTRATS_PATH, REAL_DATA_ALLOCATIONS_PATH


BASE_DIR = Path(__file__).resolve().parents[1]
CONTRACT_FILTERS_PATH = BASE_DIR / "defaults" / "contract_filters.json"


def normalize_contract_number(series: pd.Series) -> pd.Series:
    """Normalise les numeros de contrat en supprimant les prefixes type 'B7 ' / '9E ' quand ils precedent un bloc numerique."""
    s = series.astype(str).str.strip()
    # Exemples: 'B7 270745982' -> '270745982', '9E 269218752' -> '269218752'
    # Ne touche pas les formats sans espace (ex: '0010494244001-Le PER Eres').
    return s.str.replace(r'^[A-Z0-9]{1,4}\s+(?=\d{6,}$)', '', regex=True)


def to_numeric_amount(series: pd.Series) -> pd.Series:
    """Convertit des montants texte en numerique (gere espaces insécables, virgules et valeurs non disponibles)."""
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace('\u202f', '', regex=False)
        .str.replace('\xa0', '', regex=False)
        .str.replace(' ', '', regex=False)
        .str.replace(',', '.', regex=False)
    )
    return pd.to_numeric(cleaned, errors='coerce')


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


def load_contract_filter_presets() -> dict:
    if not CONTRACT_FILTERS_PATH.exists():
        return {}
    try:
        with CONTRACT_FILTERS_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    sanitized = {}
    for name, contracts in data.items():
        if isinstance(name, str) and isinstance(contracts, list):
            sanitized[name] = [str(c) for c in contracts]
    return sanitized


def save_contract_filter_presets(presets: dict):
    CONTRACT_FILTERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONTRACT_FILTERS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(presets, handle, ensure_ascii=True, indent=2)

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

    df_contrats = pd.DataFrame()
    df_allocations = pd.DataFrame()
    df_contrats_upd = pd.DataFrame()
    df_summary_allocations = pd.DataFrame()

# Ingest information from contracts
nb_imput_bruts_courant = 0
imput_bruts_details = []
if (filename_contrats is not None):
    df_contrats = pd.read_csv(filename_contrats, header=0,
                              sep=';', decimal=',', thousands=' ')

    # Normaliser N° de contrat pour matcher l'historique quel que soit le format d'export.
    df_contrats['N° de contrat'] = normalize_contract_number(df_contrats['N° de contrat'])

    # Filtre Agrégé auto : ancien format = Oui/Non, nouveau format = Non disponible (garder tout)
    valeurs_agreage = df_contrats['Agrégé auto'].dropna().unique()
    if any(v in ['Oui', 'Non'] for v in valeurs_agreage):
        df_contrats = df_contrats[df_contrats['Agrégé auto'].str.contains("Oui") == True]
    cols_a_supprimer = [c for c in ['Crédit', 'Consultant', 'Agrégé auto'] if c in df_contrats.columns]
    df_contrats.drop(cols_a_supprimer, inplace=True, axis=1)
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

    versements_bruts_num = to_numeric_amount(df_contrats['Montant total des versements bruts'])
    versements_nets_num = to_numeric_amount(df_contrats['Montant total des versements nets'])
    mask_bruts_absents = versements_bruts_num.isna() & versements_nets_num.notna()
    nb_imput_bruts_courant = int(mask_bruts_absents.sum())

    df_contrats['Montant total des versements bruts'] = versements_bruts_num.fillna(0)
    df_contrats['Montant total des versements nets'] = versements_nets_num.fillna(0)
    df_contrats.loc[mask_bruts_absents, 'Montant total des versements bruts'] = df_contrats.loc[
        mask_bruts_absents, 'Montant total des versements nets'
    ]

    if nb_imput_bruts_courant > 0:
        cols_details_courant = [
            c for c in ['Titulaire(s)', 'N° de contrat', 'Enveloppe', 'Contrat', 'Partenaire']
            if c in df_contrats.columns
        ]
        if cols_details_courant:
            details_courant = df_contrats.loc[mask_bruts_absents, cols_details_courant].copy()
        else:
            details_courant = df_contrats.loc[mask_bruts_absents].copy()
        details_courant['Source'] = 'Courant'
        imput_bruts_details.append(details_courant)

    df_contrats['Frais'] = df_contrats['Montant total des versements bruts'] - \
        df_contrats['Montant total des versements nets']
    df_contrats['Frais'] = - df_contrats['Frais']

    df_contrats['Ouverture'] = pd.to_datetime(
        df_contrats['Ouverture'], format="mixed", dayfirst=True, errors='coerce').dt.normalize()
    if 'Date de valorisation' in df_contrats.columns:
        df_contrats['Date de valorisation'] = pd.to_datetime(
            df_contrats['Date de valorisation'], format="%d/%m/%Y", errors='coerce'
        ).dt.normalize()


    st.dataframe(df_contrats)

# Ingest allocations
if (filename_allocations is not None):
    df_allocations = pd.read_csv(
        filename_allocations, header=0, sep=';', decimal=',', thousands=' ')
    df_allocations['Titulaire(s)'] = df_allocations[['Nom', 'Prénom']].apply(
        lambda x: ' '.join(x), axis=1)
    # Normaliser Numéro contrat (meme logique que N° de contrat dans les contrats).
    df_allocations['Numéro contrat'] = normalize_contract_number(df_allocations['Numéro contrat'])
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

    # Convertir les colonnes numériques ('Non disponible' → NaN → 0)
    for col in ['+/- value (en €)', 'Encours en €', 'Nombre de parts', 'Valeur unitaire en €']:
        if col in df_allocations.columns:
            df_allocations[col] = pd.to_numeric(df_allocations[col], errors='coerce').fillna(0)

    # Si +/- value (en €) est absent/nul, le recalculer depuis +/- value (en %)) et Encours en €
    col_pct = '+/- value (en %))'
    if col_pct in df_allocations.columns:
        df_allocations[col_pct] = df_allocations[col_pct].astype(str).str.replace(',', '.').str.strip()
        df_allocations[col_pct] = pd.to_numeric(df_allocations[col_pct], errors='coerce')
        mask = df_allocations['+/- value (en €)'] == 0
        pct = df_allocations.loc[mask, col_pct] / 100
        encours = df_allocations.loc[mask, 'Encours en €']
        df_allocations.loc[mask, '+/- value (en €)'] = encours * pct / (1 + pct).replace(0, float('nan'))

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
csv_files_contrats = [k for k in csv_files_history if 'selection_actif' in k or 'Export_Contrats' in k]

df_contrat_agg = pd.DataFrame()
nb_imput_bruts_historique = 0
for csv in csv_files_contrats:
    # Nouveau format (Export_Contrats_*) : pas de ligne d'avertissement → header=0
    # Ancien format (Export_selection_actifs_*) : ligne d'avertissement en ligne 0 → header=1
    hdr = 0 if csv.startswith('Export_Contrats') else 1
    df_contrats_a = pd.read_csv(base_path + csv, header=hdr,
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

    # Normaliser N° de contrat dans l'historique pour rester coherent avec le fichier courant.
    df_contrats_a['N° de contrat'] = normalize_contract_number(df_contrats_a['N° de contrat'])

    # Filtre Agrégé auto : ancien format = Oui/Non, certains nouveaux exports = Non disponible.
    valeurs_agreage_hist = df_contrats_a['Agrégé auto'].dropna().unique()
    if any(v in ['Oui', 'Non'] for v in valeurs_agreage_hist):
        df_contrats_a = df_contrats_a[df_contrats_a['Agrégé auto'].str.contains("Oui") == True]
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

    # Les nouveaux exports peuvent contenir des chaînes (ex: "Non disponible") sur ces colonnes.
    versements_bruts_hist_num = to_numeric_amount(df_contrats_a['Montant total des versements bruts'])
    versements_nets_hist_num = to_numeric_amount(df_contrats_a['Montant total des versements nets'])
    mask_bruts_hist_absents = versements_bruts_hist_num.isna() & versements_nets_hist_num.notna()
    nb_imput_bruts_historique += int(mask_bruts_hist_absents.sum())

    df_contrats_a['Montant total des versements bruts'] = versements_bruts_hist_num.fillna(0)
    df_contrats_a['Montant total des versements nets'] = versements_nets_hist_num.fillna(0)
    df_contrats_a.loc[mask_bruts_hist_absents, 'Montant total des versements bruts'] = df_contrats_a.loc[
        mask_bruts_hist_absents, 'Montant total des versements nets'
    ]

    if mask_bruts_hist_absents.any():
        cols_details_hist = [
            c for c in ['Date export', 'Titulaire(s)', 'N° de contrat', 'Enveloppe', 'Contrat', 'Partenaire']
            if c in df_contrats_a.columns
        ]
        if cols_details_hist:
            details_hist = df_contrats_a.loc[mask_bruts_hist_absents, cols_details_hist].copy()
        else:
            details_hist = df_contrats_a.loc[mask_bruts_hist_absents].copy()
        details_hist['Source'] = 'Historique'
        details_hist['Fichier source'] = csv
        imput_bruts_details.append(details_hist)

    df_contrats_a['Frais'] = df_contrats_a['Montant total des versements bruts'] - \
        df_contrats_a['Montant total des versements nets']
    df_contrats_a['Frais'] = - df_contrats_a['Frais']

    df_contrats_a['Ouverture'] = pd.to_datetime(
        df_contrats_a['Ouverture'], format="mixed", dayfirst=True, errors='coerce').dt.normalize()
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

nb_imput_total = int(nb_imput_bruts_courant + nb_imput_bruts_historique)
if nb_imput_total > 0:
    st.info(
        f"ℹ️ Versements bruts imputes depuis versements nets: {nb_imput_total} ligne(s) "
        f"(courant: {nb_imput_bruts_courant}, historique: {nb_imput_bruts_historique})."
    )
    if imput_bruts_details:
        df_imput_bruts = pd.concat(imput_bruts_details, ignore_index=True).drop_duplicates()
        with st.expander("Voir les contrats concernes par l'imputation des versements bruts"):
            st.dataframe(df_imput_bruts, hide_index=True)

# Filtre global des titulaires (persistant) pour le reste de l'application
st.subheader("Filtrage global des titulaires")

all_holders = sorted(df_contrats['Titulaire(s)'].astype(str).unique().tolist()) if 'Titulaire(s)' in df_contrats.columns else []
if 'global_holder_filter_selection' not in ss:
    ss['global_holder_filter_selection'] = all_holders

presets = load_contract_filter_presets()
preset_names = sorted(presets.keys())

col_preset, col_load, col_reset = st.columns([2, 1, 1])
with col_preset:
    selected_preset_name = st.selectbox(
        "Profil de filtre sauvegarde",
        options=["(Aucun)"] + preset_names,
        index=0,
        key="holder_filter_preset_selector",
    )
with col_load:
    load_preset_clicked = st.button("Charger")
with col_reset:
    reset_filter_clicked = st.button("Tout afficher")

if load_preset_clicked and selected_preset_name != "(Aucun)":
    loaded_holders = [h for h in presets.get(selected_preset_name, []) if h in all_holders]
    ss['global_holder_filter_selection'] = loaded_holders

if reset_filter_clicked:
    ss['global_holder_filter_selection'] = all_holders

selected_holders = st.multiselect(
    "Titulaires affiches dans le reste de l'application",
    options=all_holders,
    key="global_holder_filter_selection",
)

save_col, save_name_col, delete_col = st.columns([1, 2, 1])
with save_name_col:
    preset_name_to_save = st.text_input("Nom du profil", key="holder_filter_profile_name")
with save_col:
    save_profile_clicked = st.button("Sauvegarder profil")
with delete_col:
    delete_profile_clicked = st.button("Supprimer profil")

if save_profile_clicked:
    clean_name = preset_name_to_save.strip()
    if not clean_name:
        st.warning("Veuillez saisir un nom de profil.")
    else:
        presets[clean_name] = [str(h) for h in selected_holders]
        save_contract_filter_presets(presets)
        st.success(f"Profil '{clean_name}' sauvegarde.")

if delete_profile_clicked:
    clean_name = preset_name_to_save.strip()
    if not clean_name:
        st.warning("Indiquez le nom du profil a supprimer.")
    elif clean_name not in presets:
        st.warning("Profil introuvable.")
    else:
        presets.pop(clean_name, None)
        save_contract_filter_presets(presets)
        st.success(f"Profil '{clean_name}' supprime.")

effective_holders = [str(h) for h in selected_holders]
if len(effective_holders) == 0:
    st.warning("Aucun titulaire selectionne: le filtre est ignore et tous les titulaires sont affiches.")
    effective_holders = all_holders

if 'Titulaire(s)' in df_contrats.columns:
    mask_holders = df_contrats['Titulaire(s)'].astype(str).isin(effective_holders)
    df_contrats_filtered = df_contrats[mask_holders].copy()
else:
    df_contrats_filtered = df_contrats.copy()

effective_contracts = (
    df_contrats_filtered['N° de contrat'].astype(str).unique().tolist()
    if 'N° de contrat' in df_contrats_filtered.columns else []
)

if 'N° de contrat' in df_contrats_upd.columns:
    mask_contrats_upd = df_contrats_upd['N° de contrat'].astype(str).isin(effective_contracts)
    df_contrats_upd_filtered = df_contrats_upd[mask_contrats_upd].copy()
else:
    df_contrats_upd_filtered = df_contrats_upd.copy()

if 'Numéro contrat' in df_allocations.columns:
    mask_alloc = df_allocations['Numéro contrat'].astype(str).isin(effective_contracts)
    df_allocations_filtered = df_allocations[mask_alloc].copy()
else:
    df_allocations_filtered = df_allocations.copy()

if 'Numéro contrat' in df_summary_allocations.columns:
    mask_summary = df_summary_allocations['Numéro contrat'].astype(str).isin(effective_contracts)
    df_summary_allocations_filtered = df_summary_allocations[mask_summary].copy()
else:
    df_summary_allocations_filtered = df_summary_allocations.copy()

if 'N° de contrat' in df_contrat_agg_filtered.columns:
    mask_hist = df_contrat_agg_filtered['N° de contrat'].astype(str).isin(effective_contracts)
    df_contrat_agg_contract_filtered = df_contrat_agg_filtered[mask_hist].copy()
else:
    df_contrat_agg_contract_filtered = df_contrat_agg_filtered.copy()

if 'N° de contrat' in df_contrat_agg.columns:
    mask_hist_raw = df_contrat_agg['N° de contrat'].astype(str).isin(effective_contracts)
    df_contrat_agg_raw_contract_filtered = df_contrat_agg[mask_hist_raw].copy()
else:
    df_contrat_agg_raw_contract_filtered = df_contrat_agg.copy()

if 'df_contrat_selected' in ss and not ss['df_contrat_selected'].empty:
    contrat_actif = str(ss['df_contrat_selected']['N° de contrat'].iloc[0]) if 'N° de contrat' in ss['df_contrat_selected'].columns else None
    if contrat_actif and contrat_actif not in set(effective_contracts):
        ss['df_contrat_selected'] = pd.DataFrame()
        ss['df_allocations_client'] = pd.DataFrame()
        ss['contrat'] = None
        ss['client'] = None

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
if 'df_contrats_raw' not in ss:
    ss['df_contrats_raw'] = pd.DataFrame()
if 'df_contrats_upd_raw' not in ss:
    ss['df_contrats_upd_raw'] = pd.DataFrame()
if 'df_allocations_raw' not in ss:
    ss['df_allocations_raw'] = pd.DataFrame()
if 'df_summary_allocations_raw' not in ss:
    ss['df_summary_allocations_raw'] = pd.DataFrame()

ss['df_allocations_raw'] = df_allocations
ss['df_contrats_raw'] = df_contrats
ss['df_contrats_upd_raw'] = df_contrats_upd
ss['df_summary_allocations_raw'] = df_summary_allocations

ss['df_allocations'] = df_allocations_filtered
ss['df_contrats'] = df_contrats_filtered
ss['df_contrats_upd'] = df_contrats_upd_filtered
ss['df_summary_allocations'] = df_summary_allocations_filtered
ss['df_portfolio'] = df_portfolio
ss['df_contrat_agg_raw'] = df_contrat_agg_raw_contract_filtered
ss['df_contrat_agg'] = df_contrat_agg_contract_filtered
ss['df_contrat_agg_filtered'] = df_contrat_agg_contract_filtered
ss['export_exclusion_dates'] = exports_a_exclure_resume
ss['export_exclusion_details'] = exports_a_exclure_details
