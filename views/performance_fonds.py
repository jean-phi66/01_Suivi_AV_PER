import streamlit as st
from streamlit import session_state as ss
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import os
import glob
from scipy.optimize import minimize
from scipy.interpolate import make_interp_spline, splprep, splev

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

# Fonction pour calculer la frontière efficiente
@st.cache_data
def calculate_efficient_frontier(df_fonds_list, fonds_list, date_debut_key, date_fin_key):
    """Calcule la frontière efficiente avec optimisation et matrice de covariance"""
    if len(fonds_list) < 2:
        return None, None
    
    try:
        # Préparer les rendements quotidiens directement de df_fonds_list
        rendements_dict = {}
        for fonds in fonds_list:
            df_f = df_fonds_list[df_fonds_list['Nom_fonds'] == fonds].sort_values('Date')
            if len(df_f) > 1:
                rends = df_f['Rendement'].dropna().values
                if len(rends) > 2:
                    rendements_dict[fonds] = rends
        
        if len(rendements_dict) < 2:
            return None, None
        
        # Aligner à la même longueur
        min_len = min(len(r) for r in rendements_dict.values())
        if min_len < 2:
            return None, None
        
        fonds_keys = list(rendements_dict.keys())
        rendements_array = np.array([rendements_dict[f][-min_len:] for f in fonds_keys])
        
        nb_jours = min_len
        n_assets = len(fonds_keys)
        
        # Rendements annualisés des fonds individuels
        perf_cumulees = np.prod(1 + rendements_array, axis=1)
        mean_returns_annualized = ((perf_cumulees ** (365 / nb_jours)) - 1)
        
        # Matrice de covariance
        cov_matrix = np.cov(rendements_array)
        
        frontier_vol = []
        frontier_ret = []
        
        # Grille de rendements cibles
        ret_min = np.min(mean_returns_annualized)
        ret_max = np.max(mean_returns_annualized)
        target_rets = np.linspace(ret_min * 0.95, ret_max * 1.05, 100)
        
        for target_ret in target_rets:
            # Fonction objectif : minimiser la volatilité
            def portfolio_vol(weights):
                var = np.dot(weights.T, np.dot(cov_matrix * 252, weights))
                return np.sqrt(max(var, 0))
            
            # Contraintes
            constraints = [
                {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},  # Somme des poids = 1
                {'type': 'eq', 'fun': lambda w: np.dot(w, mean_returns_annualized) - target_ret}  # Rendement cible
            ]
            
            bounds = tuple((0, 1) for _ in range(n_assets))
            x0 = np.array([1.0 / n_assets] * n_assets)
            
            try:
                result = minimize(
                    portfolio_vol,
                    x0,
                    method='SLSQP',
                    bounds=bounds,
                    constraints=constraints,
                    options={'maxiter': 1000, 'ftol': 1e-9}
                )
                
                if result.success:
                    vol = portfolio_vol(result.x)
                    ret = np.dot(result.x, mean_returns_annualized)
                    
                    # Ajouter si cohérent
                    if 0 <= vol < 2 and -0.5 < ret < 2:
                        frontier_vol.append(vol * 100)
                        frontier_ret.append(ret * 100)
            except:
                pass
        
        if len(frontier_vol) > 1:
            # Trier et dédupliquer
            data = sorted(zip(frontier_vol, frontier_ret))
            frontier_vol = [v for v, r in data]
            frontier_ret = [r for v, r in data]
            
            # Garder seulement l'enveloppe efficiente
            unique_frontier_vol = []
            unique_frontier_ret = []
            max_ret = -np.inf
            
            for vol, ret in zip(frontier_vol, frontier_ret):
                if ret >= max_ret - 1e-6:
                    unique_frontier_vol.append(vol)
                    unique_frontier_ret.append(ret)
                    max_ret = ret
            
            if len(unique_frontier_vol) > 1:
                return unique_frontier_vol, unique_frontier_ret
        
        return None, None
        
    except Exception as e:
        return None, None

# Fonction pour calculer la position de l'allocation courante
def calculate_current_allocation(df_fonds_list, fonds_list, df_alloc, fonds_names_to_isin=None):
    """Calcule le rendement et volatilité de l'allocation courante + pondérations"""
    try:
        # Récupérer les poids actuels des fonds
        if df_alloc.empty or 'Code ISIN' not in df_alloc.columns or 'Encours en €' not in df_alloc.columns:
            return None, None, None
        
        # Mapping des noms de fonds vers ISINs si nécessaire
        fonds_to_isin = {}
        for fonds in fonds_list:
            df_f = df_fonds_list[df_fonds_list['Nom_fonds'] == fonds]
            if len(df_f) > 0 and 'Code ISIN' in df_f.columns:
                isin = df_f['Code ISIN'].iloc[0]
                if pd.notna(isin):
                    fonds_to_isin[fonds] = isin
        
        if not fonds_to_isin:
            return None, None, None
        
        # Récupérer les encours pour ces fonds (sur allocations filtrées uniquement)
        isins = list(fonds_to_isin.values())
        alloc_fonds = df_alloc[df_alloc['Code ISIN'].isin(isins)]
        
        if alloc_fonds.empty:
            return None, None, None
        
        # Calculer les poids (encours / total DES ALLOCATIONS FILTREES)
        total_encours = df_alloc['Encours en €'].sum()
        if total_encours <= 0:
            return None, None, None
        
        weights_abs_dict = {}
        for fonds, isin in fonds_to_isin.items():
            fonds_encours = alloc_fonds[alloc_fonds['Code ISIN'] == isin]['Encours en €'].sum()
            weights_abs_dict[fonds] = fonds_encours / total_encours
        
        # Calculer les rendements et volatilités des fonds
        rendements_dict = {}
        for fonds in fonds_list:
            df_f = df_fonds_list[df_fonds_list['Nom_fonds'] == fonds].sort_values('Date')
            if len(df_f) > 1:
                rends = df_f['Rendement'].dropna().values
                if len(rends) > 2:
                    rendements_dict[fonds] = rends
        
        if len(rendements_dict) < len(fonds_to_isin):
            return None, None, None
        
        # Aligner à la même longueur
        min_len = min(len(r) for r in rendements_dict.values())
        if min_len < 2:
            return None, None, None
        
        # Construire la matrice de rendements pour les fonds avec données
        fonds_keys = list(rendements_dict.keys())
        rendements_array = np.array([rendements_dict[f][-min_len:] for f in fonds_keys])
        
        # Rendements annualisés
        perf_cumulees = np.prod(1 + rendements_array, axis=1)
        mean_returns_annualized = ((perf_cumulees ** (365 / min_len)) - 1)
        
        # Matrice de covariance
        cov_matrix = np.cov(rendements_array)
        
        # Recalculer les poids en excluant les fonds sans historique
        total_weight_with_data = sum(weights_abs_dict.get(f, 0) for f in fonds_keys)
        if total_weight_with_data <= 0:
            return None, None, None
        
        weights_normalized = np.array([weights_abs_dict.get(f, 0) / total_weight_with_data for f in fonds_keys])
        
        # Rendement et volatilité du portefeuille courant
        port_ret = np.dot(weights_normalized, mean_returns_annualized)
        port_var = np.dot(weights_normalized.T, np.dot(cov_matrix * 252, weights_normalized))
        port_vol = np.sqrt(max(port_var, 0))
        
        # Créer un dataframe des pondérations
        poids_df = pd.DataFrame({
            'Fonds': fonds_keys,
            'Pondération (%)': [w * 100 for w in weights_normalized]
        }).sort_values('Pondération (%)', ascending=False)
        
        return port_vol * 100, port_ret * 100, poids_df
        
    except Exception as e:
        return None, None, None

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
        
        # Ajouter la frontière efficiente
        frontier_vols, frontier_rets = calculate_efficient_frontier(df_all_perfs, fonds_selectionnes, str(date_debut), str(date_fin))
        if frontier_vols is not None and frontier_rets is not None and len(frontier_vols) > 0:
            # Trier par volatilité pour tracer correctement
            sorted_indices = np.argsort(frontier_vols)
            frontier_vols_sorted = [frontier_vols[i] for i in sorted_indices]
            frontier_rets_sorted = [frontier_rets[i] for i in sorted_indices]
            
            fig_scatter.add_trace(go.Scatter(
                x=frontier_vols_sorted,
                y=frontier_rets_sorted,
                mode='lines',
                name='Frontière efficiente',
                line=dict(color='red', width=2, dash='dash'),
                hovertemplate='Volatilité: %{x:.2f}%<br>Rendement annualisé: %{y:.2f}%<extra></extra>'
            ))
        
        # Ajouter l'allocation courante
        alloc_vol, alloc_ret, poids_df = calculate_current_allocation(df_all_perfs, fonds_selectionnes, df_alloc_filt)
        if alloc_vol is not None and alloc_ret is not None:
            fig_scatter.add_trace(go.Scatter(
                x=[alloc_vol],
                y=[alloc_ret],
                mode='markers',
                name='Allocation courante',
                marker=dict(size=20, color='green', symbol='star'),
                hovertemplate='<b>Allocation courante</b><br>Volatilité: %{x:.2f}%<br>Rendement annualisé: %{y:.2f}%<extra></extra>'
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
        
        # Afficher les pondérations
        if poids_df is not None and not poids_df.empty:
            with st.expander("📊 Pondérations des fonds (allocation courante)"):
                st.dataframe(
                    poids_df,
                    column_config={
                        "Fonds": "Fonds",
                        "Pondération (%)": st.column_config.NumberColumn("Pondération (%)", format="%.2f")
                    },
                    hide_index=True,
                    use_container_width=True
                )

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
                    
                    # Ajouter la frontière efficiente (auto)
                    frontier_vols_a, frontier_rets_a = calculate_efficient_frontier(
                        df_all_perfs_auto,
                        df_all_perfs_auto['Nom_fonds'].unique().tolist(),
                        str(date_debut_a),
                        str(date_fin_a)
                    )
                    if frontier_vols_a is not None and frontier_rets_a is not None and len(frontier_vols_a) > 0:
                        sorted_indices_a = np.argsort(frontier_vols_a)
                        frontier_vols_sorted_a = [frontier_vols_a[i] for i in sorted_indices_a]
                        frontier_rets_sorted_a = [frontier_rets_a[i] for i in sorted_indices_a]
                        
                        fig_scatter_a.add_trace(go.Scatter(
                            x=frontier_vols_sorted_a,
                            y=frontier_rets_sorted_a,
                            mode='lines',
                            name='Frontière efficiente',
                            line=dict(color='red', width=2, dash='dash'),
                            hovertemplate='Volatilité: %{x:.2f}%<br>Rendement annualisé: %{y:.2f}%<extra></extra>'
                        ))
                    
                    # Ajouter l'allocation courante (auto)
                    fonds_auto_list = df_all_perfs_auto['Nom_fonds'].unique().tolist()
                    alloc_vol_a, alloc_ret_a, poids_df_a = calculate_current_allocation(df_all_perfs_auto, fonds_auto_list, df_alloc_filt)
                    if alloc_vol_a is not None and alloc_ret_a is not None:
                        fig_scatter_a.add_trace(go.Scatter(
                            x=[alloc_vol_a],
                            y=[alloc_ret_a],
                            mode='markers',
                            name='Allocation courante',
                            marker=dict(size=20, color='green', symbol='star'),
                            hovertemplate='<b>Allocation courante</b><br>Volatilité: %{x:.2f}%<br>Rendement annualisé: %{y:.2f}%<extra></extra>'
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
                    
                    # Afficher les pondérations (auto)
                    if poids_df_a is not None and not poids_df_a.empty:
                        with st.expander("📊 Pondérations des fonds (allocation courante)"):
                            st.dataframe(
                                poids_df_a,
                                column_config={
                                    "Fonds": "Fonds",
                                    "Pondération (%)": st.column_config.NumberColumn("Pondération (%)", format="%.2f")
                                },
                                hide_index=True,
                                use_container_width=True
                            )

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
        
        # Ajouter la frontière efficiente (contrat)
        frontier_vols_c, frontier_rets_c = calculate_efficient_frontier(
            df_perfs_ctr,
            df_perfs_ctr['Nom_fonds'].unique().tolist(),
            str(date_debut_c),
            str(date_fin_c)
        )
        if frontier_vols_c is not None and frontier_rets_c is not None and len(frontier_vols_c) > 0:
            sorted_indices_c = np.argsort(frontier_vols_c)
            frontier_vols_sorted_c = [frontier_vols_c[i] for i in sorted_indices_c]
            frontier_rets_sorted_c = [frontier_rets_c[i] for i in sorted_indices_c]
            
            fig_scatter_c.add_trace(go.Scatter(
                x=frontier_vols_sorted_c,
                y=frontier_rets_sorted_c,
                mode='lines',
                name='Frontière efficiente',
                line=dict(color='red', width=2, dash='dash'),
                hovertemplate='Volatilité: %{x:.2f}%<br>Rendement annualisé: %{y:.2f}%<extra></extra>'
            ))
        
        # Ajouter l'allocation courante (contrat)
        fonds_ctr_list = df_perfs_ctr['Nom_fonds'].unique().tolist()
        alloc_vol_c, alloc_ret_c, poids_df_c = calculate_current_allocation(df_perfs_ctr, fonds_ctr_list, df_alloc_filt)
        if alloc_vol_c is not None and alloc_ret_c is not None:
            fig_scatter_c.add_trace(go.Scatter(
                x=[alloc_vol_c],
                y=[alloc_ret_c],
                mode='markers',
                name='Allocation courante',
                marker=dict(size=20, color='green', symbol='star'),
                hovertemplate='<b>Allocation courante</b><br>Volatilité: %{x:.2f}%<br>Rendement annualisé: %{y:.2f}%<extra></extra>'
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
        
        # Afficher les pondérations (contrat)
        if poids_df_c is not None and not poids_df_c.empty:
            with st.expander("📊 Pondérations des fonds (allocation courante)"):
                st.dataframe(
                    poids_df_c,
                    column_config={
                        "Fonds": "Fonds",
                        "Pondération (%)": st.column_config.NumberColumn("Pondération (%)", format="%.2f")
                    },
                    hide_index=True,
                    use_container_width=True
                )

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
