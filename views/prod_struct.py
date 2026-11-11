import streamlit as st
from streamlit import session_state as ss

import plotly.express as px
import pandas as pd
from io import BytesIO
from pathlib import Path
import re
import unicodedata

df_allocations = ss['df_allocations']
df_allocations_all = ss.get('df_allocations_raw', df_allocations)
df_contrats_ref = ss.get('df_contrats_raw', ss.get('df_contrats', pd.DataFrame()))
df_contrats_filtered = ss.get('df_contrats', pd.DataFrame())
BASE_DIR = Path(__file__).resolve().parents[1]
HISTORICAL_EXPORTS_DIR = BASE_DIR / "00_Exports" / "old"

allowed_contracts = set()
if not df_contrats_filtered.empty and 'N° de contrat' in df_contrats_filtered.columns:
    allowed_contracts = {
        str(x).strip()
        for x in df_contrats_filtered['N° de contrat'].dropna().astype(str)
        if str(x).strip()
    }


def _build_excel_bytes(df):
    output = BytesIO()
    with pd.ExcelWriter(output) as writer:
        df.to_excel(writer, index=False, sheet_name="Contrats")
    return output.getvalue()


def _normalize_contract_number(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    return s.str.replace(r'^[A-Z0-9]{1,4}\s+(?=\d{6,}$)', '', regex=True)


def _normalize_support_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_export_date_from_filename(filename: str):
    match = re.search(r'(\d{2})_(\d{2})_(\d{4})', filename)
    if not match:
        return pd.NaT
    day, month, year = match.groups()
    return pd.to_datetime(f"{year}-{month}-{day}", errors='coerce')


@st.cache_data(show_spinner=False)
def _load_historical_structured_support_last_seen() -> pd.DataFrame:
    if not HISTORICAL_EXPORTS_DIR.exists():
        return pd.DataFrame(columns=['Support', 'Last seen'])

    files = sorted(HISTORICAL_EXPORTS_DIR.glob("*.csv"))
    files = [f for f in files if "situations_detaillees" in f.name.lower()]
    if not files:
        return pd.DataFrame(columns=['Support', 'Last seen'])

    rows = []
    for file_path in files:
        fallback_date = _extract_export_date_from_filename(file_path.name)
        try:
            df_supports = pd.read_csv(
                file_path,
                header=0,
                sep=';',
                decimal=',',
                thousands=' ',
                usecols=lambda c: c in {'Support', "Date d'import"},
            )
        except Exception:
            continue

        if 'Support' not in df_supports.columns:
            continue

        df_supports['Support'] = df_supports['Support'].astype(str).str.strip()
        df_supports = df_supports[df_supports['Support'].str.contains('excel', case=False, na=False)].copy()
        if df_supports.empty:
            continue

        if "Date d'import" in df_supports.columns:
            last_seen = pd.to_datetime(df_supports["Date d'import"], dayfirst=True, errors='coerce')
            df_supports['Last seen'] = last_seen.fillna(fallback_date)
        else:
            df_supports['Last seen'] = fallback_date

        rows.append(df_supports[['Support', 'Last seen']])

    if not rows:
        return pd.DataFrame(columns=['Support', 'Last seen'])

    merged = pd.concat(rows, ignore_index=True)
    merged = merged.dropna(subset=['Support'])
    merged = merged.groupby('Support', as_index=False)['Last seen'].max()
    merged = merged.sort_values('Last seen', ascending=False)
    return merged


@st.cache_data(show_spinner=False)
def _load_historical_structured_products(target_supports: tuple[str, ...]) -> pd.DataFrame:
    if not target_supports:
        return pd.DataFrame()

    target_supports_norm = {
        _normalize_support_name(s)
        for s in target_supports
        if _normalize_support_name(s)
    }
    if not target_supports_norm:
        return pd.DataFrame()

    if not HISTORICAL_EXPORTS_DIR.exists():
        return pd.DataFrame()

    files = sorted(HISTORICAL_EXPORTS_DIR.glob("*.csv"))
    files = [f for f in files if "situations_detaillees" in f.name.lower()]
    if not files:
        return pd.DataFrame()

    chunks = []
    for file_path in files:
        try:
            keep_cols = {
                'Support',
                'Numéro contrat',
                'Encours en €',
                '+/- value (en €)',
                '+/- value (en %))',
                "Date d'import",
                'Titulaire(s)',
                'Nom',
                'Prénom',
                'Type',
            }
            df_hist = pd.read_csv(
                file_path,
                header=0,
                sep=';',
                decimal=',',
                thousands=' ',
                usecols=lambda c: c in keep_cols,
            )
        except Exception:
            continue

        required = {'Support', 'Numéro contrat', 'Encours en €'}
        if not required.issubset(set(df_hist.columns)):
            continue

        df_hist['Support'] = df_hist['Support'].astype(str).str.strip()
        df_hist['_support_match_key'] = df_hist['Support'].map(_normalize_support_name)
        mask_struct = df_hist['_support_match_key'].isin(target_supports_norm)
        df_hist = df_hist.loc[mask_struct].copy()
        if df_hist.empty:
            continue

        df_hist['Numéro contrat'] = _normalize_contract_number(df_hist['Numéro contrat'])

        if "Titulaire(s)" not in df_hist.columns and {'Nom', 'Prénom'}.issubset(set(df_hist.columns)):
            df_hist['Titulaire(s)'] = df_hist[['Nom', 'Prénom']].fillna('').agg(' '.join, axis=1).str.strip()

        if 'Date d\'import' in df_hist.columns:
            date_snapshot = pd.to_datetime(df_hist["Date d'import"], dayfirst=True, errors='coerce')
        else:
            date_snapshot = pd.Series(pd.NaT, index=df_hist.index)

        fallback_date = _extract_export_date_from_filename(file_path.name)
        df_hist['Date dernière valorisation'] = date_snapshot.fillna(fallback_date)
        df_hist['Statut PS'] = 'Cloture (historique)'
        df_hist['for_count'] = 1

        chunks.append(df_hist)

    if not chunks:
        return pd.DataFrame()

    df_all = pd.concat(chunks, ignore_index=True)
    df_all = df_all.drop(columns=['_support_match_key'], errors='ignore')
    df_all['Encours en €'] = pd.to_numeric(df_all['Encours en €'], errors='coerce').fillna(0)
    if '+/- value (en €)' in df_all.columns:
        df_all['+/- value (en €)'] = pd.to_numeric(df_all['+/- value (en €)'], errors='coerce').fillna(0)
    else:
        df_all['+/- value (en €)'] = 0
    if '+/- value (en %))' in df_all.columns:
        df_all['+/- value (en %))'] = (
            df_all['+/- value (en %))'].astype(str).str.replace(',', '.').str.strip()
        )
        df_all['+/- value (en %))'] = pd.to_numeric(df_all['+/- value (en %))'], errors='coerce').fillna(0)
    else:
        df_all['+/- value (en %))'] = 0
    return df_all


def _enrich_contract_name(df_alloc: pd.DataFrame, df_contrats: pd.DataFrame) -> pd.DataFrame:
    if df_alloc.empty or df_contrats.empty:
        return df_alloc

    alloc = df_alloc.copy()
    contrats = df_contrats.copy()

    if 'Numéro contrat' in alloc.columns:
        alloc['_contract_key'] = alloc['Numéro contrat'].astype(str).str.strip()
    elif 'N° de contrat' in alloc.columns:
        alloc['_contract_key'] = alloc['N° de contrat'].astype(str).str.strip()
    else:
        return alloc

    contrat_num_col = None
    if 'N° de contrat' in contrats.columns:
        contrat_num_col = 'N° de contrat'
    elif 'Numéro contrat' in contrats.columns:
        contrat_num_col = 'Numéro contrat'

    if not contrat_num_col or 'Contrat' not in contrats.columns:
        return alloc

    lookup = contrats[[contrat_num_col, 'Contrat']].copy()
    lookup['_contract_key'] = lookup[contrat_num_col].astype(str).str.strip()
    lookup = lookup.dropna(subset=['_contract_key']).drop_duplicates(subset=['_contract_key'], keep='first')
    lookup = lookup.rename(columns={'Contrat': 'Contrat_lookup'})

    alloc = alloc.merge(lookup[['_contract_key', 'Contrat_lookup']], on='_contract_key', how='left')

    if 'Contrat' not in alloc.columns:
        alloc['Contrat'] = alloc['Contrat_lookup']
    else:
        contrat_local = alloc['Contrat'].astype(str).str.strip()
        alloc['Contrat'] = alloc['Contrat'].where(
            contrat_local.ne('') & contrat_local.ne('nan'),
            alloc['Contrat_lookup'],
        )

    alloc = alloc.drop(columns=['Contrat_lookup'], errors='ignore')
    return alloc

df_prod_struct = df_allocations[df_allocations['Support'].str.contains(
    'excel', case=False)]
df_prod_struct = df_prod_struct.copy()
df_prod_struct['Statut PS'] = 'En cours'
df_prod_struct['Date dernière valorisation'] = pd.NaT
df_prod_struct['for_count'] = 1

include_closed = st.checkbox(
    "Inclure les produits structures clotures (historiques)",
    value=False,
    help="Ajoute les produits structures absents du fichier courant en prenant leur derniere valorisation connue dans les exports historiques.",
)

if include_closed:
    support_options_current = sorted(
        df_allocations_all.loc[
            df_allocations_all['Support'].astype(str).str.contains('excel', case=False, na=False),
            'Support',
        ]
        .astype(str)
        .str.strip()
        .dropna()
        .unique()
        .tolist()
    ) if 'Support' in df_allocations_all.columns else []

    current_norm = {_normalize_support_name(x) for x in support_options_current if _normalize_support_name(x)}

    support_hist_last = _load_historical_structured_support_last_seen()
    if not support_hist_last.empty:
        support_hist_last = support_hist_last.copy()
        support_hist_last['_support_norm'] = support_hist_last['Support'].map(_normalize_support_name)
        support_hist_last = support_hist_last[~support_hist_last['_support_norm'].isin(current_norm)]
        support_hist_last = support_hist_last.sort_values('Last seen', ascending=False)
        support_options = support_hist_last['Support'].tolist()
    else:
        support_options = []

    selected_supports_hist = st.multiselect(
        "Produits a rechercher dans l'historique",
        options=support_options,
        default=[],
        help="Produits absents du dernier export, tries du plus recent au plus ancien.",
    )

    if selected_supports_hist:
        df_hist_struct = _load_historical_structured_products(tuple(selected_supports_hist))
        if not df_hist_struct.empty and allowed_contracts and 'Numéro contrat' in df_hist_struct.columns:
            df_hist_struct = df_hist_struct[
                df_hist_struct['Numéro contrat'].astype(str).str.strip().isin(allowed_contracts)
            ].copy()
        if not df_hist_struct.empty:
            current_keys = set(
                df_prod_struct[['Numéro contrat', 'Support']]
                .astype(str)
                .apply(lambda x: (x['Numéro contrat'].strip(), x['Support'].strip()), axis=1)
                .tolist()
            ) if {'Numéro contrat', 'Support'}.issubset(set(df_prod_struct.columns)) else set()

            if {'Numéro contrat', 'Support', 'Date dernière valorisation'}.issubset(set(df_hist_struct.columns)):
                df_hist_last = (
                    df_hist_struct.sort_values('Date dernière valorisation')
                    .groupby(['Numéro contrat', 'Support'], as_index=False)
                    .tail(1)
                )
                hist_keys = df_hist_last[['Numéro contrat', 'Support']].astype(str).apply(
                    lambda x: (x['Numéro contrat'].strip(), x['Support'].strip()), axis=1
                )
                mask_closed = ~hist_keys.isin(current_keys)
                df_closed = df_hist_last.loc[mask_closed].copy()
                if not df_closed.empty:
                    df_prod_struct = pd.concat([df_prod_struct, df_closed], ignore_index=True, sort=False)
                    st.caption(f"{len(df_closed)} produit(s) structure(s) cloture(s) ajoute(s) depuis l'historique.")
    else:
        st.info("Selectionnez au moins un produit dans la liste pour lancer la recherche historique.")
#st.dataframe(df_prod_struct)

fig_pie_PS_nombre = px.pie(df_prod_struct,
                            values='for_count', names='Support', hole=.5)
fig_pie_PS_nombre.update_layout(
    title="Ventilation Produit structuré par nombre")
fig_pie_PS_nombre.update_traces(
    hoverinfo='label+percent', textinfo='value')

fig_pie_PS_encours = px.pie(df_prod_struct,
                            values='Encours en €', names='Support', hole=.5)
fig_pie_PS_encours.update_layout(
    title="Ventilation Produit structuré par encours")
fig_pie_PS_encours.update_traces(
    hoverinfo='label+percent', textinfo='value')

col_PS_nombre, col_PS_encours = st.columns(2)

col_PS_nombre.plotly_chart(fig_pie_PS_nombre)
col_PS_encours.plotly_chart(fig_pie_PS_encours)

df_summary_prod_struct = df_prod_struct[['Support',
                                            'Encours en €',
                                            '+/- value (en €)',
                                            '+/- value (en %))']].groupby(['Support']).agg({'Encours en €': ['count', 'sum', 'max'],
                                                                                        '+/- value (en €)': ['sum'],
                                                                                            '+/- value (en %))': ['mean']})
df_summary_prod_struct.columns = [
    ' '.join(str(i) for i in col) for col in df_summary_prod_struct.columns]
df_summary_prod_struct.reset_index(inplace=True)

# Tableau interactif avec sélection
st.subheader("Résumé des produits structurés")

# Ajouter une colonne de sélection
df_with_selection = df_summary_prod_struct.copy()
df_with_selection.insert(0, 'Sélectionner', False)

# Utiliser data_editor avec colonnes configurées
config = {
    'Sélectionner': st.column_config.CheckboxColumn(
        'Sélectionner',
        help="Cochez pour voir les contrats de ce support",
        default=False,
    )
}

edited_df = st.data_editor(
    df_with_selection,
    column_config=config,
    disabled=['Support', 'Encours en € count', 'Encours en € sum', 'Encours en € max', '+/- value (en €) sum', '+/- value (en %)) mean'],
    hide_index=True,
    use_container_width=True,
    key="prod_struct_selector"
)

# Récupérer les lignes sélectionnées
selected_supports = edited_df[edited_df['Sélectionner'] == True]['Support'].tolist()

if selected_supports:
    st.subheader("Contrats concernés")

    # Filtrer les données pour les supports sélectionnés
    df_contrats_concernes = df_prod_struct[df_prod_struct['Support'].isin(selected_supports)]
    df_contrats_concernes = _enrich_contract_name(df_contrats_concernes, df_contrats_ref)

    # Afficher les colonnes pertinentes pour les contrats (avec nom et numero de contrat)
    colonnes_contrats = [
        'Titulaire(s)',
        'Type',
        'Statut PS',
        'Date dernière valorisation',
        'Contrat',
        'Numéro contrat',
        'N° de contrat',
        'Support',
        'Encours en €',
        '+/- value (en €)',
        '+/- value (en %))',
    ]
    # Vérifier que les colonnes existent dans le DataFrame
    colonnes_disponibles = [col for col in colonnes_contrats if col in df_contrats_concernes.columns]

    if colonnes_disponibles:
        df_contrats_affichage = df_contrats_concernes[colonnes_disponibles].copy()

        if 'Numéro contrat' in df_contrats_affichage.columns and 'N° de contrat' in df_contrats_affichage.columns:
            # Eviter le doublon si les deux colonnes existent simultanement.
            df_contrats_affichage = df_contrats_affichage.drop(columns=['N° de contrat'])
            
        # Trier par encours décroissant
        if 'Encours en €' in df_contrats_affichage.columns:
            df_contrats_affichage = df_contrats_affichage.sort_values('Encours en €', ascending=False)

        st.dataframe(
            df_contrats_affichage,
            hide_index=True,
            use_container_width=True
        )

        try:
            excel_bytes = _build_excel_bytes(df_contrats_affichage)
            st.download_button(
                "Exporter en Excel",
                data=excel_bytes,
                file_name="produits_structures_contrats.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as exc:
            st.warning(f"Export Excel indisponible: {exc}")
            
        # Afficher quelques statistiques
        nb_contrats = len(df_contrats_affichage)
        encours_total = df_contrats_affichage['Encours en €'].sum() if 'Encours en €' in df_contrats_affichage.columns else 0

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Nombre de contrats", nb_contrats)
        with col2:
            st.metric("Encours total", f"{encours_total:,.0f} €")
        with col3:
            # Compter les types de contrats
            if 'Type' in df_contrats_affichage.columns:
                types_contrats = df_contrats_affichage['Type'].value_counts()
                types_str = " | ".join([f"{k}: {v}" for k, v in types_contrats.items()])
                st.metric("Répartition AV/PER", types_str)
    else:
        st.warning("Les colonnes de contrat ne sont pas disponibles dans les données")
else:
    st.info("Sélectionnez une ou plusieurs lignes dans le tableau ci-dessus pour voir les contrats concernés")
