import streamlit as st
from streamlit import session_state as ss
import pandas as pd
import zipfile
import io
import time
from datetime import datetime

# Import du module de génération de rapport
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from report_generator import generate_rapport_pdf
from reporting_helpers import build_evolution_figure, build_kpi_overrides, build_tri_figure, resolve_payment_source
from tri_integration import load_tri_analyses, match_tri_analyses_to_contracts


def generate_figures_for_contract(
    df_allocations_client,
    df_contrat_selected,
    contrat_num,
    df_contrats_all,
    df_contrat_agg,
    tri_contracts_map,
    preferred_source,
):
    """Génère les figures nécessaires pour un contrat en utilisant EXACTEMENT les mêmes fonctions que les pages individuelles"""
    import plotly.express as px
    import plotly.graph_objects as go
    import pandas as pd
    import sys
    import os
    
    # Ajouter le répertoire racine au path pour importer les modules
    root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root_path not in sys.path:
        sys.path.append(root_path)
    
    figures = {}
    tri_analysis = tri_contracts_map.get(str(contrat_num))
    source_context = resolve_payment_source(df_contrat_selected, tri_analysis, preferred_source)
    
    try:
        # Figure de typologie (composition.py) - MÊME CODE QUE DANS COMPOSITION.PY
        if 'Type' in df_allocations_client.columns and len(df_allocations_client) > 0:
            fig_typologie = px.pie(df_allocations_client,
                                 values='Encours en €', names='Type', hole=.5)
            fig_typologie.update_layout(title="Typologie des supports")
            figures['fig_typologie'] = fig_typologie
        
        # Figure supports (composition.py) - MÊME CODE QUE DANS COMPOSITION.PY
        if 'Support' in df_allocations_client.columns and len(df_allocations_client) > 0:
            fig_supports = px.pie(df_allocations_client,
                                values='Encours en €', names='Support', hole=.5)
            fig_supports.update_layout(title="Répartition par support")
            figures['fig_supports'] = fig_supports
        
        # Figures SRI (analyse_SRI.py) - MÊME CODE QUE DANS D'AUTRES PAGES
        if 'SRI' in df_allocations_client.columns and len(df_allocations_client) > 0:
            try:
                from analyse_SRI import generate_fig_SRI
                _, fig_distribution_SRI, fig_SRI_contrat = generate_fig_SRI(df_allocations_client)
                figures['fig_distribution_SRI'] = fig_distribution_SRI
                figures['fig_SRI_contrat'] = fig_SRI_contrat
            except Exception as e:
                print(f"Erreur lors de la génération des figures SRI: {e}")
                figures['fig_distribution_SRI'] = None
                figures['fig_SRI_contrat'] = None
        
        # Figures Waterfall - REPRENDRE EXACTEMENT LE CODE DE PERFO.PY
        try:
            from waterfall_graphs import generate_contrats_waterfall, generate_allocations_waterfall
            
            # Waterfall contrat - MÊME LOGIQUE QUE DANS PERFO.PY
            if not df_contrat_selected.empty and 'df_allocations' in ss:
                # Préparer les données exactement comme dans perfo.py
                df_contrats = df_contrats_all.copy()
                df_allocations = ss['df_allocations']
                
                # Détecter si c'est un contrat PER pour appliquer la réduction fiscale automatiquement
                is_per_contract = False
                add_reduction_IR = False
                IR_num = 0.0
                
                if ('Enveloppe' in df_contrat_selected.columns and 
                    'PER' in str(df_contrat_selected['Enveloppe'].iloc[0]).upper()):
                    is_per_contract = True
                    add_reduction_IR = True  # Automatiquement activer pour les PER en batch
                    IR_num = 0.30  # TMI 30% par défaut pour les rapports par lot
                
                # Même préparation que dans perfo.py (lignes 87-99)
                df_summary_allocations = df_allocations[~df_allocations['Type'].isin(["Fonds en Euros"])]
                df_summary_allocations = df_summary_allocations.groupby(
                    'Numéro contrat')['+/- value (en €)'].sum().reset_index('Numéro contrat')
                
                df_contrats_upd = pd.merge(df_contrats, df_summary_allocations,
                                         how='left', left_on='N° de contrat', right_on='Numéro contrat')
                df_contrats_upd['Performance embarquée'] = df_contrats_upd[
                    'Performance financière en euros (perf du contrat)'] - df_contrats_upd['+/- value (en €)']
                df_contrats_upd.rename(
                    columns={'+/- value (en €)': 'Performance allocation'}, inplace=True)

                if (
                    source_context.get('source_effective') == "Releve d'operations TRI"
                    and source_context.get('gross_used') is not None
                    and source_context.get('net_used') is not None
                ):
                    mask_contrat = df_contrats_upd['N° de contrat'].astype(str) == str(contrat_num)
                    if mask_contrat.any():
                        gross_used = float(source_context['gross_used'])
                        net_used = float(source_context['net_used'])
                        df_contrats_upd.loc[mask_contrat, 'Montant total des versements bruts'] = gross_used
                        df_contrats_upd.loc[mask_contrat, 'Montant total des versements nets'] = net_used
                        df_contrats_upd.loc[mask_contrat, 'Frais'] = net_used - gross_used
                        df_contrats_upd.loc[mask_contrat, 'Performance financière en euros (perf du contrat)'] = (
                            df_contrats_upd.loc[mask_contrat, 'Valorisation'] - net_used
                        )
                        df_contrats_upd.loc[mask_contrat, 'Performance embarquée'] = (
                            df_contrats_upd.loc[mask_contrat, 'Performance financière en euros (perf du contrat)']
                            - df_contrats_upd.loc[mask_contrat, 'Performance allocation']
                        )
                
                # Générer le waterfall avec les mêmes paramètres que dans perfo.py
                # IMPORTANT: Utiliser add_reduction_IR et IR_num pour les PER
                df_client_waterfall, measure = generate_contrats_waterfall(
                    df_contrats_upd, contrat_num, add_reduction_IR, IR_num)
                
                # EXACTEMENT le même code que dans perfo.py (lignes 105-119)
                fig_waterfall_contract = go.Figure(go.Waterfall(
                    name="20", orientation="v",
                    measure=measure,
                    x=df_client_waterfall['variable'],
                    textposition="auto",
                    text=df_client_waterfall['value'].apply(lambda x: str(int(round(x, 0)))),
                    y=df_client_waterfall['value'],
                    connector={"line": {"color": "rgb(63, 63, 63)"}},
                    cliponaxis=False
                ))
                
                # Titre adapté selon le type de contrat
                if is_per_contract:
                    title = "Situation contrat PER (avec avantage fiscal 30%)"
                else:
                    title = "Situation contrat"
                    
                fig_waterfall_contract.update_layout(
                    title=title,
                    showlegend=False
                )
                figures['fig_waterfall_contract'] = fig_waterfall_contract
            else:
                figures['fig_waterfall_contract'] = None
            
            # Waterfall allocation - EXACTEMENT le même code que dans perfo.py (lignes 121-137)
            if len(df_allocations_client) > 0 and 'df_allocations' in ss:
                df_allocations_waterfall = generate_allocations_waterfall(
                    ss['df_allocations'], contrat_num)
                
                fig_waterfall_allocation = go.Figure(go.Waterfall(
                    name="20", orientation="v",
                    measure=df_allocations_waterfall['measure'],
                    x=df_allocations_waterfall['Support'],
                    textposition="auto",
                    text=df_allocations_waterfall['+/- value (en €)'].apply(
                        lambda x: str(int(round(x, 0)))),
                    y=df_allocations_waterfall['+/- value (en €)'],
                    connector={"line": {"color": "rgb(63, 63, 63)"}},
                    cliponaxis=False
                ))
                fig_waterfall_allocation.update_layout(
                    title="Performance allocation",
                    showlegend=False,
                )
                figures['fig_waterfall_allocation'] = fig_waterfall_allocation
            else:
                figures['fig_waterfall_allocation'] = None
                
        except Exception as e:
            print(f"Erreur lors de la génération des figures waterfall: {e}")
            figures['fig_waterfall_contract'] = None
            figures['fig_waterfall_allocation'] = None
        
        # Figure évolution - REPRENDRE EXACTEMENT LE CODE DE PERFO.PY
        try:
            # Vérifier que les données historiques sont disponibles
            if not df_contrat_selected.empty:
                df_historical_for_contract = df_contrat_agg[df_contrat_agg['N° de contrat'] == contrat_num].copy()
                df_current_for_contract = df_contrat_selected.copy()
                add_reduction_ir = (
                    'Enveloppe' in df_contrat_selected.columns and 'PER' in str(df_contrat_selected['Enveloppe'].iloc[0]).upper()
                )
                ir_num = 0.30 if add_reduction_ir else 0.0
                figures['fig_evol'] = build_evolution_figure(
                    df_historical_for_contract,
                    df_current_for_contract,
                    contrat_num,
                    tri_analysis,
                    source_context,
                    add_reduction_ir=add_reduction_ir,
                    ir_num=ir_num,
                )
                figures['fig_tri'] = build_tri_figure(
                    df_historical_for_contract,
                    df_current_for_contract,
                    contrat_num,
                    tri_analysis,
                )
            else:
                figures['fig_evol'] = None
                figures['fig_tri'] = None
                
        except Exception as e:
            print(f"Erreur lors de la génération du graphique d'évolution: {e}")
            figures['fig_evol'] = None
            figures['fig_tri'] = None

        figures['kpi_overrides'] = build_kpi_overrides(df_contrat_selected, source_context)
        figures['source_context'] = source_context
        
        # S'assurer que tous les graphiques attendus sont définis
        required_figures = ['fig_typologie', 'fig_supports', 'fig_waterfall_contract', 
                          'fig_waterfall_allocation', 'fig_distribution_SRI', 
                          'fig_SRI_contrat', 'fig_evol', 'fig_tri', 'kpi_overrides', 'source_context']
        
        for fig_name in required_figures:
            if fig_name not in figures:
                figures[fig_name] = None
        
    except Exception as e:
        st.warning(f"Erreur lors de la génération des figures: {str(e)}")
        # Retourner des figures vides en cas d'erreur
        figures = {key: None for key in ['fig_typologie', 'fig_supports', 'fig_waterfall_contract', 
                                       'fig_waterfall_allocation', 'fig_distribution_SRI', 
                                       'fig_SRI_contrat', 'fig_evol', 'fig_tri', 'kpi_overrides', 'source_context']}
    
    return figures


def generate_batch_reports(contrats_selectionnes, format_fichiers, inclure_timestamp, preferred_source):
    """Génère les rapports pour tous les contrats sélectionnés"""
    
    # Récupérer les DataFrames depuis la session
    df_contrats = ss['df_contrats']
    df_allocations = ss['df_allocations']
    df_contrat_agg = ss.get('df_contrat_agg_filtered', ss.get('df_contrat_agg', pd.DataFrame()))

    tri_contracts_df, tri_contracts_map = match_tri_analyses_to_contracts(
        load_tri_analyses(),
        df_contrats[["N° de contrat", "Titulaire(s)", "Enveloppe", "Partenaire"]].drop_duplicates().copy(),
    )
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    rapports_generes = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S") if inclure_timestamp else ""
    
    total_contrats = len(contrats_selectionnes)
    
    for index, contrat_row in contrats_selectionnes.iterrows():
        try:
            # Mise à jour du statut
            contrat_num = contrat_row['N° de contrat']
            client_name = contrat_row['Titulaire(s)']
            
            status_text.text(f"Génération du rapport pour {client_name} - Contrat {contrat_num}...")
            
            # Récupérer les données du contrat spécifique
            df_contrat_selected = df_contrats[df_contrats['N° de contrat'] == contrat_num].copy()
            
            # Chercher dans df_allocations avec la bonne colonne
            if 'Numéro contrat' in df_allocations.columns:
                df_allocations_client = df_allocations[df_allocations['Numéro contrat'] == contrat_num].copy()
            elif 'Contrat' in df_allocations.columns:
                df_allocations_client = df_allocations[df_allocations['Contrat'] == contrat_num].copy()
            else:
                st.warning(f"⚠️ Colonne de liaison contrat non trouvée pour le contrat {contrat_num}")
                continue
            
            if df_contrat_selected.empty or df_allocations_client.empty:
                st.warning(f"⚠️ Données manquantes pour le contrat {contrat_num}")
                continue
            
            # Générer les figures nécessaires
            figures = generate_figures_for_contract(
                df_allocations_client,
                df_contrat_selected,
                contrat_num,
                df_contrats,
                df_contrat_agg,
                tri_contracts_map,
                preferred_source,
            )
            
            # Générer le PDF
            pdf_data = generate_rapport_pdf(
                client_name=client_name,
                contrat_num=contrat_num,
                df_contrat_sel=df_contrat_selected,
                fig_typologie_plot=figures.get('fig_typologie'),
                fig_supports_plot=figures.get('fig_supports'),
                fig_waterfall_contract_plot=figures.get('fig_waterfall_contract'),
                fig_waterfall_allocation_plot=figures.get('fig_waterfall_allocation'),
                fig_distribution_SRI_plot=figures.get('fig_distribution_SRI'),
                fig_SRI_contrat_plot=figures.get('fig_SRI_contrat'),
                fig_evol_plot=figures.get('fig_evol'),
                df_alloc_client_data=df_allocations_client,
                fig_tri_plot=figures.get('fig_tri'),
                kpi_overrides=figures.get('kpi_overrides'),
            )
            
            # Créer le nom de fichier
            nom_fichier_base = f"{client_name} - {contrat_num} - Rapport"
            if timestamp:
                nom_fichier = f"{nom_fichier_base}_{timestamp}.pdf"
            else:
                nom_fichier = f"{nom_fichier_base}.pdf"
            
            rapports_generes.append({
                'nom_fichier': nom_fichier,
                'data': pdf_data,
                'client': client_name,
                'contrat': contrat_num
            })
            
            # Mettre à jour la barre de progression
            progress = (len(rapports_generes)) / total_contrats
            progress_bar.progress(progress)
            
            # Petit délai pour éviter de surcharger le système
            time.sleep(0.1)
            
        except Exception as e:
            st.error(f"❌ Erreur lors de la génération du rapport pour {client_name} - {contrat_num}: {str(e)}")
            continue
    
    # Finalisation
    progress_bar.progress(1.0)
    status_text.text("Génération terminée !")
    
    if rapports_generes:
        st.success(f"✅ {len(rapports_generes)} rapport(s) généré(s) avec succès !")
        
        if format_fichiers == "Archive ZIP":
            # Créer une archive ZIP
            zip_buffer = io.BytesIO()
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for rapport in rapports_generes:
                    zip_file.writestr(rapport['nom_fichier'], rapport['data'])
            
            zip_buffer.seek(0)
            
            # Bouton de téléchargement pour l'archive ZIP
            nom_archive = f"Rapports_Lot_{timestamp}.zip" if timestamp else "Rapports_Lot.zip"
            
            st.download_button(
                label="📦 Télécharger l'archive ZIP",
                data=zip_buffer.getvalue(),
                file_name=nom_archive,
                mime="application/zip",
                key="download_zip_reports"
            )
        
        else:
            # Afficher les boutons de téléchargement individuels
            st.subheader("Téléchargements individuels")
            
            for i, rapport in enumerate(rapports_generes):
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    st.text(f"📄 {rapport['client']} - Contrat {rapport['contrat']}")
                
                with col2:
                    st.download_button(
                        label="⬇️ Télécharger",
                        data=rapport['data'],
                        file_name=rapport['nom_fichier'],
                        mime="application/pdf",
                        key=f"download_individual_{i}"
                    )
    
    else:
        st.error("❌ Aucun rapport n'a pu être généré.")


# Interface utilisateur principale
st.title("Génération de rapports en lot")

# Vérifier que les données sont disponibles
if 'df_contrats' not in ss or 'df_allocations' not in ss:
    st.error("⚠️ Les données ne sont pas chargées. Veuillez d'abord aller sur la page d'ingestion des données.")
    st.stop()

def main():
    """Fonction principale de la page de génération de rapports par lot"""
    df_contrats = ss['df_contrats']
    df_allocations = ss['df_allocations']

    # Créer un DataFrame avec les informations des contrats pour la sélection
    # Joindre avec df_allocations pour récupérer les informations sur le type
    df_selection = df_contrats[['Titulaire(s)', 'N° de contrat', 'Enveloppe', 'Partenaire', 'Valorisation']].copy()

    # Récupérer le type dominant pour chaque contrat depuis df_allocations
    def get_contract_type(contrat_num):
        """Récupère le type dominant d'un contrat depuis ses allocations"""
        try:
            # Chercher d'abord par 'Numéro contrat' puis par 'Contrat' si la première colonne n'existe pas
            if 'Numéro contrat' in df_allocations.columns:
                df_contrat_alloc = df_allocations[df_allocations['Numéro contrat'] == contrat_num]
            elif 'Contrat' in df_allocations.columns:
                df_contrat_alloc = df_allocations[df_allocations['Contrat'] == contrat_num]
            else:
                return "N/A"
                
            if not df_contrat_alloc.empty and 'Type' in df_contrat_alloc.columns:
                # Prendre le type le plus fréquent ou le premier si égalité
                return df_contrat_alloc['Type'].mode().iloc[0] if len(df_contrat_alloc['Type'].mode()) > 0 else "N/A"
            return "N/A"
        except:
            return "N/A"

    # Déterminer le type pour chaque contrat
    if 'Enveloppe' in df_selection.columns:
        # Utiliser l'Enveloppe comme proxy pour le type si disponible
        df_selection['Type'] = df_selection['Enveloppe'].apply(lambda x: 
            "PER" if "PER" in str(x).upper() else 
            "AV" if any(keyword in str(x).upper() for keyword in ["AV", "ASSURANCE", "VIE"]) else 
            get_contract_type(df_selection[df_selection['Enveloppe'] == x]['N° de contrat'].iloc[0]) if not df_selection[df_selection['Enveloppe'] == x].empty else "N/A")
    else:
        # Si pas d'Enveloppe, essayer de récupérer depuis les allocations
        df_selection['Type'] = df_selection['N° de contrat'].apply(get_contract_type)

    df_selection['Valorisation_formatted'] = df_selection['Valorisation'].apply(lambda x: f"{x:,.0f} €".replace(",", " "))
    df_selection['Selection'] = False

    st.subheader("Sélection des contrats")

    # Filtres pour faciliter la sélection
    col1, col2, col3 = st.columns(3)

    with col1:
        # Filtre par titulaire
        titulaires_uniques = sorted(df_selection['Titulaire(s)'].unique())
        titulaires_selectionnes = st.multiselect(
            "Filtrer par titulaire(s)",
            options=titulaires_uniques,
            key="filtre_titulaires"
        )

    with col2:
        # Filtre par type de contrat
        types_uniques = sorted(df_selection['Type'].unique())
        types_selectionnes = st.multiselect(
            "Filtrer par type",
            options=types_uniques,
            key="filtre_types"
        )

    with col3:
        # Filtre par partenaire
        partenaires_uniques = sorted(df_selection['Partenaire'].unique())
        partenaires_selectionnes = st.multiselect(
            "Filtrer par partenaire",
            options=partenaires_uniques,
            key="filtre_partenaires"
        )

    # Appliquer les filtres
    df_filtre = df_selection.copy()

    if titulaires_selectionnes:
        df_filtre = df_filtre[df_filtre['Titulaire(s)'].isin(titulaires_selectionnes)]

    if types_selectionnes:
        df_filtre = df_filtre[df_filtre['Type'].isin(types_selectionnes)]

    if partenaires_selectionnes:
        df_filtre = df_filtre[df_filtre['Partenaire'].isin(partenaires_selectionnes)]

    # Initialiser les sélections dans le session state si pas encore fait
    if 'selections_batch' not in ss:
        ss['selections_batch'] = {}

    # Boutons de sélection rapide
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("Tout sélectionner", key="select_all"):
            # Sélectionner tous les contrats filtrés
            for idx in df_filtre.index:
                contrat_id = df_filtre.loc[idx, 'N° de contrat']
                ss['selections_batch'][contrat_id] = True
            st.rerun()

    with col2:
        if st.button("Tout désélectionner", key="deselect_all"):
            # Désélectionner tous les contrats filtrés
            for idx in df_filtre.index:
                contrat_id = df_filtre.loc[idx, 'N° de contrat']
                ss['selections_batch'][contrat_id] = False
            st.rerun()

    with col3:
        if st.button("Inverser la sélection", key="invert_selection"):
            # Inverser la sélection pour tous les contrats filtrés
            for idx in df_filtre.index:
                contrat_id = df_filtre.loc[idx, 'N° de contrat']
                current = ss['selections_batch'].get(contrat_id, False)
                ss['selections_batch'][contrat_id] = not current
            st.rerun()

    with col4:
        if st.button("Réinitialiser", key="reset_selections"):
            # Réinitialiser toutes les sélections
            ss['selections_batch'] = {}
            st.rerun()

    # Appliquer les sélections depuis le session state
    for idx in df_filtre.index:
        contrat_id = df_filtre.loc[idx, 'N° de contrat']
        df_filtre.loc[idx, 'Selection'] = ss['selections_batch'].get(contrat_id, False)

    # Configuration des colonnes pour l'affichage
    config = {
        'Selection': st.column_config.CheckboxColumn(
            'Sélectionner',
            help="Cochez pour inclure ce contrat dans la génération de rapports",
            default=False,
        ),
        'Valorisation_formatted': st.column_config.TextColumn(
            'Valorisation',
            help="Valorisation actuelle du contrat"
        )
    }

    # Tableau de sélection des contrats
    colonnes_affichage = ['Selection', 'Titulaire(s)', 'N° de contrat', 'Type', 'Partenaire', 'Valorisation_formatted']
    df_affichage = df_filtre[colonnes_affichage].copy()

    edited_df = st.data_editor(
        df_affichage,
        column_config=config,
        disabled=['Titulaire(s)', 'N° de contrat', 'Type', 'Partenaire', 'Valorisation_formatted'],
        hide_index=True,
        use_container_width=True,
        key="contrats_selector"
    )

    # Synchroniser les sélections manuelles avec le session state
    for idx in edited_df.index:
        contrat_id = edited_df.loc[idx, 'N° de contrat']
        selection_state = edited_df.loc[idx, 'Selection']
        ss['selections_batch'][contrat_id] = selection_state

    # Récupérer les contrats sélectionnés en utilisant le session state mis à jour
    contrats_selectionnes = edited_df[edited_df['Selection'] == True].copy()

    if len(contrats_selectionnes) > 0:
        st.success(f"✅ {len(contrats_selectionnes)} contrat(s) sélectionné(s)")
        
        # Afficher un aperçu des contrats sélectionnés
        with st.expander("Voir les contrats sélectionnés", expanded=False):
            st.dataframe(
                contrats_selectionnes[['Titulaire(s)', 'N° de contrat', 'Type', 'Partenaire', 'Valorisation_formatted']],
                hide_index=True,
                use_container_width=True
            )
        
        # Options de génération
        st.subheader("Options de génération")
        
        col1, col2 = st.columns(2)
        with col1:
            format_fichiers = st.radio(
                "Format de sortie",
                options=["Archive ZIP", "Fichiers séparés"],
                help="ZIP recommandé pour plusieurs contrats"
            )
        
        with col2:
            inclure_timestamp = st.checkbox(
                "Inclure un timestamp dans les noms de fichiers",
                value=True,
                help="Ajoute la date et l'heure aux noms des fichiers"
            )

        preferred_source = st.radio(
            "Source des versements pour les rapports",
            options=["CSV contrats", "Releve d'operations TRI"],
            horizontal=True,
            help="Si le relevé TRI n'est pas disponible pour un contrat, le rapport repasse automatiquement sur les valeurs CSV.",
        )
        
        # Bouton de génération
        if st.button("🚀 Générer les rapports", type="primary", key="generate_reports"):
            generate_batch_reports(contrats_selectionnes, format_fichiers, inclure_timestamp, preferred_source)
    else:
        st.info("Sélectionnez au moins un contrat pour générer des rapports.")

# Appeler la fonction principale seulement dans certains contextes
if __name__ == "__main__":
    # Exécution directe du script
    main()
elif hasattr(st, 'runtime') and st.runtime.exists():
    # Exécution dans le contexte Streamlit
    main()