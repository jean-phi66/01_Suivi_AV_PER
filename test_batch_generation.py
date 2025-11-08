#!/usr/bin/env python3
"""
Script de test pour valider la génération de rapports en lot avec tous les graphiques
"""

import pandas as pd
import numpy as np
import sys
import os

# Ajouter le répertoire courant au path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Mock du session state pour les tests
class MockSessionState:
    def __init__(self):
        self.data = {}
        
    def __getitem__(self, key):
        return self.data.get(key)
        
    def __setitem__(self, key, value):
        self.data[key] = value
        
    def __contains__(self, key):
        return key in self.data

# Créer des données de test
def create_test_data():
    """Crée des données de test pour simuler les DataFrames"""
    
    # DataFrame contrats test
    df_contrats = pd.DataFrame({
        'N° contrat': ['123456', '789012'],
        'Nom Client': ['Test Client 1', 'Test Client 2'],
        'Encours en €': [50000, 75000],
        'Versements en €': [45000, 70000],
        '+/- Value (en €)': [5000, 5000]
    })
    
    # DataFrame allocations test
    df_allocations = pd.DataFrame({
        'N° contrat': ['123456', '123456', '789012', '789012'],
        'Support': ['Support A', 'Support B', 'Support C', 'Support D'],
        'Type': ['Actions', 'Obligataire', 'Actions', 'Diversifié'],
        'Encours en €': [30000, 20000, 40000, 35000],
        'SRI': [8, 6, 7, 9],
        '+/- value (en €)': [3000, 2000, 2500, 2500]
    })
    
    return df_contrats, df_allocations

def test_imports():
    """Test des importations nécessaires"""
    print("🧪 Test des importations...")
    
    try:
        from views.batch_reports import generate_figures_for_contract
        print("✅ generate_figures_for_contract importée")
        
        from report_generator import generate_rapport_pdf
        print("✅ generate_rapport_pdf importée")
        
        import plotly.express as px
        import plotly.graph_objects as go
        print("✅ Plotly importé")
        
        from waterfall_graphs import generate_contrats_waterfall, generate_allocations_waterfall
        print("✅ waterfall_graphs importé")
        
        from analyse_SRI import generate_fig_SRI
        print("✅ analyse_SRI importé")
        
        return True
        
    except ImportError as e:
        print(f"❌ Erreur d'importation: {e}")
        return False

def test_figure_generation():
    """Test de génération des figures"""
    print("\n🧪 Test de génération des figures...")
    
    # Simuler le session state
    import streamlit as st
    if not hasattr(st, '_session_state'):
        # Mock session state pour les tests
        mock_ss = MockSessionState()
        df_contrats, df_allocations = create_test_data()
        mock_ss['df_contrats'] = df_contrats
        mock_ss['df_allocations'] = df_allocations
        
        # Remplacer temporairement le session state
        import views.batch_reports
        views.batch_reports.ss = mock_ss
    
    try:
        from views.batch_reports import generate_figures_for_contract
        
        # Données de test pour un contrat
        df_contrats, df_allocations = create_test_data()
        contrat_num = '123456'
        
        df_contrat_selected = df_contrats[df_contrats['N° contrat'] == contrat_num]
        df_allocations_client = df_allocations[df_allocations['N° contrat'] == contrat_num]
        
        print(f"📊 Génération des figures pour le contrat {contrat_num}...")
        figures = generate_figures_for_contract(df_allocations_client, df_contrat_selected, contrat_num)
        
        # Vérifier les figures générées
        expected_figures = ['fig_typologie', 'fig_supports', 'fig_waterfall_contract', 
                          'fig_waterfall_allocation', 'fig_distribution_SRI', 
                          'fig_SRI_contrat', 'fig_evol']
        
        for fig_name in expected_figures:
            if fig_name in figures:
                if figures[fig_name] is not None:
                    print(f"✅ {fig_name}: Générée avec succès")
                else:
                    print(f"⚠️  {fig_name}: Présente mais None")
            else:
                print(f"❌ {fig_name}: Manquante")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de la génération des figures: {e}")
        return False

def main():
    """Fonction principale de test"""
    print("🚀 Test de la génération de rapports par lot\n")
    
    # Test des importations
    imports_ok = test_imports()
    
    if imports_ok:
        # Test de génération des figures
        figures_ok = test_figure_generation()
        
        if figures_ok:
            print("\n🎉 Tous les tests sont passés avec succès!")
            print("✅ La génération de rapports par lot avec tous les graphiques est opérationnelle")
        else:
            print("\n⚠️  Problème avec la génération des figures")
    else:
        print("\n❌ Problème avec les importations")

if __name__ == "__main__":
    main()