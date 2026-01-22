import streamlit as st
from streamlit import session_state as ss
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import os
import glob

st.title("📈 Performance historique des fonds")

# Répertoire des fichiers de performance
fonds_dir = "/Users/jean-philippenavarro/Documents/10_CGP/20_Outils - Simulateurs/01_Suivi_AV_PER/00_Exports/3_Fonds"

# Chercher tous les fichiers CSV qui contiennent "Top" dans leur nom
try:
    top_files = glob.glob(os.path.join(fonds_dir, "*Top*.csv"))
except Exception:
    top_files = []

if not top_files:
    st.warning("⚠️ Aucun fichier de performance trouvé dans le répertoire 00_Exports/3_Fonds")
    st.stop()

# Sélection du fichier si plusieurs disponibles
if len(top_files) > 1:
    selected_file = st.selectbox(
        "Sélectionnez le fichier de performance",
        options=top_files,
        format_func=lambda x: os.path.basename(x)
    )
else:
    selected_file = top_files[0]
    st.info(f"📄 Fichier chargé : {os.path.basename(selected_file)}")

# Charger les données (gérer encodage FR)
try:
    df_perfs = pd.read_csv(selected_file, sep=';', decimal=',', encoding='latin-1')
except UnicodeDecodeError:
    # Fallback éventuel
    df_perfs = pd.read_csv(selected_file, sep=';', decimal=',', encoding='utf-8', errors='ignore')

# Nettoyage et conversions
# Date
df_perfs['Date'] = pd.to_datetime(df_perfs['Date'], format='%d/%m/%Y', errors='coerce')
# Rendement
if df_perfs['Rendement'].dtype == 'object':
    df_perfs['Rendement'] = (
        df_perfs['Rendement'].astype(str).str.replace(',', '.').astype(float)
    )

# Trier par date
df_perfs = df_perfs.sort_values('Date')
# Conserver une copie complète pour d'autres modes de sélection
df_perfs_all = df_perfs.copy()

# Informations générales
fonds_disponibles = sorted(df_perfs_all['Nom'].dropna().unique())
nb_fonds = len(fonds_disponibles)

st.success(
    f"✅ Données chargées : {len(df_perfs_all):,} lignes ({nb_fonds} fonds), du "
    f"{df_perfs_all['Date'].min().strftime('%d/%m/%Y')} au {df_perfs_all['Date'].max().strftime('%d/%m/%Y')}"
)

# Mettre les onglets TOUT EN HAUT et piloter tout l'affichage par onglet
tab_man, tab_auto, tab_contrat = st.tabs(["Sélection manuelle", "Sélection auto (Top N)", "Par contrat"])

# Paramètres généraux communs
min_date = df_perfs_all['Date'].min().date()
max_date = df_perfs_all['Date'].max().date()
default_start_global = (df_perfs_all['Date'].max() - pd.DateOffset(years=1)).date()
if default_start_global < min_date:
    default_start_global = min_date

# Onglet 1: Sélection manuelle (Performance base 100)
with tab_man:
    st.header("Configuration de la période d'analyse")
    col_date1, col_date2 = st.columns(2)
    with col_date1:
        date_debut = st.date_input(
            "Date de début",
            value=default_start_global,
            min_value=min_date,
            max_value=max_date,
            help="Sélectionnez la date de début de la période d'analyse (base 100)",
            key="date_debut_man"
        )
    with col_date2:
        date_fin = st.date_input(
            "Date de fin",
            value=max_date,
            min_value=min_date,
            max_value=max_date,
            help="Sélectionnez la date de fin de la période d'analyse",
            key="date_fin_man"
        )

    if date_debut >= date_fin:
        st.error("❌ La date de début doit être antérieure à la date de fin")
        st.stop()

    # Filtres Enveloppe / Partenaire pour restreindre les fonds disponibles
    st.header("Filtres d'allocations")
    df_alloc = ss.get('df_allocations', pd.DataFrame())
    df_contrats = ss.get('df_contrats', pd.DataFrame())
    df_alloc_filt = df_alloc.copy()
    colMF1, colMF2 = st.columns(2)
    if not df_contrats.empty and 'Enveloppe' in df_contrats.columns and 'Partenaire' in df_contrats.columns:
        with colMF1:
            enveloppes = sorted(df_contrats['Enveloppe'].dropna().unique())
            env_sel_m = st.multiselect(
                "Enveloppe(s)", options=enveloppes, default=enveloppes,
                help="Filtre les contrats par enveloppe", key="env_sel_man"
            )
        # Partenaires dépendants des enveloppes sélectionnées
        contrats_env_m = df_contrats[df_contrats['Enveloppe'].isin(env_sel_m)] if env_sel_m else df_contrats.copy()
        with colMF2:
            partenaires = sorted(contrats_env_m['Partenaire'].dropna().unique())
            part_sel_m = st.multiselect(
                "Partenaire(s)", options=partenaires, default=partenaires,
                help="Filtre les contrats par partenaire", key="part_sel_man"
            )
        contrats_filt = contrats_env_m[contrats_env_m['Partenaire'].isin(part_sel_m)] if part_sel_m else contrats_env_m
        numeros = contrats_filt['N° de contrat'].unique() if 'N° de contrat' in contrats_filt.columns else []
        if len(numeros) > 0 and 'Numéro contrat' in df_alloc.columns:
            df_alloc_filt = df_alloc[df_alloc['Numéro contrat'].isin(numeros)]
    else:
        # Fallback si df_contrats absent
        with colMF1:
            env_opts = sorted(df_alloc['Enveloppe'].dropna().unique()) if 'Enveloppe' in df_alloc.columns else []
            env_sel_m = st.multiselect("Enveloppe", options=env_opts, default=env_opts, key="env_sel_man_fb") if env_opts else []
        # Partenaires dépendants des enveloppes choisies
        alloc_env_m = df_alloc[df_alloc['Enveloppe'].isin(env_sel_m)] if (env_sel_m and 'Enveloppe' in df_alloc.columns) else df_alloc.copy()
        with colMF2:
            part_opts = sorted(alloc_env_m['Partenaire'].dropna().unique()) if 'Partenaire' in alloc_env_m.columns else []
            part_sel_m = st.multiselect("Partenaire", options=part_opts, default=part_opts, key="part_sel_man_fb") if part_opts else []
        df_alloc_filt = alloc_env_m
        if part_sel_m and 'Partenaire' in df_alloc_filt.columns:
            df_alloc_filt = df_alloc_filt[df_alloc_filt['Partenaire'].isin(part_sel_m)]

    # Filtre par type de fonds (avant le filtrage par noms)
    st.header("Filtre par type de fonds (graphique)")
    types_dispo_m = sorted([t for t in df_alloc_filt['Type'].dropna().unique()]) if 'Type' in df_alloc_filt.columns else []
    types_sel_m = st.multiselect(
        "Type de fonds",
        options=types_dispo_m,
        default=types_dispo_m,
        help="Applique un filtre sur le type avant de choisir les fonds",
        key="type_sel_man"
    ) if types_dispo_m else []

    map_isin_type_m = {}
    if 'Code ISIN' in df_alloc_filt.columns and 'Type' in df_alloc_filt.columns:
        map_isin_type_m = df_alloc_filt[['Code ISIN','Type']].dropna().drop_duplicates().set_index('Code ISIN')['Type'].to_dict()

    # Restreindre la liste des fonds selon les allocations filtrées
    perfs_isin_nom = df_perfs_all[['Code ISIN','Nom']].dropna(subset=['Code ISIN']).drop_duplicates()
    isins_autorises = set(df_alloc_filt['Code ISIN'].dropna().unique()) if 'Code ISIN' in df_alloc_filt.columns else set()
    if types_sel_m:
        isins_autorises = {i for i in isins_autorises if map_isin_type_m.get(i) in types_sel_m}
    if isins_autorises:
        fonds_autorises = sorted(perfs_isin_nom[perfs_isin_nom['Code ISIN'].isin(isins_autorises)]['Nom'].unique())
    else:
        fonds_autorises = fonds_disponibles

    st.header("Sélection des fonds")
    default_selection = ['Portefeuille'] if 'Portefeuille' in fonds_autorises else (fonds_autorises[:1] if len(fonds_autorises)>0 else [])
    fonds_selectionnes = st.multiselect(
        "Fonds à afficher",
        options=fonds_autorises,
        default=default_selection,
        help="Sélectionnez un ou plusieurs fonds pour comparer leurs performances",
        key="fonds_selectionnes_man"
    )
    if not fonds_selectionnes:
        st.warning("⚠️ Veuillez sélectionner au moins un fonds")
        st.stop()

    # Filtrer selon la période et fonds
    df_periode = df_perfs_all[
        (df_perfs_all['Nom'].isin(fonds_selectionnes)) &
        (df_perfs_all['Date'] >= pd.to_datetime(date_debut)) &
        (df_perfs_all['Date'] <= pd.to_datetime(date_fin))
    ].copy()
    if df_periode.empty:
        st.warning("⚠️ Aucune donnée disponible pour la période sélectionnée")
        st.stop()

    # Calcul base 100 par fonds
    performances_fonds = []
    for fonds in fonds_selectionnes:
        df_fonds = df_periode[df_periode['Nom'] == fonds].copy()
        if df_fonds.empty:
            continue
        df_fonds['Valeur_cumul'] = (1 + df_fonds['Rendement']).cumprod()
        valeur_initiale = df_fonds['Valeur_cumul'].iloc[0]
        df_fonds['Performance_base_100'] = (df_fonds['Valeur_cumul'] / valeur_initiale) * 100
        df_fonds['Nom_fonds'] = fonds
        performances_fonds.append(df_fonds)

    df_all_perfs = pd.concat(performances_fonds, ignore_index=True)

    # Statistiques par fonds
    st.header("Statistiques de la période")
    for fonds in fonds_selectionnes:
        df_fonds = df_all_perfs[df_all_perfs['Nom_fonds'] == fonds]
        if df_fonds.empty:
            continue
        st.subheader(fonds)
        col1, col2, col3, col4 = st.columns(4)
        performance_totale = df_fonds['Performance_base_100'].iloc[-1] - 100
        nb_jours = (date_fin - date_debut).days
        rendement_annualise = ((df_fonds['Performance_base_100'].iloc[-1] / 100) ** (365 / nb_jours) - 1) * 100 if nb_jours > 0 else 0
        volatilite = df_fonds['Rendement'].std() * np.sqrt(252) * 100
        with col1:
            st.metric("Performance totale", f"{performance_totale:.2f}%")
        with col2:
            st.metric("Rendement annualisé", f"{rendement_annualise:.2f}%")
        with col3:
            st.metric("Volatilité annualisée", f"{volatilite:.2f}%")
        with col4:
            st.metric("Nombre de jours", f"{len(df_fonds)}")

    st.header("Graphiques")
    fig = go.Figure()
    colors = px.colors.qualitative.Plotly
    for i, fonds in enumerate(fonds_selectionnes):
        df_fonds = df_all_perfs[df_all_perfs['Nom_fonds'] == fonds]
        fig.add_trace(go.Scatter(
            x=df_fonds['Date'],
            y=df_fonds['Performance_base_100'],
            mode='lines',
            name=fonds,
            line=dict(color=colors[i % len(colors)], width=2),
            hovertemplate='<b>%{x|%d/%m/%Y}</b><br>Performance: %{y:.2f}<extra></extra>'
        ))
    fig.add_hline(y=100, line_dash="dash", line_color="gray", annotation_text="Base 100", annotation_position="right")
    fig.update_layout(title=f"Performance (base 100 au {date_debut.strftime('%d/%m/%Y')})", xaxis_title="Date", yaxis_title="Performance (base 100)", hovermode='x unified', height=500)
    st.plotly_chart(fig, use_container_width=True)

    # Graphique rendement vs volatilité
    rendements_vola = []
    for fonds in fonds_selectionnes:
        df_fonds = df_all_perfs[df_all_perfs['Nom_fonds'] == fonds]
        if len(df_fonds) > 0:
            nb_jours = len(df_fonds)
            perf_base = df_fonds['Performance_base_100'].iloc[-1]
            rendement_annualise = ((perf_base / 100) ** (365 / nb_jours) - 1) * 100 if nb_jours > 0 else 0
            volatilite_annualisee = df_fonds['Rendement'].std() * np.sqrt(252) * 100
            rendements_vola.append({
                'Fonds': fonds,
                'Rendement': rendement_annualise,
                'Volatilité': volatilite_annualisee
            })
    
    if rendements_vola:
        df_rendement_vola = pd.DataFrame(rendements_vola)
        fig_scatter = go.Figure()
        colors = px.colors.qualitative.Plotly
        for i, row in df_rendement_vola.iterrows():
            fig_scatter.add_trace(go.Scatter(
                x=[row['Volatilité']],
                y=[row['Rendement']],
                mode='markers+text',
                name=row['Fonds'],
                text=[row['Fonds']],
                textposition='top center',
                marker=dict(size=15, color=colors[i % len(colors)]),
                hovertemplate='<b>%{text}</b><br>Volatilité: %{x:.2f}%<br>Rendement annualisé: %{y:.2f}%<extra></extra>'
            ))
        fig_scatter.update_layout(
            title="Rendement vs Volatilité (annualisés)",
            xaxis_title="Volatilité annualisée (%)",
            yaxis_title="Rendement annualisé (%)",
            hovermode='closest',
            height=500,
            showlegend=False
        )
        st.plotly_chart(fig_scatter, use_container_width=True)

    # Données détaillées (manuel)
    with st.expander("📊 Voir les données de la courbe (sélection manuelle)"):
        df_display = df_all_perfs[['Date', 'Nom_fonds', 'Rendement', 'Performance_base_100']].copy()
        df_display['Date'] = df_display['Date'].dt.strftime('%d/%m/%Y')
        df_display.columns = ['Date', 'Fonds', 'Rendement quotidien', 'Performance (base 100)']
        st.dataframe(
            df_display,
            column_config={
                "Date": "Date",
                "Fonds": "Fonds",
                "Rendement quotidien": st.column_config.NumberColumn("Rendement quotidien", format="%.4f"),
                "Performance (base 100)": st.column_config.NumberColumn("Performance (base 100)", format="%.2f")
            },
            hide_index=True,
            use_container_width=True
        )

    # Export (manuel)
    with st.expander("📥 Télécharger les données (sélection manuelle)"):
        df_export = df_display.copy()
        csv = df_export.to_csv(index=False, sep=';', decimal=',')
        st.download_button(
            label="💾 Télécharger les données (CSV)",
            data=csv,
            file_name=f"performance_{date_debut.strftime('%Y%m%d')}_{date_fin.strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )

# Onglet 2: Sélection auto (Top N)
with tab_auto:
    st.header("Configuration de la période d'analyse")
    col_date1a, col_date2a = st.columns(2)
    with col_date1a:
        date_debut_a = st.date_input(
            "Date de début",
            value=default_start_global,
            min_value=min_date,
            max_value=max_date,
            help="Sélectionnez la date de début de la période d'analyse (base 100)",
            key="date_debut_auto"
        )
    with col_date2a:
        date_fin_a = st.date_input(
            "Date de fin",
            value=max_date,
            min_value=min_date,
            max_value=max_date,
            help="Sélectionnez la date de fin de la période d'analyse",
            key="date_fin_auto"
        )

    if date_debut_a >= date_fin_a:
        st.error("❌ La date de début doit être antérieure à la date de fin")
        st.stop()

    df_alloc = ss.get('df_allocations', pd.DataFrame())
    df_contrats = ss.get('df_contrats', pd.DataFrame())
    if df_alloc.empty:
        st.info("ℹ️ Données d'allocations indisponibles (sélection auto). Retournez sur 'Données' pour charger les fichiers.")
    else:
        # Filtres Enveloppe / Partenaire AVANT le Top N (comme page Fonds du portefeuille)
        st.header("Filtres d'allocations")
        colF1, colF2 = st.columns(2)
        if not df_contrats.empty and 'Enveloppe' in df_contrats.columns and 'Partenaire' in df_contrats.columns:
            with colF1:
                enveloppes = sorted(df_contrats['Enveloppe'].dropna().unique())
                env_sel = st.multiselect(
                    "Enveloppe(s)",
                    options=enveloppes,
                    default=enveloppes,
                    help="Filtre les contrats par enveloppe"
                )
            # Partenaires dépendants des enveloppes choisies
            contrats_env = df_contrats[df_contrats['Enveloppe'].isin(env_sel)] if env_sel else df_contrats.copy()
            with colF2:
                partenaires_dep = sorted(contrats_env['Partenaire'].dropna().unique())
                part_sel = st.multiselect(
                    "Partenaire(s)",
                    options=partenaires_dep,
                    default=partenaires_dep,
                    help="Filtre les contrats par partenaire"
                )

            contrats_filtres = contrats_env[contrats_env['Partenaire'].isin(part_sel)] if part_sel else contrats_env
            numeros_contrats = contrats_filtres['N° de contrat'].unique() if 'N° de contrat' in contrats_filtres.columns else []
            df_alloc_filt = df_alloc[df_alloc['Numéro contrat'].isin(numeros_contrats)] if len(numeros_contrats) > 0 else df_alloc.copy()
        else:
            # Fallback: pas de df_contrats, filtrer directement si colonnes existent dans allocations
            with colF1:
                enveloppes = sorted([e for e in df_alloc['Enveloppe'].dropna().unique()]) if 'Enveloppe' in df_alloc.columns else []
                env_sel = st.multiselect("Enveloppe", options=enveloppes, default=enveloppes) if enveloppes else []
            # Partenaires dépendants des enveloppes choisies
            alloc_env = df_alloc[df_alloc['Enveloppe'].isin(env_sel)] if (env_sel and 'Enveloppe' in df_alloc.columns) else df_alloc.copy()
            with colF2:
                partenaires = sorted([p for p in alloc_env['Partenaire'].dropna().unique()]) if 'Partenaire' in alloc_env.columns else []
                part_sel = st.multiselect("Partenaire", options=partenaires, default=partenaires) if partenaires else []
            df_alloc_filt = alloc_env
            if part_sel:
                df_alloc_filt = df_alloc_filt[df_alloc_filt['Partenaire'].isin(part_sel)]

        colA, colB = st.columns([1,1])
        with colA:
            critere_classement = st.radio(
                "Critère de classement des fonds",
                options=["Nombre d'utilisations", "Encours total"],
                index=0,
                help="Classement basé sur les allocations courantes"
            )
        with colB:
            n_fonds = st.number_input(
                "Nombre de fonds à afficher séparément",
                min_value=1,
                max_value=50,
                value=10
            )

        # Calcul des top N sur les allocations
        fonds_stats = df_alloc_filt.groupby(['Support', 'Code ISIN']).agg({
            'Numéro contrat': 'count',
            'Encours en €': 'sum'
        }).reset_index()
        fonds_stats.rename(columns={'Numéro contrat': 'Nb_utilisations'}, inplace=True)

        if critere_classement == "Nombre d'utilisations":
            fonds_stats = fonds_stats.sort_values('Nb_utilisations', ascending=False)
            critere_colonne = 'Nb_utilisations'
        else:
            fonds_stats = fonds_stats.sort_values('Encours en €', ascending=False)
            critere_colonne = 'Encours en €'

        top_n = fonds_stats.head(int(n_fonds)).copy()
        isins_top = set(top_n['Code ISIN'].dropna().unique())

        # Mapping ISIN -> Nom depuis le fichier de perfs
        map_isin_nom = (df_perfs_all[['Code ISIN','Nom']]
                        .dropna(subset=['Code ISIN'])
                        .drop_duplicates()
                        .set_index('Code ISIN')['Nom'])

        # Filtrage par type de fonds pour le graphique (avant le filtrage par noms)
        st.header("Filtre par type de fonds (graphique)")
        types_dispo = sorted([t for t in df_alloc_filt['Type'].dropna().unique()]) if 'Type' in df_alloc_filt.columns else []
        types_sel = st.multiselect(
            "Type de fonds",
            options=types_dispo,
            default=types_dispo,
            help="Applique un filtre sur le type avant de tracer les courbes"
        ) if types_dispo else []

        # Construire un mapping ISIN -> Type depuis allocations filtrées
        map_isin_type = {}
        if 'Code ISIN' in df_alloc_filt.columns and 'Type' in df_alloc_filt.columns:
            map_isin_type = df_alloc_filt[['Code ISIN','Type']].dropna().drop_duplicates().set_index('Code ISIN')['Type'].to_dict()

        # Appliquer filtre type sur ISINs top
        if types_sel:
            isins_top = {i for i in isins_top if map_isin_type.get(i) in types_sel}

        isins_disponibles = [i for i in isins_top if i in set(df_perfs_all['Code ISIN'].dropna().unique())]
        noms_auto = [map_isin_nom[i] for i in isins_disponibles if i in map_isin_nom]

        manquants = isins_top.difference(isins_disponibles)
        if manquants:
            st.warning(f"{len(manquants)} fonds sélectionnés ne disposent pas d'historique dans le fichier: {', '.join(list(manquants)[:5])}{'…' if len(manquants)>5 else ''}")

        if len(noms_auto) == 0:
            st.warning("⚠️ Aucun des fonds top N n'est présent dans le fichier de performances.")
        else:
            # Préparer les séries pour ces fonds
            df_auto_sel = df_perfs_all[df_perfs_all['Code ISIN'].isin(isins_disponibles)]
            df_auto_periode = df_auto_sel[(df_auto_sel['Date'] >= pd.to_datetime(date_debut_a)) & (df_auto_sel['Date'] <= pd.to_datetime(date_fin_a))].copy()

            perf_auto_list = []
            for isin in isins_disponibles:
                df_f = df_auto_periode[df_auto_periode['Code ISIN'] == isin].copy()
                if df_f.empty:
                    continue
                df_f['Valeur_cumul'] = (1 + df_f['Rendement']).cumprod()
                base = df_f['Valeur_cumul'].iloc[0]
                df_f['Performance_base_100'] = (df_f['Valeur_cumul'] / base) * 100
                df_f['Nom_fonds'] = map_isin_nom.get(isin, isin)
                perf_auto_list.append(df_f)

            if len(perf_auto_list) == 0:
                st.warning("⚠️ Aucune donnée disponible sur la période pour les fonds top N.")
            else:
                df_all_perfs_auto = pd.concat(perf_auto_list, ignore_index=True)
                fig_auto = go.Figure()
                colors = px.colors.qualitative.T10
                for i, name in enumerate(df_all_perfs_auto['Nom_fonds'].unique()):
                    d = df_all_perfs_auto[df_all_perfs_auto['Nom_fonds'] == name]
                    fig_auto.add_trace(go.Scatter(
                        x=d['Date'], y=d['Performance_base_100'], mode='lines', name=name,
                        line=dict(color=colors[i % len(colors)], width=2),
                        hovertemplate='<b>%{x|%d/%m/%Y}</b><br>Performance: %{y:.2f}<extra></extra>'
                    ))
                fig_auto.add_hline(y=100, line_dash='dash', line_color='gray', annotation_text='Base 100', annotation_position='right')
                titre = f"Top {int(n_fonds)} par {critere_colonne.lower()} (base 100 au {date_debut_a.strftime('%d/%m/%Y')})"
                fig_auto.update_layout(title=titre, xaxis_title='Date', yaxis_title='Performance (base 100)', hovermode='x unified', height=500)
                st.plotly_chart(fig_auto, use_container_width=True)

                # Graphique rendement vs volatilité (auto)
                rendements_vola_a = []
                for name in df_all_perfs_auto['Nom_fonds'].unique():
                    dff = df_all_perfs_auto[df_all_perfs_auto['Nom_fonds'] == name]
                    if len(dff) > 0:
                        nb_j = len(dff)
                        perf_b = dff['Performance_base_100'].iloc[-1]
                        rend_a = ((perf_b / 100) ** (365 / nb_j) - 1) * 100 if nb_j > 0 else 0
                        vola_a = dff['Rendement'].std() * np.sqrt(252) * 100
                        rendements_vola_a.append({
                            'Fonds': name,
                            'Rendement': rend_a,
                            'Volatilité': vola_a
                        })
                
                if rendements_vola_a:
                    df_rend_vola_a = pd.DataFrame(rendements_vola_a)
                    fig_scatter_a = go.Figure()
                    colors_a = px.colors.qualitative.T10
                    for i, row in df_rend_vola_a.iterrows():
                        fig_scatter_a.add_trace(go.Scatter(
                            x=[row['Volatilité']],
                            y=[row['Rendement']],
                            mode='markers+text',
                            name=row['Fonds'],
                            text=[row['Fonds']],
                            textposition='top center',
                            marker=dict(size=15, color=colors_a[i % len(colors_a)]),
                            hovertemplate='<b>%{text}</b><br>Volatilité: %{x:.2f}%<br>Rendement annualisé: %{y:.2f}%<extra></extra>'
                        ))
                    fig_scatter_a.update_layout(
                        title="Rendement vs Volatilité (annualisés)",
                        xaxis_title="Volatilité annualisée (%)",
                        yaxis_title="Rendement annualisé (%)",
                        hovermode='closest',
                        height=500,
                        showlegend=False
                    )
                    st.plotly_chart(fig_scatter_a, use_container_width=True)

                # Statistiques par fonds (auto)
                st.header("Statistiques de la période")
                for name in df_all_perfs_auto['Nom_fonds'].unique():
                    dff = df_all_perfs_auto[df_all_perfs_auto['Nom_fonds'] == name]
                    if dff.empty:
                        continue
                    st.subheader(name)
                    c1, c2, c3, c4 = st.columns(4)
                    perf_tot = dff['Performance_base_100'].iloc[-1] - 100
                    nb_j = (date_fin_a - date_debut_a).days
                    rend_ann = ((dff['Performance_base_100'].iloc[-1] / 100) ** (365 / nb_j) - 1) * 100 if nb_j > 0 else 0
                    vola = dff['Rendement'].std() * np.sqrt(252) * 100
                    with c1:
                        st.metric("Performance totale", f"{perf_tot:.2f}%")
                    with c2:
                        st.metric("Rendement annualisé", f"{rend_ann:.2f}%")
                    with c3:
                        st.metric("Volatilité annualisée", f"{vola:.2f}%")
                    with c4:
                        st.metric("Nombre de jours", f"{len(dff)}")

                with st.expander("📊 Voir les données de la courbe (sélection auto)"):
                    df_display_auto = df_all_perfs_auto[['Date','Nom_fonds','Rendement','Performance_base_100']].copy()
                    df_display_auto['Date'] = df_display_auto['Date'].dt.strftime('%d/%m/%Y')
                    df_display_auto.columns = ['Date','Fonds','Rendement quotidien','Performance (base 100)']
                    st.dataframe(df_display_auto, hide_index=True, use_container_width=True)

                with st.expander("📥 Télécharger les données (sélection auto)"):
                    csv_auto = df_display_auto.to_csv(index=False, sep=';', decimal=',')
                    st.download_button(
                        label="💾 Télécharger les données (CSV)",
                        data=csv_auto,
                        file_name=f"performance_auto_{date_debut_a.strftime('%Y%m%d')}_{date_fin_a.strftime('%Y%m%d')}.csv",
                        mime='text/csv'
                    )

# Onglet 3: Par contrat
with tab_contrat:
    df_alloc = ss.get('df_allocations', pd.DataFrame())
    df_contrats = ss.get('df_contrats', pd.DataFrame())
    if df_alloc.empty or df_contrats.empty:
        st.info("ℹ️ Données d'allocations/contrats indisponibles. Retournez sur 'Données' pour charger les fichiers.")
        st.stop()

    st.header("Filtres d'allocations")
    colC1, colC2, colC3 = st.columns([1,1,1])
    with colC1:
        env_opts_c = sorted(df_contrats['Enveloppe'].dropna().unique()) if 'Enveloppe' in df_contrats.columns else []
        env_sel_c = st.multiselect("Enveloppe(s)", options=env_opts_c, default=env_opts_c, key="env_sel_ctr")
    contrats_env_c = df_contrats[df_contrats['Enveloppe'].isin(env_sel_c)] if env_sel_c else df_contrats.copy()
    with colC2:
        part_opts_c = sorted(contrats_env_c['Partenaire'].dropna().unique()) if 'Partenaire' in contrats_env_c.columns else []
        part_sel_c = st.multiselect("Partenaire(s)", options=part_opts_c, default=part_opts_c, key="part_sel_ctr")
    contrats_filtrables = contrats_env_c[contrats_env_c['Partenaire'].isin(part_sel_c)] if part_sel_c else contrats_env_c

    with colC3:
        if 'N° de contrat' in contrats_filtrables.columns:
            options_contrats = sorted(contrats_filtrables['N° de contrat'].dropna().unique())
        else:
            options_contrats = []
        contrat_sel = st.selectbox("Contrat", options=options_contrats, index=0 if len(options_contrats)>0 else None, key="contrat_select")

    if not options_contrats:
        st.warning("⚠️ Aucun contrat disponible avec les filtres sélectionnés.")
        st.stop()

    # Sélection période
    st.header("Configuration de la période d'analyse")
    colD1, colD2 = st.columns(2)
    with colD1:
        date_debut_c = st.date_input(
            "Date de début",
            value=default_start_global,
            min_value=min_date,
            max_value=max_date,
            help="Sélectionnez la date de début (base 100)",
            key="date_debut_ctr"
        )
    with colD2:
        date_fin_c = st.date_input(
            "Date de fin",
            value=max_date,
            min_value=min_date,
            max_value=max_date,
            help="Sélectionnez la date de fin",
            key="date_fin_ctr"
        )

    if date_debut_c >= date_fin_c:
        st.error("❌ La date de début doit être antérieure à la date de fin")
        st.stop()

    # Récupérer les ISIN des fonds du contrat
    if 'Numéro contrat' in df_alloc.columns:
        fonds_contrat = df_alloc[df_alloc['Numéro contrat'] == contrat_sel]
    else:
        fonds_contrat = pd.DataFrame()

    if fonds_contrat.empty or 'Code ISIN' not in fonds_contrat.columns:
        st.warning("⚠️ Aucun fonds trouvé pour ce contrat.")
        st.stop()

    isins_contrat = set(fonds_contrat['Code ISIN'].dropna().unique())
    map_isin_nom = (df_perfs_all[['Code ISIN','Nom']]
                    .dropna(subset=['Code ISIN'])
                    .drop_duplicates()
                    .set_index('Code ISIN')['Nom'])

    isins_dispos_c = [i for i in isins_contrat if i in set(df_perfs_all['Code ISIN'].dropna().unique())]
    noms_c = [map_isin_nom.get(i, i) for i in isins_dispos_c]
    manquants_c = isins_contrat.difference(isins_dispos_c)
    if manquants_c:
        st.warning(f"{len(manquants_c)} fonds du contrat n'ont pas d'historique dans le fichier: {', '.join(list(manquants_c)[:5])}{'…' if len(manquants_c)>5 else ''}")

    if len(isins_dispos_c) == 0:
        st.warning("⚠️ Aucun des fonds du contrat n'est présent dans le fichier de performances.")
        st.stop()

    df_ctr_sel = df_perfs_all[df_perfs_all['Code ISIN'].isin(isins_dispos_c)]
    df_ctr_periode = df_ctr_sel[(df_ctr_sel['Date'] >= pd.to_datetime(date_debut_c)) & (df_ctr_sel['Date'] <= pd.to_datetime(date_fin_c))].copy()

    # Calculs base 100 par fonds du contrat
    perf_ctr_list = []
    for isin in isins_dispos_c:
        d = df_ctr_periode[df_ctr_periode['Code ISIN'] == isin].copy()
        if d.empty:
            continue
        d['Valeur_cumul'] = (1 + d['Rendement']).cumprod()
        base = d['Valeur_cumul'].iloc[0]
        d['Performance_base_100'] = (d['Valeur_cumul'] / base) * 100
        d['Nom_fonds'] = map_isin_nom.get(isin, isin)
        perf_ctr_list.append(d)

    if len(perf_ctr_list) == 0:
        st.warning("⚠️ Aucune donnée disponible pour la période sélectionnée.")
        st.stop()

    df_perfs_ctr = pd.concat(perf_ctr_list, ignore_index=True)

    # Graphique
    st.header("Graphiques")
    fig_c = go.Figure()
    colors = px.colors.qualitative.Set2
    for i, name in enumerate(sorted(df_perfs_ctr['Nom_fonds'].unique())):
        d = df_perfs_ctr[df_perfs_ctr['Nom_fonds'] == name]
        fig_c.add_trace(go.Scatter(
            x=d['Date'], y=d['Performance_base_100'], mode='lines', name=name,
            line=dict(color=colors[i % len(colors)], width=2),
            hovertemplate='<b>%{x|%d/%m/%Y}</b><br>Performance: %{y:.2f}<extra></extra>'
        ))
    fig_c.add_hline(y=100, line_dash='dash', line_color='gray', annotation_text='Base 100', annotation_position='right')
    titre_c = f"Fonds du contrat {contrat_sel} (base 100 au {date_debut_c.strftime('%d/%m/%Y')})"
    fig_c.update_layout(title=titre_c, xaxis_title='Date', yaxis_title='Performance (base 100)', hovermode='x unified', height=500)
    st.plotly_chart(fig_c, use_container_width=True)

    # Graphique rendement vs volatilité (contrat)
    rendements_vola_c = []
    for name in sorted(df_perfs_ctr['Nom_fonds'].unique()):
        dff = df_perfs_ctr[df_perfs_ctr['Nom_fonds'] == name]
        if len(dff) > 0:
            nb_j = len(dff)
            perf_b = dff['Performance_base_100'].iloc[-1]
            rend_c = ((perf_b / 100) ** (365 / nb_j) - 1) * 100 if nb_j > 0 else 0
            vola_c = dff['Rendement'].std() * np.sqrt(252) * 100
            rendements_vola_c.append({
                'Fonds': name,
                'Rendement': rend_c,
                'Volatilité': vola_c
            })
    
    if rendements_vola_c:
        df_rend_vola_c = pd.DataFrame(rendements_vola_c)
        fig_scatter_c = go.Figure()
        colors_c = px.colors.qualitative.Set2
        for i, row in df_rend_vola_c.iterrows():
            fig_scatter_c.add_trace(go.Scatter(
                x=[row['Volatilité']],
                y=[row['Rendement']],
                mode='markers+text',
                name=row['Fonds'],
                text=[row['Fonds']],
                textposition='top center',
                marker=dict(size=15, color=colors_c[i % len(colors_c)]),
                hovertemplate='<b>%{text}</b><br>Volatilité: %{x:.2f}%<br>Rendement annualisé: %{y:.2f}%<extra></extra>'
            ))
        fig_scatter_c.update_layout(
            title="Rendement vs Volatilité (annualisés)",
            xaxis_title="Volatilité annualisée (%)",
            yaxis_title="Rendement annualisé (%)",
            hovermode='closest',
            height=500,
            showlegend=False
        )
        st.plotly_chart(fig_scatter_c, use_container_width=True)

    # Statistiques par fonds
    st.header("Statistiques de la période")
    for name in sorted(df_perfs_ctr['Nom_fonds'].unique()):
        dff = df_perfs_ctr[df_perfs_ctr['Nom_fonds'] == name]
        c1, c2, c3, c4 = st.columns(4)
        perf_tot = dff['Performance_base_100'].iloc[-1] - 100
        nb_j = (date_fin_c - date_debut_c).days
        rend_ann = ((dff['Performance_base_100'].iloc[-1] / 100) ** (365 / nb_j) - 1) * 100 if nb_j > 0 else 0
        vola = dff['Rendement'].std() * np.sqrt(252) * 100
        with c1:
            st.metric("Performance totale", f"{perf_tot:.2f}%")
        with c2:
            st.metric("Rendement annualisé", f"{rend_ann:.2f}%")
        with c3:
            st.metric("Volatilité annualisée", f"{vola:.2f}%")
        with c4:
            st.metric("Nombre de jours", f"{len(dff)}")

    # Table et export
    with st.expander("📊 Voir les données de la courbe (contrat)"):
        df_display_c = df_perfs_ctr[['Date','Nom_fonds','Rendement','Performance_base_100']].copy()
        df_display_c['Date'] = df_display_c['Date'].dt.strftime('%d/%m/%Y')
        df_display_c.columns = ['Date','Fonds','Rendement quotidien','Performance (base 100)']
        st.dataframe(df_display_c, hide_index=True, use_container_width=True)

    with st.expander("📥 Télécharger les données (contrat)"):
        csv_c = df_display_c.to_csv(index=False, sep=';', decimal=',')
        st.download_button(
            label="💾 Télécharger les données (CSV)",
            data=csv_c,
            file_name=f"performance_contrat_{contrat_sel}_{date_debut_c.strftime('%Y%m%d')}_{date_fin_c.strftime('%Y%m%d')}.csv",
            mime='text/csv'
        )
