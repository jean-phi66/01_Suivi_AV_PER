import streamlit as st
from streamlit import session_state as ss

import locale
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

df_contrats = ss['df_contrats']
df_allocations = ss['df_allocations']
df_contrat_agg = ss['df_contrat_agg']
df_contrat_agg_raw = ss.get('df_contrat_agg_raw', df_contrat_agg)
df_contrat_agg_filtered = ss.get('df_contrat_agg_filtered', df_contrat_agg)
export_exclusion_dates = ss.get('export_exclusion_dates', [])
export_exclusion_details = ss.get('export_exclusion_details', [])

# Utiliser la version filtrée par défaut pour l'ensemble des graphiques historiques
df_contrat_agg = df_contrat_agg_filtered

locale.setlocale(locale.LC_ALL, '')
# st.dataframe(df_contrats)

# --- SYNTHESE ENCOURS / DONUT EN TÊTE DE PAGE ---
st.header("📊 Synthèse encours sous gestion")

col_metric, col_ventilation_enveloppe = st.columns(2)

total_encours = df_contrats['Valorisation'].sum()
total_encours = np.round(total_encours, 0)
total_encours_str = '{:,}'.format(total_encours).replace(',', ' ') + '€'

ventilation_encours = df_contrats[['Enveloppe',
                                   'Montant total des versements bruts',
                                   'Montant total des versements nets', 'Valorisation']].groupby(['Enveloppe'], as_index=False).agg('sum')
ventilation_encours = ventilation_encours.rename(columns={'Montant total des versements bruts': 'Versements bruts',
                                                          'Montant total des versements nets': 'Versements nets'})

fig_pie_enveloppe = px.pie(ventilation_encours,
                           values='Valorisation', names='Enveloppe', hole=.5)
fig_pie_enveloppe.update_layout(title="Ventilation par Enveloppe fiscale")
fig_pie_enveloppe.update_traces(
    texttemplate='%{value:,.0f}€ (%{percent})',
    hovertemplate='<b>%{label}</b><br>Valorisation: %{value:,.0f}€<br>Pourcentage: %{percent}<extra></extra>'
)

with col_metric:
    st.metric(label="En cours sous gestion", value=total_encours_str)
    st.dataframe(
        ventilation_encours,
        hide_index=True,
        column_config={
            "Versements bruts": st.column_config.NumberColumn(format="%.0f €"),
            "Versements nets": st.column_config.NumberColumn(format="%.0f €"),
            "Valorisation": st.column_config.NumberColumn(format="%.0f €"),
        })
with col_ventilation_enveloppe:
    st.plotly_chart(fig_pie_enveloppe)

st.divider()

# --- DÉBUT GRAPHIQUE ÉVOLUTION TEMPORELLE ---
st.header("📈 Évolution de l'encours sous gestion et du nombre de contrats")

if not df_contrat_agg.empty:
    # Préparer les données d'évolution avec moyenne mensuelle
    # Créer une colonne année-mois pour regrouper
    df_contrat_agg_copy = df_contrat_agg.copy()
    df_contrat_agg_copy['Année-Mois'] = df_contrat_agg_copy['Date de valorisation'].dt.to_period('M')
    
    # ÉTAPE 1 : Calculer la valorisation MOYENNE par contrat par mois
    # Cela lisse les variations dues aux différentes dates de valorisation
    evolution_par_contrat = df_contrat_agg_copy.groupby(['Année-Mois', 'Enveloppe', 'N° de contrat']).agg({
        'Valorisation': 'mean',  # Moyenne mensuelle par contrat
        'Date de valorisation': 'first'  # Garder une date de référence
    }).reset_index()
    
    # ÉTAPE 1.5 : Forward fill au niveau des contrats individuels
    # Créer une série temporelle complète pour chaque contrat
    date_min = evolution_par_contrat['Année-Mois'].min()
    date_max = evolution_par_contrat['Année-Mois'].max()
    all_periods = pd.period_range(start=date_min, end=date_max, freq='M')
    
    # Pour chaque contrat, créer une série temporelle complète
    complete_contracts = []
    for (enveloppe, contrat), group in evolution_par_contrat.groupby(['Enveloppe', 'N° de contrat']):
        # Créer un DataFrame avec tous les mois
        df_complete = pd.DataFrame({
            'Année-Mois': all_periods,
            'Enveloppe': enveloppe,
            'N° de contrat': contrat
        })
        # Merger avec les données existantes
        df_complete = df_complete.merge(
            group[['Année-Mois', 'Valorisation', 'Date de valorisation']],
            on='Année-Mois',
            how='left'
        )
        # Forward fill pour reprendre la dernière valorisation connue
        df_complete = df_complete.sort_values('Année-Mois')
        df_complete['Valorisation'] = df_complete['Valorisation'].ffill()
        
        # Ne garder que les périodes où on a une valorisation
        df_complete = df_complete[df_complete['Valorisation'].notna()]
        
        complete_contracts.append(df_complete)
    
    evolution_par_contrat_complete = pd.concat(complete_contracts, ignore_index=True)
    
    # ÉTAPE 2 : Maintenant agréger par mois et enveloppe
    evolution_encours = evolution_par_contrat_complete.groupby(['Année-Mois', 'Enveloppe']).agg({
        'Valorisation': 'sum',  # Somme des valorisations
        'N° de contrat': 'nunique',  # Nombre unique de contrats
        'Date de valorisation': 'first'  # Pour l'affichage
    }).reset_index()
    
    # Convertir la période en datetime pour Plotly
    evolution_encours['Date'] = evolution_encours['Année-Mois'].dt.to_timestamp()
    
    # Renommer pour clarté
    evolution_encours.rename(columns={'N° de contrat': 'Nombre de contrats'}, inplace=True)
    
    # Trier par date
    evolution_encours = evolution_encours.sort_values('Date')
    
    # Afficher quelques statistiques de débogage
    with st.expander("🔍 Informations de debug"):
        st.write(f"Nombre total de lignes dans df_contrat_agg: {len(df_contrat_agg)}")
        st.write(f"Nombre de lignes après moyenne par contrat/mois: {len(evolution_par_contrat)}")
        st.write(f"Nombre de mois uniques: {len(evolution_encours['Année-Mois'].unique())}")
        st.write(f"Plage de dates: {evolution_encours['Date'].min()} → {evolution_encours['Date'].max()}")
        
        # Afficher les données de mars à mai 2025 pour diagnostic
        st.write("📊 Détail mars-mai 2025:")
        mask_2025 = (evolution_encours['Date'] >= '2025-03-01') & (evolution_encours['Date'] <= '2025-05-31')
        st.dataframe(evolution_encours[mask_2025].sort_values(['Date', 'Enveloppe']))
        
        # Afficher un échantillon des données
        st.write("Échantillon des données agrégées (10 derniers mois):")
        st.dataframe(evolution_encours.tail(20))
    
    # Séparer les données AV et PER
    df_av = evolution_encours[evolution_encours['Enveloppe'] == 'Assurance-vie']
    df_per = evolution_encours[evolution_encours['Enveloppe'] == 'PER']
    
    # Créer le graphique avec subplots
    fig_evolution = make_subplots(
        rows=2, cols=1,
        row_heights=[0.7, 0.3],
        subplot_titles=('Encours sous gestion (AV + PER)', 'Nombre de contrats (AV + PER)'),
        vertical_spacing=0.12,
        specs=[[{"secondary_y": False}],
               [{"secondary_y": False}]]
    )
    
    # --- Graphique 1: Encours empilé ---
    # AV
    fig_evolution.add_trace(
        go.Bar(
            x=df_av['Date'],
            y=df_av['Valorisation'],
            name='AV - Encours',
            marker=dict(color='rgb(99, 110, 250)'),
            text=df_av['Valorisation'].apply(lambda x: f'{x:,.0f} €'.replace(',', ' ')),
            textposition='inside',
            textfont=dict(color='white', size=10),
            hovertemplate='<b>Assurance-vie</b><br>Date: %{x|%b %Y}<br>Encours: %{y:,.0f} €<extra></extra>'
        ),
        row=1, col=1
    )
    
    # PER
    fig_evolution.add_trace(
        go.Bar(
            x=df_per['Date'],
            y=df_per['Valorisation'],
            name='PER - Encours',
            marker=dict(color='rgb(239, 85, 59)'),
            text=df_per['Valorisation'].apply(lambda x: f'{x:,.0f} €'.replace(',', ' ')),
            textposition='inside',
            textfont=dict(color='white', size=10),
            hovertemplate='<b>PER</b><br>Date: %{x|%b %Y}<br>Encours: %{y:,.0f} €<extra></extra>'
        ),
        row=1, col=1
    )
    
    # Ajouter les totaux sur chaque barre
    df_total_encours = evolution_encours.groupby('Date')['Valorisation'].sum().reset_index()
    for idx, row in df_total_encours.iterrows():
        fig_evolution.add_annotation(
            x=row['Date'],
            y=row['Valorisation'],
            text=f"{row['Valorisation']:,.0f} €".replace(',', ' '),
            showarrow=False,
            yshift=10,
            font=dict(size=10, color='black', family='Arial Black'),
            row=1, col=1
        )
    
    # --- Graphique 2: Nombre de contrats empilé ---
    # AV
    fig_evolution.add_trace(
        go.Bar(
            x=df_av['Date'],
            y=df_av['Nombre de contrats'],
            name='AV - Contrats',
            marker=dict(color='rgb(99, 110, 250)'),
            text=df_av['Nombre de contrats'].astype(int).astype(str),
            textposition='inside',
            textfont=dict(color='white', size=10),
            hovertemplate='<b>Assurance-vie</b><br>Date: %{x|%b %Y}<br>Contrats: %{y}<extra></extra>',
            showlegend=False
        ),
        row=2, col=1
    )
    
    # PER
    fig_evolution.add_trace(
        go.Bar(
            x=df_per['Date'],
            y=df_per['Nombre de contrats'],
            name='PER - Contrats',
            marker=dict(color='rgb(239, 85, 59)'),
            text=df_per['Nombre de contrats'].astype(int).astype(str),
            textposition='inside',
            textfont=dict(color='white', size=10),
            hovertemplate='<b>PER</b><br>Date: %{x|%b %Y}<br>Contrats: %{y}<extra></extra>',
            showlegend=False
        ),
        row=2, col=1
    )
    
    # Ajouter les totaux de contrats sur chaque barre
    df_total_contrats = evolution_encours.groupby('Date')['Nombre de contrats'].sum().reset_index()
    for idx, row in df_total_contrats.iterrows():
        fig_evolution.add_annotation(
            x=row['Date'],
            y=row['Nombre de contrats'],
            text=f"{int(row['Nombre de contrats'])}",
            showarrow=False,
            yshift=10,
            font=dict(size=10, color='black', family='Arial Black'),
            row=2, col=1
        )
    
    # Mise en forme du graphique
    fig_evolution.update_xaxes(title_text="Date", row=2, col=1)
    fig_evolution.update_yaxes(title_text="Encours (€)", row=1, col=1, tickformat=",")
    fig_evolution.update_yaxes(title_text="Nombre de contrats", row=2, col=1)
    
    fig_evolution.update_layout(
        height=800,
        hovermode='x unified',
        barmode='stack',
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )
    
    st.plotly_chart(fig_evolution, use_container_width=True)
    
    # Statistiques d'évolution
    with st.expander("📊 Statistiques d'évolution"):
        col1, col2, col3 = st.columns(3)
        
        # Calculer les évolutions
        encours_total_dernier = evolution_encours.groupby('Date de valorisation')['Valorisation'].sum().iloc[-1]
        encours_total_premier = evolution_encours.groupby('Date de valorisation')['Valorisation'].sum().iloc[0]
        variation_encours = ((encours_total_dernier - encours_total_premier) / encours_total_premier * 100) if encours_total_premier > 0 else 0
        
        nb_contrats_dernier = evolution_encours.groupby('Date de valorisation')['Nombre de contrats'].sum().iloc[-1]
        nb_contrats_premier = evolution_encours.groupby('Date de valorisation')['Nombre de contrats'].sum().iloc[0]
        variation_contrats = nb_contrats_dernier - nb_contrats_premier
        
        with col1:
            st.metric("Variation encours total", 
                     f"{variation_encours:+.1f}%",
                     delta=f"{encours_total_dernier - encours_total_premier:,.0f} €")
        
        with col2:
            st.metric("Variation nombre de contrats",
                     f"{variation_contrats:+.0f}",
                     delta=f"{nb_contrats_dernier} contrats actuels")
        
        with col3:
            st.metric("Période analysée",
                     f"{len(evolution_encours['Date de valorisation'].unique())} dates")
else:
    st.info("📊 Aucune donnée historique disponible pour afficher l'évolution temporelle.")

# --- DÉBUT GRAPHIQUE COMPOSITION ENCOURS (VERSEMENTS NETS + PERFORMANCE) ---
st.header("📊 Composition de l'encours : Versements nets vs Performance")

if not df_contrat_agg.empty:
    df_composition_base = df_contrat_agg.copy()
    
    # Vérifier que les colonnes nécessaires sont présentes
    required_cols = ['Montant total des versements nets', 'Performance financière en euros (perf du contrat)']
    has_required_cols = all(col in df_composition_base.columns for col in required_cols)
    
    if has_required_cols:
        # Préparer les données avec moyenne mensuelle par contrat
        df_composition_copy = df_composition_base.copy()
        df_composition_copy['Année-Mois'] = df_composition_copy['Date de valorisation'].dt.to_period('M')
        
        # ÉTAPE 1 : Calculer les moyennes mensuelles par contrat
        composition_par_contrat = df_composition_copy.groupby(['Année-Mois', 'Enveloppe', 'N° de contrat']).agg({
            'Montant total des versements nets': 'mean',
            'Valorisation': 'mean',
            'Date de valorisation': 'first'
        }).reset_index()
        
        # ÉTAPE 1.5 : Forward fill et détection des variations anormales
        date_min = composition_par_contrat['Année-Mois'].min()
        date_max = composition_par_contrat['Année-Mois'].max()
        all_periods = pd.period_range(start=date_min, end=date_max, freq='M')
        
        # Seuil de variation anormale (25% de baisse ou hausse)
        seuil_variation = 0.25
        
        complete_contracts_compo = []
        contrats_exclus = []  # Pour le debug
        
        for (enveloppe, contrat), group in composition_par_contrat.groupby(['Enveloppe', 'N° de contrat']):
            df_complete_compo = pd.DataFrame({
                'Année-Mois': all_periods,
                'Enveloppe': enveloppe,
                'N° de contrat': contrat
            })
            df_complete_compo = df_complete_compo.merge(
                group[['Année-Mois', 'Montant total des versements nets', 'Valorisation']],
                on='Année-Mois',
                how='left'
            )
            df_complete_compo = df_complete_compo.sort_values('Année-Mois')
            
            # Détecter les variations anormales avant le forward fill
            for idx in range(1, len(df_complete_compo)):
                if pd.notna(df_complete_compo.iloc[idx]['Valorisation']) and pd.notna(df_complete_compo.iloc[idx-1]['Valorisation']):
                    val_actuelle = df_complete_compo.iloc[idx]['Valorisation']
                    val_precedente = df_complete_compo.iloc[idx-1]['Valorisation']
                    
                    if val_precedente > 0:  # Éviter division par zéro
                        variation = abs((val_actuelle - val_precedente) / val_precedente)
                        
                        # Si variation > seuil, exclure cette donnée et utiliser la valeur précédente
                        if variation > seuil_variation:
                            contrats_exclus.append({
                                'Contrat': contrat,
                                'Mois': df_complete_compo.iloc[idx]['Année-Mois'],
                                'Val précédente': val_precedente,
                                'Val actuelle (exclue)': val_actuelle,
                                'Variation': f"{variation*100:.1f}%"
                            })
                            # Remplacer par NaN pour que le forward fill prenne le relais
                            df_complete_compo.at[df_complete_compo.index[idx], 'Valorisation'] = np.nan
                            df_complete_compo.at[df_complete_compo.index[idx], 'Montant total des versements nets'] = np.nan
            
            # Forward fill après avoir exclu les valeurs anormales
            df_complete_compo['Montant total des versements nets'] = df_complete_compo['Montant total des versements nets'].ffill()
            df_complete_compo['Valorisation'] = df_complete_compo['Valorisation'].ffill()
            
            df_complete_compo = df_complete_compo[df_complete_compo['Valorisation'].notna()]
            complete_contracts_compo.append(df_complete_compo)
        
        composition_complete = pd.concat(complete_contracts_compo, ignore_index=True)
        
        # ÉTAPE 2 : Agréger par mois (sans distinction AV/PER)
        composition_encours = composition_complete.groupby(['Année-Mois']).agg({
            'Montant total des versements nets': 'sum',
            'Valorisation': 'sum',
            'N° de contrat': 'nunique'  # Compter le nombre de contrats
        }).reset_index()
        
        # Calculer la performance APRÈS l'agrégation
        composition_encours['Performance'] = composition_encours['Valorisation'] - composition_encours['Montant total des versements nets']
        
        composition_encours['Date'] = composition_encours['Année-Mois'].dt.to_timestamp()
        composition_encours = composition_encours.sort_values('Date')
        
        # Debug pour janvier 2025
        with st.expander("🔍 Debug Composition - Janvier 2025"):
            st.write("### ⚠️ Contrats exclus pour variations anormales:")
            if contrats_exclus:
                df_exclus = pd.DataFrame(contrats_exclus)
                st.dataframe(df_exclus)
                st.write(f"**Total de valeurs exclues: {len(contrats_exclus)}**")
            else:
                st.info("Aucun contrat exclu pour variation anormale")
            
            st.write("### Données agrégées janvier 2025:")
            jan_2025 = composition_encours[composition_encours['Année-Mois'] == '2025-01']
            if not jan_2025.empty:
                st.dataframe(jan_2025)
            else:
                st.write("Pas de données pour janvier 2025")
            
            st.write("### Détail par contrat pour janvier 2025:")
            jan_2025_contracts = composition_complete[composition_complete['Année-Mois'] == '2025-01']
            if not jan_2025_contracts.empty:
                st.dataframe(jan_2025_contracts[['N° de contrat', 'Enveloppe', 'Montant total des versements nets', 'Valorisation']].sort_values('N° de contrat'))
                st.write(f"**Nombre de contrats:** {len(jan_2025_contracts)}")
            else:
                st.write("Pas de contrats pour janvier 2025")
            
            st.write("### Comparaison décembre 2024 vs janvier 2025:")
            dec_2024 = composition_encours[composition_encours['Année-Mois'] == '2024-12']
            if not dec_2024.empty and not jan_2025.empty:
                comparison = pd.DataFrame({
                    'Mois': ['Décembre 2024', 'Janvier 2025'],
                    'Versements nets': [dec_2024['Montant total des versements nets'].values[0], jan_2025['Montant total des versements nets'].values[0]],
                    'Valorisation': [dec_2024['Valorisation'].values[0], jan_2025['Valorisation'].values[0]],
                    'Performance': [dec_2024['Performance'].values[0], jan_2025['Performance'].values[0]],
                    'Nb contrats': [dec_2024['N° de contrat'].values[0], jan_2025['N° de contrat'].values[0]]
                })
                st.dataframe(comparison)
                
                # Vérifier combien de contrats ont des données réelles vs forward-fillées
                st.write("### Analyse des données sources:")
                real_data_jan = composition_par_contrat[composition_par_contrat['Année-Mois'] == '2025-01']
                st.write(f"Contrats avec données réelles en janvier 2025: **{len(real_data_jan)}**")
                st.write(f"Contrats après forward fill: **{len(jan_2025_contracts)}**")
                st.write(f"Contrats forward-fillés: **{len(jan_2025_contracts) - len(real_data_jan)}**")
        
        # Créer le graphique avec axe Y secondaire
        fig_composition = make_subplots(specs=[[{"secondary_y": True}]])
        
        # Versements nets (global)
        fig_composition.add_trace(
            go.Bar(
                x=composition_encours['Date'],
                y=composition_encours['Montant total des versements nets'],
                name='Versements nets',
                marker=dict(color='rgb(99, 110, 250)'),
                text=composition_encours['Montant total des versements nets'].apply(lambda x: f'{x:,.0f} €'.replace(',', ' ')),
                textposition='inside',
                textfont=dict(color='white', size=10),
                hovertemplate='<b>Versements nets</b><br>Date: %{x|%b %Y}<br>Montant: %{y:,.0f} €<extra></extra>'
            ),
            secondary_y=False
        )
        
        # Performance (global)
        fig_composition.add_trace(
            go.Bar(
                x=composition_encours['Date'],
                y=composition_encours['Performance'],
                name='Performance',
                marker=dict(color='rgb(239, 85, 59)'),
                text=composition_encours['Performance'].apply(lambda x: f'{x:,.0f} €'.replace(',', ' ')),
                textposition='inside',
                textfont=dict(color='white', size=10),
                hovertemplate='<b>Performance</b><br>Date: %{x|%b %Y}<br>Montant: %{y:,.0f} €<extra></extra>'
            ),
            secondary_y=False
        )
        
        # Nombre de contrats (ligne)
        fig_composition.add_trace(
            go.Scatter(
                x=composition_encours['Date'],
                y=composition_encours['N° de contrat'],
                name='Nombre de contrats',
                mode='lines+markers+text',
                line=dict(color='rgb(50, 50, 50)', width=3),
                marker=dict(size=8, color='rgb(50, 50, 50)'),
                text=composition_encours['N° de contrat'].astype(int),
                textposition='top center',
                textfont=dict(color='white', size=9),
                hovertemplate='<b>Nombre de contrats</b><br>Date: %{x|%b %Y}<br>Contrats: %{y}<extra></extra>'
            ),
            secondary_y=True
        )
        
        # Ajouter les totaux d'encours
        for idx, row in composition_encours.iterrows():
            fig_composition.add_annotation(
                x=row['Date'],
                y=row['Valorisation'],
                text=f"{row['Valorisation']:,.0f} €".replace(',', ' '),
                showarrow=False,
                yshift=10,
                font=dict(size=10, color='black', family='Arial Black'),
                yref='y'
            )
        
        fig_composition.update_layout(
            barmode='stack',
            height=500,
            hovermode='x unified',
            xaxis_title="Date",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        
        # Configurer les axes Y
        fig_composition.update_yaxes(title_text="Montant (€)", tickformat=",", secondary_y=False)
        
        # Adapter l'échelle de l'axe Y secondaire pour que la courbe soit dans la moitié basse
        max_contrats = composition_encours['N° de contrat'].max()
        fig_composition.update_yaxes(
            title_text="Nombre de contrats", 
            range=[0, max_contrats * 2.5],  # Multiplier par 2.5 pour garder la courbe dans la moitié basse
            secondary_y=True
        )
        
        st.plotly_chart(fig_composition, use_container_width=True)
    else:
        st.warning("Les colonnes nécessaires (Versements nets, Performance financière) ne sont pas disponibles dans les données historiques.")
else:
    st.info("📊 Aucune donnée historique disponible pour afficher la composition de l'encours.")

# --- DÉBUT GRAPHIQUE PAR DATE D'EXPORT ---
st.header("📅 Évolution de l'encours par date d'export")

if not df_contrat_agg.empty and 'Date export' in df_contrat_agg.columns:
    # Vérifier que les colonnes nécessaires sont présentes
    required_cols = ['Montant total des versements nets', 'Valorisation']
    has_required_cols = all(col in df_contrat_agg.columns for col in required_cols)
    
    if has_required_cols:
        # Filtrer les données avec date d'export valide
        df_export_copy = df_contrat_agg[df_contrat_agg['Date export'].notna()].copy()
        
        if not df_export_copy.empty:
            # Agréger par date d'export (prendre la moyenne par contrat si plusieurs lignes)
            export_data = df_export_copy.groupby(['Date export', 'Enveloppe', 'N° de contrat']).agg({
                'Montant total des versements nets': 'mean',
                'Valorisation': 'mean'
            }).reset_index()
            
            # Agréger par date d'export total
            export_encours = export_data.groupby(['Date export']).agg({
                'Montant total des versements nets': 'sum',
                'Valorisation': 'sum',
                'N° de contrat': 'nunique'
            }).reset_index()
            
            # Calculer la performance
            export_encours['Performance'] = export_encours['Valorisation'] - export_encours['Montant total des versements nets']
            export_encours = export_encours.sort_values('Date export')
            
            export_encours_filtre = export_encours.copy()

            # Debug des exports exclus (issus de l'ingestion)
            with st.expander("🔍 Debug Exports exclus"):
                if export_exclusion_details:
                    st.write("### ⚠️ Exports exclus pour variations anormales:")
                    df_exports_exclus = pd.DataFrame(export_exclusion_details)
                    st.dataframe(df_exports_exclus)
                    st.write(f"**Total d'exports exclus: {len(export_exclusion_details)}**")
                else:
                    st.info("Aucun export exclu pour variation anormale")
            
            # Créer le graphique
            fig_export = make_subplots(specs=[[{"secondary_y": True}]])
            
            # Versements nets
            fig_export.add_trace(
                go.Bar(
                    x=export_encours_filtre['Date export'],
                    y=export_encours_filtre['Montant total des versements nets'],
                    name='Versements nets',
                    marker=dict(color='rgb(99, 110, 250)'),
                    text=export_encours_filtre['Montant total des versements nets'].apply(lambda x: f'{x:,.0f} €'.replace(',', ' ')),
                    textposition='inside',
                    textfont=dict(color='white', size=10),
                    hovertemplate='<b>Versements nets</b><br>Date: %{x|%d/%m/%Y}<br>Montant: %{y:,.0f} €<extra></extra>'
                ),
                secondary_y=False
            )
            
            # Performance
            fig_export.add_trace(
                go.Bar(
                    x=export_encours_filtre['Date export'],
                    y=export_encours_filtre['Performance'],
                    name='Performance',
                    marker=dict(color='rgb(239, 85, 59)'),
                    text=export_encours_filtre['Performance'].apply(lambda x: f'{x:,.0f} €'.replace(',', ' ')),
                    textposition='inside',
                    textfont=dict(color='white', size=10),
                    hovertemplate='<b>Performance</b><br>Date: %{x|%d/%m/%Y}<br>Montant: %{y:,.0f} €<extra></extra>'
                ),
                secondary_y=False
            )
            
            # Nombre de contrats
            fig_export.add_trace(
                go.Scatter(
                    x=export_encours_filtre['Date export'],
                    y=export_encours_filtre['N° de contrat'],
                    name='Nombre de contrats',
                    mode='lines+markers+text',
                    line=dict(color='rgb(50, 50, 50)', width=3),
                    marker=dict(size=8, color='rgb(50, 50, 50)'),
                    text=export_encours_filtre['N° de contrat'].astype(int),
                    textposition='top center',
                    textfont=dict(color='white', size=9),
                    hovertemplate='<b>Nombre de contrats</b><br>Date: %{x|%d/%m/%Y}<br>Contrats: %{y}<extra></extra>'
                ),
                secondary_y=True
            )
            
            # Ajouter les totaux
            for idx, row in export_encours_filtre.iterrows():
                fig_export.add_annotation(
                    x=row['Date export'],
                    y=row['Valorisation'],
                    text=f"{row['Valorisation']:,.0f} €".replace(',', ' '),
                    showarrow=False,
                    yshift=10,
                    font=dict(size=10, color='black', family='Arial Black'),
                    yref='y'
                )
            
            fig_export.update_layout(
                barmode='stack',
                height=500,
                hovermode='x unified',
                xaxis_title="Date d'export",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )
            
            # Configurer les axes Y
            fig_export.update_yaxes(title_text="Montant (€)", tickformat=",", secondary_y=False)
            max_contrats_export = export_encours_filtre['N° de contrat'].max()
            fig_export.update_yaxes(
                title_text="Nombre de contrats", 
                range=[0, max_contrats_export * 2.5],
                secondary_y=True
            )
            
            st.plotly_chart(fig_export, use_container_width=True)
        else:
            st.warning("Aucune donnée avec date d'export valide")
    else:
        st.warning("Les colonnes nécessaires ne sont pas disponibles")
else:
    st.info("📊 Aucune donnée historique avec date d'export disponible")

st.divider()
# --- FIN GRAPHIQUE PAR DATE D'EXPORT ---

# --- DÉBUT GRAPHIQUE VALORISATION PAR CONTRAT ---
st.header("📊 Valorisation de chaque contrat par date d'export")

if not df_contrat_agg.empty and 'Date export' in df_contrat_agg.columns:
    df_contrat_agg_temp = df_contrat_agg[df_contrat_agg['Date export'].notna()].copy()
    
    if not df_contrat_agg_temp.empty:
        df_contrats_filtre = df_contrat_agg_temp.copy()
        
        if not df_contrats_filtre.empty:
            # Créer le graphique avec une ligne par contrat
            fig_contrats = go.Figure()
            
            # Grouper par contrat
            for (contrat, titulaire), group in df_contrats_filtre.groupby(['N° de contrat', 'Titulaire(s)']):
                # Trier par date d'export
                group_sorted = group.sort_values('Date export')
                
                # Prendre la valorisation moyenne par date d'export (au cas où plusieurs lignes)
                group_agg = group_sorted.groupby('Date export').agg({
                    'Valorisation': 'mean',
                    'Enveloppe': 'first'
                }).reset_index()
                
                # Couleur selon l'enveloppe
                couleur = 'rgb(99, 110, 250)' if group_agg['Enveloppe'].iloc[0] == 'Assurance-vie' else 'rgb(239, 85, 59)'
                
                fig_contrats.add_trace(
                    go.Scatter(
                        x=group_agg['Date export'],
                        y=group_agg['Valorisation'],
                        name=f"{titulaire} - {contrat}",
                        mode='lines+markers',
                        line=dict(width=1.5, color=couleur),
                        marker=dict(size=4),
                        hovertemplate=f'<b>{titulaire}</b><br>Contrat: {contrat}<br>Date: %{{x|%d/%m/%Y}}<br>Valorisation: %{{y:,.0f}} €<extra></extra>',
                        opacity=0.7
                    )
                )
            
            fig_contrats.update_layout(
                height=600,
                hovermode='x unified',
                xaxis_title="Date d'export",
                yaxis_title="Valorisation (€)",
                yaxis_tickformat=",",
                showlegend=True,
                legend=dict(
                    yanchor="top",
                    y=0.99,
                    xanchor="left",
                    x=1.01,
                    bgcolor="rgba(255, 255, 255, 0.8)"
                )
            )
            
            st.plotly_chart(fig_contrats, use_container_width=True)
            
            st.info(f"📈 {len(df_contrats_filtre['N° de contrat'].unique())} contrats affichés sur {len(df_contrats_filtre['Date export'].unique())} dates d'export")
        else:
            st.warning("Aucune donnée après filtrage des exports aberrants")
    else:
        st.warning("Aucune donnée avec date d'export valide")
else:
    st.info("📊 Aucune donnée historique avec date d'export disponible")

st.divider()
# --- FIN GRAPHIQUE VALORISATION PAR CONTRAT ---

# --- DÉBUT GRAPHIQUES DIAGNOSTIC : VALORISATION VS VERSEMENTS NETS ---
st.header("🔍 Diagnostic : Valorisation vs Versements Nets par export")
st.info("Ces graphiques permettent d'identifier visuellement les exports aberrants en comparant la valorisation aux versements nets.")

if not df_contrat_agg.empty and 'Date export' in df_contrat_agg.columns:
    df_diag = df_contrat_agg[df_contrat_agg['Date export'].notna()].copy()
    
    if not df_diag.empty:
        # Créer deux colonnes pour afficher les graphiques côte à côte
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Données agrégées (tous contrats)")
            
            # Agréger par date d'export
            df_agg_total = df_diag.groupby('Date export').agg({
                'Valorisation': 'sum',
                'Montant total des versements nets': 'sum'
            }).reset_index().sort_values('Date export')
            
            # Créer le graphique scatter
            fig_agg = go.Figure()
            
            # Créer un index numérique pour la couleur
            df_agg_total['index_color'] = range(len(df_agg_total))
            
            # Ajouter les points colorés par date
            fig_agg.add_trace(
                go.Scatter(
                    x=df_agg_total['Montant total des versements nets'],
                    y=df_agg_total['Valorisation'],
                    mode='markers+lines+text',
                    marker=dict(
                        size=10,
                        color=df_agg_total['index_color'],
                        colorscale='Viridis',
                        showscale=False,
                        line=dict(width=1, color='white')
                    ),
                    text=df_agg_total['Date export'].dt.strftime('%d/%m/%Y'),
                    textposition='top center',
                    textfont=dict(size=8),
                    hovertemplate='<b>Date: %{text}</b><br>Versements nets: %{x:,.0f} €<br>Valorisation: %{y:,.0f} €<extra></extra>',
                    showlegend=False
                )
            )
            
            # Ajouter la ligne y=x (performance nulle)
            vn_min = df_agg_total['Montant total des versements nets'].min()
            vn_max = df_agg_total['Montant total des versements nets'].max()
            fig_agg.add_trace(
                go.Scatter(
                    x=[vn_min, vn_max],
                    y=[vn_min, vn_max],
                    mode='lines',
                    line=dict(color='gray', dash='dash', width=1),
                    name='Performance = 0',
                    hoverinfo='skip'
                )
            )
            
            fig_agg.update_layout(
                height=500,
                xaxis_title="Versements nets cumulés (€)",
                yaxis_title="Valorisation (€)",
                xaxis_tickformat=",",
                yaxis_tickformat=",",
                hovermode='closest',
                showlegend=True
            )
            
            st.plotly_chart(fig_agg, use_container_width=True)
            
            # Afficher les points suspects
            df_agg_total['Performance'] = df_agg_total['Valorisation'] - df_agg_total['Montant total des versements nets']
            df_agg_total['Taux_performance'] = (df_agg_total['Performance'] / df_agg_total['Montant total des versements nets'] * 100)
            
            with st.expander("📊 Statistiques par export"):
                st.dataframe(
                    df_agg_total[['Date export', 'Montant total des versements nets', 'Valorisation', 'Performance', 'Taux_performance']].rename(columns={
                        'Montant total des versements nets': 'Versements nets',
                        'Taux_performance': 'Taux perf. (%)'
                    }).style.format({
                        'Versements nets': '{:,.0f} €',
                        'Valorisation': '{:,.0f} €',
                        'Performance': '{:,.0f} €',
                        'Taux perf. (%)': '{:.2f}%'
                    }),
                    use_container_width=True
                )
        
        with col2:
            st.subheader("Tous les contrats superposés")
            
            # Créer le graphique scatter pour chaque contrat
            fig_contrats = go.Figure()
            
            # Grouper par contrat
            for (contrat, titulaire, enveloppe), group in df_diag.groupby(['N° de contrat', 'Titulaire(s)', 'Enveloppe']):
                group_sorted = group.sort_values('Date export')
                
                # Couleur selon l'enveloppe
                couleur = 'rgba(99, 110, 250, 0.5)' if enveloppe == 'Assurance-vie' else 'rgba(239, 85, 59, 0.5)'
                
                fig_contrats.add_trace(
                    go.Scatter(
                        x=group_sorted['Montant total des versements nets'],
                        y=group_sorted['Valorisation'],
                        mode='markers+lines',
                        marker=dict(size=4, color=couleur),
                        line=dict(width=0.5, color=couleur),
                        name=f"{titulaire} - {contrat}",
                        hovertemplate=f'<b>{titulaire}</b><br>Contrat: {contrat}<br>Date: %{{text}}<br>VN: %{{x:,.0f}} €<br>Val: %{{y:,.0f}} €<extra></extra>',
                        text=group_sorted['Date export'].dt.strftime('%d/%m/%Y'),
                        showlegend=False
                    )
                )
            
            # Ajouter la ligne y=x (performance nulle)
            vn_min_all = df_diag['Montant total des versements nets'].min()
            vn_max_all = df_diag['Montant total des versements nets'].max()
            fig_contrats.add_trace(
                go.Scatter(
                    x=[vn_min_all, vn_max_all],
                    y=[vn_min_all, vn_max_all],
                    mode='lines',
                    line=dict(color='gray', dash='dash', width=1),
                    name='Performance = 0',
                    hoverinfo='skip'
                )
            )
            
            fig_contrats.update_layout(
                height=500,
                xaxis_title="Versements nets cumulés (€)",
                yaxis_title="Valorisation (€)",
                xaxis_tickformat=",",
                yaxis_tickformat=",",
                hovermode='closest'
            )
            
            st.plotly_chart(fig_contrats, use_container_width=True)
            
            st.info(f"📊 {len(df_diag['N° de contrat'].unique())} contrats sur {len(df_diag['Date export'].unique())} dates d'export")
    else:
        st.warning("Aucune donnée avec date d'export valide")
else:
    st.info("📊 Aucune donnée historique avec date d'export disponible")

st.divider()
# --- FIN GRAPHIQUES DIAGNOSTIC ---

# --- DÉBUT BLOC EXCLUSION CONTRATS SANS PERF FINANCIERE POUR WATERFALL ---
st.subheader("🔍 Filtrage pour Waterfall Contrat Global")
contrats_perf_nan = df_contrats[df_contrats['Performance financière en euros (perf du contrat)'].isnull()]
if not contrats_perf_nan.empty:
    st.warning(
        f"{len(contrats_perf_nan)} contrat(s) ont une performance financière non renseignée et seront exclus du waterfall global :"
    )
    st.dataframe(contrats_perf_nan[[
        'Titulaire(s)', 'N° de contrat', 'Enveloppe', 'Partenaire',
        'Montant total des versements nets', 'Performance financière en euros (perf du contrat)', 'Valorisation'
    ]])
else:
    st.info("Tous les contrats ont une performance financière renseignée pour le waterfall global.")

df_contrats_pour_waterfall = df_contrats.dropna(subset=['Performance financière en euros (perf du contrat)'])
# --- FIN BLOC EXCLUSION CONTRATS SANS PERF FINANCIERE POUR WATERFALL ---

# Calculs pour le Waterfall Contrat Global (déplacés ici pour être utilisés avant l'expander de débogage si besoin)
sum_versements_bruts = df_contrats_pour_waterfall['Montant total des versements bruts'].sum()
sum_versements_nets = df_contrats_pour_waterfall['Montant total des versements nets'].sum()
sum_valorisation = df_contrats_pour_waterfall['Valorisation'].sum()
sum_perf_financiere = df_contrats_pour_waterfall['Performance financière en euros (perf du contrat)'].sum()
sum_rachats_bruts = df_contrats_pour_waterfall['Montant total des rachats bruts'].sum()

aggregation_contrat = pd.DataFrame() # Initialisation
if not df_contrats_pour_waterfall.empty:
    aggregation_contrat = df_contrats_pour_waterfall[['Montant total des versements bruts',
                                       'Montant total des versements nets', 'Valorisation',
                                       'Performance financière en euros (perf du contrat)',
                                       'Montant total des rachats bruts'
                                       ]].sum().to_frame().transpose()
    aggregation_contrat['Frais'] = aggregation_contrat['Montant total des versements bruts'] - \
        aggregation_contrat['Montant total des versements nets']
    aggregation_contrat['Frais'] = - aggregation_contrat['Frais']
    aggregation_contrat['Rachats'] = -aggregation_contrat['Montant total des rachats bruts']
    aggregation_contrat['Solde Net Mouvements'] = aggregation_contrat['Montant total des versements nets'] + aggregation_contrat['Rachats']

    perfo_allocation = df_allocations[~df_allocations['Type'].isin(
        ["Fonds en Euros", "Trésorerie Régulière"])]['+/- value (en €)'].sum()
    aggregation_contrat['Performance allocation'] = perfo_allocation

    if 'Performance financière en euros (perf du contrat)' in aggregation_contrat.columns and 'Performance allocation' in aggregation_contrat.columns:
        aggregation_contrat['Performance embarquée'] = aggregation_contrat[
            'Performance financière en euros (perf du contrat)'] - aggregation_contrat['Performance allocation']
    else:
        aggregation_contrat['Performance embarquée'] = 0 # Fallback si une colonne manque

    # Sélection finale des colonnes pour le waterfall
    aggregation_contrat = aggregation_contrat.reindex(columns=['Montant total des versements bruts',
                                               'Frais',
                                               'Montant total des versements nets',
                                               'Rachats',
                                               'Solde Net Mouvements',
                                               'Performance embarquée',
                                               'Performance allocation',
                                               'Valorisation'], fill_value=0)

# --- FIN DES CALCULS PRÉPARATOIRES POUR LE WATERFALL ---

# Affichage du Waterfall Contrat Global
if not aggregation_contrat.empty:
    aggregation_contrat_melted = pd.melt(aggregation_contrat)
    aggregation_contrat_melted['variable'] = aggregation_contrat_melted['variable'].str.replace('Montant total des versements bruts',
                                                                                  'Versements bruts')
    aggregation_contrat_melted['variable'] = aggregation_contrat_melted['variable'].str.replace('Montant total des versements nets',
                                                                                  'Versements nets')
    # Pas besoin de remplacer 'Rachats' ou 'Solde Net Mouvements' si les noms de colonnes sont déjà corrects

    # Mise à jour de la liste 'measure' pour inclure les nouvelles étapes
    measure = ["relative", "relative", "total",  # VB, Frais -> VN
               "relative", "total",              # Rachats -> SNM
               "relative", "relative", "total"]  # PE, PA -> Valorisation
    fig_waterfall_aggregation_contract = go.Figure(go.Waterfall(
        name="20", orientation="v",
        measure=measure,
        x=aggregation_contrat_melted['variable'],
        textposition="auto",
        text=aggregation_contrat_melted['value'].apply(lambda x: f"{round(x, 0):,.0f} €".replace(',', ' ')),
        y=aggregation_contrat_melted['value'],
        connector={"line": {"color": "rgb(63, 63, 63)"}},
        cliponaxis=False
    ))
    fig_waterfall_aggregation_contract.update_layout(
        title="Situation contrat (basée sur les contrats avec performance financière renseignée)",
        showlegend=False
    )
    st.plotly_chart(fig_waterfall_aggregation_contract, use_container_width=True)
else:
    st.info("Le graphique Waterfall de la situation contrat ne peut pas être généré car aucun contrat ne dispose des données de performance financière nécessaires après filtrage.")


# ventilation_encours['Performance embarquée'] = ventilation_encours[
#    'Performance financière en euros (perf du contrat)'] - ventilation_encours['+/- value (en €)']


# Aggregation by support
df_agg_support = df_allocations.groupby(['Support'],
                                        as_index=False)
df_agg_support = df_agg_support.agg(Type=("Type", "first"),
                                    SRI=('SRI', 'first'),
                                    Prestation=('Prestation', 'first'),
                                    Nombre_de_lignes=(
                                        'Prestation', 'count'),
                                    Encours_total=(
                                        "Encours en €", "sum"),
                                    Encours_moyen=(
                                        'Encours en €', 'mean'),
                                    plus_value_totale=('+/- value (en €)', 'sum'))
df_agg_support['plus_value (en %)'] = np.round(
    df_agg_support['plus_value_totale'] / df_agg_support['Encours_total'] * 100, 2)

# Remplacer les valeurs None dans Type pour éviter l'erreur sunburst
df_agg_support['Type'] = df_agg_support['Type'].fillna('Non classé')

fig_sunb = px.sunburst(df_agg_support,
                        # path= ['Type', 'SRI', 'Support'],
                        path=['Type', 'Support'],
                        values='Encours_total')
fig_sunb.update_traces(
    insidetextorientation='radial',
    hovertemplate='<b>%{label}</b><br>Encours total: %{value:,.0f}€<extra></extra>'
)
st.plotly_chart(fig_sunb)


# Préparation des données pour le waterfall des performances par support
df_supports_perf = df_agg_support[~df_agg_support['Type'].isin(
    ["Fonds en Euros", "Trésorerie Régulière"]
)].copy()

# Trier les supports par leur performance (plus_value_totale)
df_supports_perf = df_supports_perf.sort_values(by=['plus_value_totale'])

# Calculer la ligne "Total"
total_plus_value = df_supports_perf['plus_value_totale'].sum()
total_row = pd.DataFrame({
    'Support': ['Total'],
    'plus_value_totale': [total_plus_value],
    # Autres colonnes pourraient être ajoutées ici si nécessaire pour le hovertemplate, etc.
    # Pour ce graphique, 'Type' et autres ne sont pas directement utilisés pour la ligne Total.
})

# Concaténer les supports triés avec la ligne "Total" à la fin
df_waterfall_data = pd.concat([df_supports_perf, total_row], ignore_index=True)

# Définir les mesures pour le waterfall
df_waterfall_data['measure'] = 'relative'
df_waterfall_data.loc[df_waterfall_data['Support'] == 'Total', 'measure'] = 'total'

fig_waterfall_agg_support = go.Figure(go.Waterfall(
    name="20", orientation="v",
    measure=df_waterfall_data['measure'],
    x=df_waterfall_data['Support'],
    textposition="auto",
    text=df_waterfall_data['plus_value_totale'].apply(lambda x: f"{round(x, 0):,.0f} €".replace(',', ' ')),
    y=df_waterfall_data['plus_value_totale'],
    connector={"line": {"color": "rgb(63, 63, 63)"}},
    cliponaxis=False
))
fig_waterfall_agg_support.update_layout(
    title="Performance allocation",
    showlegend=False,
    # plot_bgcolor="#f0f2f6"
)
st.plotly_chart(fig_waterfall_agg_support, use_container_width=True)


st.divider()

# --- START: Analyse Statistique des Performances des Contrats ---
st.header("Analyse Statistique des Performances des Contrats")

# Créer une copie pour les calculs afin de ne pas modifier le df original
df_kpis = df_contrats.copy()

# --- Calcul des KPIs pour tous les contrats ---

# 1. TRA (Taux de Rendement Annuel)
# S'assurer que les colonnes de date sont au format datetime
df_kpis['Ouverture_dt'] = pd.to_datetime(df_kpis['Ouverture'], errors='coerce')
df_kpis['Date_valorisation_dt'] = pd.to_datetime(df_kpis['Date de valorisation'], errors='coerce')

# Calculer la durée en années
df_kpis['duree_annees'] = (df_kpis['Date_valorisation_dt'] - df_kpis['Ouverture_dt']).dt.days / 365.25

# Conditions pour un calcul valide du TRA
conditions_tra = (
    (df_kpis['duree_annees'] > 0) &
    (df_kpis['Montant total des versements nets'] > 0) &
    (df_kpis['Valorisation'] > 0) & (df_kpis['Montant total des rachats bruts'] == 0)
)

conditions_hist = (
    #(df_kpis['duree_annees'] > 0) &
    (df_kpis['Montant total des versements nets'] > 0) &
    (df_kpis['Valorisation'] > 0) & (df_kpis['Montant total des rachats bruts'] == 0)
)


# Calculer le TRA en utilisant np.where pour gérer les cas non valides
df_kpis['TRA'] = np.where(
    conditions_tra,
    ((df_kpis['Valorisation'] / df_kpis['Montant total des versements nets'])**(1 / df_kpis['duree_annees']) - 1) * 100,
    np.nan  # Utiliser NaN pour les cas où le calcul n'est pas possible
)

# 2. Performance par rapport aux versements
# Perf / VB (%)
df_kpis['Perf_vs_VB_pct'] = np.where(
    #df_kpis['Montant total des versements bruts'] > 0,
    conditions_hist,
    ((df_kpis['Valorisation'] - df_kpis['Montant total des versements bruts']) / df_kpis['Montant total des versements bruts']) * 100,
    np.nan
)

# Perf / VN (%)
df_kpis['Perf_vs_VN_pct'] = np.where(
    #df_kpis['Montant total des versements nets'] > 0,
    conditions_hist,
    ((df_kpis['Valorisation'] - df_kpis['Montant total des versements nets']) / df_kpis['Montant total des versements nets']) * 100,
    np.nan
)

# Sélectionner et renommer les colonnes pour l'affichage
df_kpis_display = df_kpis[[
    'Titulaire(s)', 'N° de contrat', 'Enveloppe', 'Valorisation', 'duree_annees',
    'TRA', 'Perf_vs_VB_pct', 'Perf_vs_VN_pct'
]].rename(columns={
    'duree_annees': 'Ancienneté (années)',
    'TRA': 'TRA (%)',
    'Perf_vs_VB_pct': 'Performance / VB (%)',
    'Perf_vs_VN_pct': 'Performance / VN (%)'
})

st.subheader("Tableau des KPIs par contrat")
st.dataframe(df_kpis_display.style.format({
    'Valorisation': "{:,.0f} €",
    'Ancienneté (années)': "{:.1f}",
    'TRA (%)': "{:.2f}%",
    'Performance / VB (%)': "{:.2f}%",
    'Performance / VN (%)': "{:.2f}%"
}, na_rep='N/A'))


st.subheader("Distributions statistiques des KPIs")
fig_hist_tra = px.histogram(df_kpis_display.dropna(subset=['TRA (%)']), x='TRA (%)', title='Distribution du TRA (Taux de Rendement Annuel) des contrats', nbins=30)
st.plotly_chart(fig_hist_tra, use_container_width=True)

fig_hist_perf_vn = px.histogram(df_kpis_display.dropna(subset=['Performance / VN (%)']), x='Performance / VN (%)', title='Distribution de la Performance vs Versements Nets (%)', nbins=30)
st.plotly_chart(fig_hist_perf_vn, use_container_width=True)

fig_box_tra_env = px.box(df_kpis_display.dropna(subset=['TRA (%)']), x='Enveloppe', y='TRA (%)', title='Distribution du TRA par type d\'enveloppe', points='all', color='Enveloppe')
st.plotly_chart(fig_box_tra_env, use_container_width=True)

fig_perf_anciennete = px.scatter(
    df_kpis_display.dropna(subset=["Performance / VN (%)", "Ancienneté (années)"]),
    x="Ancienneté (années)",
    y="Performance / VN (%)",
    color="Enveloppe",
    hover_data=['Titulaire(s)', 'N° de contrat', 'Valorisation'],
    title="Performance / Versements Nets en fonction de l'ancienneté du contrat"
)
fig_perf_anciennete.update_layout(xaxis_title="Ancienneté du contrat (années)", yaxis_title="Performance / Versements Nets (%)")
st.plotly_chart(fig_perf_anciennete, use_container_width=True)
# --- END: Analyse Statistique des Performances des Contrats ---

# --- DÉBUT SECTION DE DÉBOGAGE (DANS UN EXPANDER) ---
with st.expander("🔍 Section de Débogage"):
    st.subheader("Débogage Waterfall Contrat Global")

    # BLOC DE DÉBOGAGE 1 (Sommes et vérification égalité)
    st.write("**Informations Générales et Vérification de Cohérence**")
    if not df_contrats_pour_waterfall.empty:
        st.write("Sommes pour le waterfall (basées sur les contrats avec performance financière renseignée):")
        st.write(f"- Total Versements Bruts: {sum_versements_bruts:,.0f} €")
        st.write(f"- Total Versements Nets: {sum_versements_nets:,.0f} €")
        st.write(f"- Total Rachats Bruts (valeur absolue): {sum_rachats_bruts:,.0f} €")
        st.write(f"- Total Performance Financière: {sum_perf_financiere:,.0f} €")
        st.write(f"- Total Valorisation: {sum_valorisation:,.0f} €")

        attendu_valorisation = sum_versements_nets - sum_rachats_bruts + sum_perf_financiere
        difference = sum_valorisation - attendu_valorisation
        st.write(f"Vérification équation: Versements Nets ({sum_versements_nets:,.0f} €) - Rachats Bruts ({sum_rachats_bruts:,.0f} €) + Perf. Financière ({sum_perf_financiere:,.0f} €) = {attendu_valorisation:,.0f} €")
        st.write(f"Comparaison avec Valorisation réelle ({sum_valorisation:,.0f} €) : Différence = {difference:,.0f} €")
        if abs(difference) > 0.01:
            st.warning(f"L'équation (Versements Nets - Rachats Bruts + Perf. Financière = Valorisation) n'est pas parfaitement vérifiée. Écart: {difference:,.0f}€.")
    else:
        st.write("Aucun contrat avec performance financière renseignée pour calculer les sommes du waterfall.")
    st.divider()

    # BLOC DE DÉBOGAGE SPÉCIFIQUE PERFORMANCE EMBARQUÉE
    st.write("**Calcul Performance Embarquée**")
    if not aggregation_contrat.empty and not df_contrats_pour_waterfall.empty:
        # Recalcul de perfo_allocation ici pour être sûr qu'elle est à jour dans ce contexte
        current_perfo_allocation = df_allocations[~df_allocations['Type'].isin(
            ["Fonds en Euros", "Trésorerie Régulière"])]['+/- value (en €)'].sum()
        
        st.write(f"- Performance financière totale (des contrats inclus): {sum_perf_financiere:,.0f} €")
        st.write(f"- Performance allocation calculée (hors Fonds Euros/Tréso, sur tous les contrats): {current_perfo_allocation:,.0f} €")
        
        # S'assurer que les colonnes existent avant de calculer
        if 'Performance financière en euros (perf du contrat)' in aggregation_contrat.columns and \
           'Performance allocation' in aggregation_contrat.columns:
            
            # Utiliser les valeurs agrégées de aggregation_contrat pour le calcul de la perf embarquée affichée
            agg_sum_perf_financiere = aggregation_contrat['Performance financière en euros (perf du contrat)'].iloc[0]
            agg_perf_allocation = aggregation_contrat['Performance allocation'].iloc[0]
            
            calc_perf_embarquee = agg_sum_perf_financiere - agg_perf_allocation
            st.write(f"- Performance embarquée (calculée pour le waterfall) = {agg_sum_perf_financiere:,.0f} € - {agg_perf_allocation:,.0f} € = {calc_perf_embarquee:,.0f} €")
            
            if 'Performance embarquée' in aggregation_contrat.columns:
                 st.write(f"- Performance embarquée (assignée à aggregation_contrat): {aggregation_contrat['Performance embarquée'].iloc[0]:,.0f} €")
            else:
                st.write("- Colonne 'Performance embarquée' non trouvée dans aggregation_contrat.")
        else:
            st.write("- Colonnes nécessaires pour le calcul de la performance embarquée manquantes dans `aggregation_contrat`.")
    else:
        st.write("Aucune donnée pour calculer la performance embarquée (soit `aggregation_contrat` est vide, soit `df_contrats_pour_waterfall` est vide).")
    st.divider()

    # BLOC DE DÉBOGAGE 2 (aggregation_contrat avant sélection et melt)
    st.write("**`aggregation_contrat` (DataFrame agrégé avant sélection finale des colonnes pour `melt`)**")
    # Afficher une version temporaire de aggregation_contrat avant la sélection finale des colonnes
    if not df_contrats_pour_waterfall.empty:
        temp_aggregation_contrat_debug = df_contrats_pour_waterfall[['Montant total des versements bruts',
                                       'Montant total des versements nets', 'Valorisation',
                                       'Performance financière en euros (perf du contrat)',
                                       'Montant total des rachats bruts'
                                       ]].sum().to_frame().transpose()
        if not temp_aggregation_contrat_debug.empty:
            temp_aggregation_contrat_debug['Frais'] = temp_aggregation_contrat_debug['Montant total des versements bruts'] - temp_aggregation_contrat_debug['Montant total des versements nets']
            temp_aggregation_contrat_debug['Frais'] = - temp_aggregation_contrat_debug['Frais']
            temp_aggregation_contrat_debug['Rachats_calc_debug'] = -temp_aggregation_contrat_debug['Montant total des rachats bruts']
            temp_aggregation_contrat_debug['Solde Net Mouvements_calc_debug'] = temp_aggregation_contrat_debug['Montant total des versements nets'] + temp_aggregation_contrat_debug['Rachats_calc_debug']
            # Recalcul perfo_allocation et perf_embarquee pour ce point de débogage
            current_perfo_allocation_debug = df_allocations[~df_allocations['Type'].isin(["Fonds en Euros", "Trésorerie Régulière"])]['+/- value (en €)'].sum()
            temp_aggregation_contrat_debug['Performance allocation_calc_debug'] = current_perfo_allocation_debug
            temp_aggregation_contrat_debug['Performance embarquée_calc_debug'] = temp_aggregation_contrat_debug['Performance financière en euros (perf du contrat)'] - temp_aggregation_contrat_debug['Performance allocation_calc_debug']
            st.dataframe(temp_aggregation_contrat_debug.style.format("{:,.0f} €", na_rep='-'))
        else:
            st.write("`temp_aggregation_contrat_debug` est vide.")
    else:
        st.write("`df_contrats_pour_waterfall` est vide, impossible de générer `temp_aggregation_contrat_debug`.")
    st.divider()

    # BLOC DE DÉBOGAGE 3 (aggregation_contrat après sélection des colonnes)
    st.write("**`aggregation_contrat` (DataFrame final prêt pour `melt`)**")
    st.dataframe(aggregation_contrat.style.format("{:,.0f} €", na_rep='-'))
    st.divider()

    # BLOC DE DÉBOGAGE 4 (aggregation_contrat_melted)
    if not aggregation_contrat.empty:
        st.write("**`aggregation_contrat_melted` (données finales pour le graphique)**")
        # Le melt est déjà fait plus haut, on réutilise aggregation_contrat_melted
        st.dataframe(aggregation_contrat_melted.style.format({'value': "{:,.0f} €"}, na_rep='-'))
    else:
        st.write("`aggregation_contrat` est vide, donc `aggregation_contrat_melted` n'a pas été généré.")
# --- FIN SECTION DE DÉBOGAGE ---
