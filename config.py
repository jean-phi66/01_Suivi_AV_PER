"""
Configuration pour l'application Suivi AV/PER
"""

import os
import sys

# Déterminer si le mode demo est activé
DEMO_MODE = "--demo" in sys.argv or os.getenv("DEMO_MODE", "False").lower() == "true"

# Chemins des fichiers
BASE_EXPORTS_PATH = '/Users/jean-philippenavarro/Documents/10_CGP/20_Outils - Simulateurs/01_Suivi_AV_PER/00_Exports/'

# Chemins pour les données réelles
REAL_DATA_CONTRATS_PATH = os.path.join(BASE_EXPORTS_PATH, '1_Selection_Actifs/')
REAL_DATA_ALLOCATIONS_PATH = os.path.join(BASE_EXPORTS_PATH, '2_Situations_Detaillées/')

# Chemins pour les données de démo
DEMO_DATA_CONTRATS_FILE = os.path.join(BASE_EXPORTS_PATH, 'DEMO_Export_selection_actifs.csv')
DEMO_DATA_ALLOCATIONS_FILE = os.path.join(BASE_EXPORTS_PATH, 'DEMO_Export_situations_detaillees.csv')
