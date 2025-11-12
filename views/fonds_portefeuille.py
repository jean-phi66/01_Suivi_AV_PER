import streamlit as st
from streamlit import session_state as ss
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

st.title("📊 Fonds du portefeuille")

df_allocations = ss['df_allocations']

# Configuration des critères de classement
st.header("Configuration")
col1, col2 = st.columns(2)

with col1:
    critere_classement = st.radio(
        "Critère de classement des fonds",
        options=["Nombre d'utilisations", "Encours total"],
        help="Choisissez comment classer les fonds : par nombre de contrats qui les utilisent ou par l'encours total investi"
    )

with col2:
    n_fonds = st.number_input(
        "Nombre de fonds à afficher séparément",
        min_value=1,
        max_value=50,
        value=10,
        help="Les n fonds les plus représentés selon le critère choisi seront affichés séparément, les autres seront regroupés dans 'Autres'"
    )

# Analyse des fonds selon le critère sélectionné
if critere_classement == "Nombre d'utilisations":
    # Compter le nombre d'utilisations (lignes) par fonds
    fonds_stats = df_allocations.groupby(['Support', 'Code ISIN']).agg({
        'Numéro contrat': 'count',  # Nombre d'utilisations
        'Encours en €': 'sum',      # Encours total
        'Type': 'first'             # Type de fonds
    }).reset_index()
    
    fonds_stats.rename(columns={'Numéro contrat': 'Nb_utilisations'}, inplace=True)
    fonds_stats = fonds_stats.sort_values('Nb_utilisations', ascending=False)
    
    critere_colonne = 'Nb_utilisations'
    critere_label = "Nombre d'utilisations"
    
else:  # Encours total
    # Sommer l'encours par fonds
    fonds_stats = df_allocations.groupby(['Support', 'Code ISIN']).agg({
        'Numéro contrat': 'count',  # Nombre d'utilisations
        'Encours en €': 'sum',      # Encours total
        'Type': 'first'             # Type de fonds
    }).reset_index()
    
    fonds_stats.rename(columns={'Numéro contrat': 'Nb_utilisations'}, inplace=True)
    fonds_stats = fonds_stats.sort_values('Encours en €', ascending=False)
    
    critere_colonne = 'Encours en €'
    critere_label = "Encours total"

# Sélection des top N fonds (déplacé ici pour calculer les KPIs)
top_n_fonds = fonds_stats.head(n_fonds).copy()
autres_fonds = fonds_stats.iloc[n_fonds:].copy()

# Calculs pour les KPIs
encours_total_portefeuille = fonds_stats['Encours en €'].sum()
encours_fonds_selectionnes = top_n_fonds['Encours en €'].sum()
ratio_encours_selectionnes = (encours_fonds_selectionnes / encours_total_portefeuille * 100) if encours_total_portefeuille > 0 else 0

# Affichage des statistiques générales
st.header("Vue d'ensemble")
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Nombre total de fonds", len(fonds_stats))

with col2:
    st.metric("Encours fonds sélectionnés", f"{encours_fonds_selectionnes:,.2f} €")

with col3:
    st.metric("Ratio vs encours total", f"{ratio_encours_selectionnes:.1f}%")

with col4:
    st.metric("Nombre de contrats", df_allocations['Numéro contrat'].nunique())

# Préparation des données pour le treemap
treemap_data = []

# Calculer le total pour les pourcentages
if critere_classement == "Nombre d'utilisations":
    total_valeur = fonds_stats['Nb_utilisations'].sum()
else:
    total_valeur = fonds_stats['Encours en €'].sum()

# Ajouter les top N fonds
for _, fonds in top_n_fonds.iterrows():
    valeur = fonds[critere_colonne]
    pourcentage = (valeur / total_valeur * 100) if total_valeur > 0 else 0
    
    treemap_data.append({
        'Support': fonds['Support'],
        'Code ISIN': fonds['Code ISIN'],
        'Type_fonds': fonds['Type'],  # Niveau 1 - Type de fonds
        'Nom_fonds': fonds['Support'],  # Niveau 2 - Nom du fonds
        'Valeur': valeur,
        'Pourcentage': pourcentage,
        'Encours': fonds['Encours en €'],
        'Nb_utilisations': fonds['Nb_utilisations'],
        'Type': fonds['Type']
    })

# Ajouter la catégorie "Non sélectionnés" si il y a des fonds en plus
if len(autres_fonds) > 0:
    valeur_autres = autres_fonds[critere_colonne].sum()
    pourcentage_autres = (valeur_autres / total_valeur * 100) if total_valeur > 0 else 0
    
    treemap_data.append({
        'Support': 'Autres fonds',
        'Code ISIN': 'N/A',
        'Type_fonds': 'Non sélectionnés',  # Niveau 1 - Catégorie spécifique pour les fonds non sélectionnés
        'Nom_fonds': f'{len(autres_fonds)} autres fonds',  # Niveau 2 - Indication du nombre de fonds regroupés
        'Valeur': valeur_autres,
        'Pourcentage': pourcentage_autres,
        'Encours': autres_fonds['Encours en €'].sum(),
        'Nb_utilisations': autres_fonds['Nb_utilisations'].sum(),
        'Type': 'Divers'
    })

treemap_df = pd.DataFrame(treemap_data)

# Création du treemap
st.header(f"Répartition des {n_fonds} fonds les plus représentés")

# Création du treemap avec pourcentages et regroupement par type
fig_treemap = px.treemap(
    treemap_df,
    path=['Type_fonds', 'Nom_fonds'],  # Hiérarchie: Type de fonds > Nom du fonds
    values='Valeur',
    title=f"Treemap des fonds par {critere_label.lower()} (regroupés par type)",
    hover_data={
        'Encours': ':,.2f',
        'Nb_utilisations': True,
        'Pourcentage': ':.1f',
        'Type': True
    }
)

if critere_classement == "Nombre d'utilisations":
    fig_treemap.update_traces(
        hovertemplate='<b>%{label}</b><br>' +
                     f'{critere_label}: %{{value}}<br>' +
                     'Pourcentage: %{customdata[2]:.1f}%<br>' +
                     'Encours: %{customdata[0]:,.2f} €<br>' +
                     'Utilisations: %{customdata[1]}<br>' +
                     'Type: %{customdata[3]}<extra></extra>',
        customdata=treemap_df[['Encours', 'Nb_utilisations', 'Pourcentage', 'Type']].values,
        texttemplate="<b>%{label}</b><br>%{customdata[2]:.1f}%"
    )
else:
    fig_treemap.update_traces(
        hovertemplate='<b>%{label}</b><br>' +
                     f'{critere_label}: %{{value:,.2f}} €<br>' +
                     'Pourcentage: %{customdata[2]:.1f}%<br>' +
                     'Utilisations: %{customdata[1]}<br>' +
                     'Type: %{customdata[3]}<extra></extra>',
        customdata=treemap_df[['Encours', 'Nb_utilisations', 'Pourcentage', 'Type']].values,
        texttemplate="<b>%{label}</b><br>%{customdata[2]:.1f}%"
    )

fig_treemap.update_layout(height=600)
st.plotly_chart(fig_treemap, use_container_width=True)

# Tableau détaillé des top N fonds
st.header(f"Détail des {n_fonds} fonds les plus représentés")
st.dataframe(
    top_n_fonds,
    column_config={
        "Support": "Nom du fonds",
        "Code ISIN": "Code ISIN",
        "Encours en €": st.column_config.NumberColumn(
            "Encours total",
            format="%.2f €"
        ),
        "Nb_utilisations": st.column_config.NumberColumn(
            "Nb d'utilisations",
            format="%d"
        ),
        "Type": "Type de fonds"
    },
    hide_index=True,
    use_container_width=True
)

# Export des codes ISIN
st.header("🔽 Export des codes ISIN")

# Filtre par type de fonds pour l'export
st.subheader("Filtre par type de fonds")
types_disponibles = sorted(top_n_fonds['Type'].unique())
types_selectionnes = st.multiselect(
    "Types de fonds à inclure dans l'export",
    options=types_disponibles,
    default=types_disponibles,  # Par défaut, tous les types sont sélectionnés
    help="Désélectionnez les types de fonds que vous souhaitez exclure de l'export des codes ISIN"
)

# Filtrer les fonds selon les types sélectionnés
if types_selectionnes:
    fonds_filtres = top_n_fonds[top_n_fonds['Type'].isin(types_selectionnes)]
else:
    fonds_filtres = pd.DataFrame()  # DataFrame vide si aucun type sélectionné

# Générer la liste des codes ISIN des fonds filtrés
codes_isin = fonds_filtres['Code ISIN'].dropna().tolist()
codes_isin_str = '; '.join(codes_isin)

# Afficher dans une zone de texte copiable
if types_selectionnes:
    st.subheader(f"Codes ISIN des {len(codes_isin)} fonds sélectionnés")
    
    # Affichage des statistiques par type dans un expandeur
    if len(fonds_filtres) > 0:
        with st.expander("📊 Statistiques détaillées"):
            col1, col2 = st.columns(2)
            with col1:
                st.write("**Répartition par type :**")
                repartition_types = fonds_filtres['Type'].value_counts()
                for type_fonds, count in repartition_types.items():
                    st.write(f"- {type_fonds}: {count} fonds")
            
            with col2:
                st.write("**Statistiques :**")
                st.write(f"- Encours total: {fonds_filtres['Encours en €'].sum():,.2f} €")
                st.write(f"- Codes ISIN disponibles: {len(codes_isin)}")
                codes_manquants = len(fonds_filtres) - len(codes_isin)
                if codes_manquants > 0:
                    st.write(f"- Codes ISIN manquants: {codes_manquants}")
    
    st.text_area(
        "Codes ISIN (séparés par des point-virgules)",
        value=codes_isin_str,
        height=150,
        help="Sélectionnez tout le texte (Ctrl+A) puis copiez (Ctrl+C / Cmd+C)"
    )
else:
    st.warning("⚠️ Aucun type de fonds sélectionné. Choisissez au moins un type pour générer l'export.")



# Affichage des "Autres" si pertinent
if len(autres_fonds) > 0:
    with st.expander(f"📋 Détail des {len(autres_fonds)} autres fonds"):
        st.dataframe(
            autres_fonds,
            column_config={
                "Support": "Nom du fonds",
                "Code ISIN": "Code ISIN", 
                "Encours en €": st.column_config.NumberColumn(
                    "Encours total",
                    format="%.2f €"
                ),
                "Nb_utilisations": st.column_config.NumberColumn(
                    "Nb d'utilisations",
                    format="%d"
                ),
                "Type": "Type de fonds"
            },
            hide_index=True,
            use_container_width=True
        )
        
        # Statistiques des "Autres"
        st.write(f"**Statistiques des 'Autres' :**")
        st.write(f"- Nombre de fonds : {len(autres_fonds)}")
        st.write(f"- Encours total : {autres_fonds['Encours en €'].sum():,.2f} €")
        st.write(f"- Utilisations totales : {autres_fonds['Nb_utilisations'].sum()}")