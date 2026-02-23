"""
Petit script de test pour l'export PDF des filtres d'exposition.
Génère un fichier 00_Exports/Export_Exposition_Filtres_TEST.pdf
"""
import os
import pandas as pd

from report_generator import generate_exposition_filters_pdf

# Échantillon de données
contrats_resume = pd.DataFrame([
    {"Numéro contrat": "C0001", "Nom": "DUPONT", "Prénom": "JEAN", "Prestation": "AV", "Encours en €": 150000},
    {"Numéro contrat": "C0002", "Nom": "MARTIN", "Prénom": "ANNE", "Prestation": "PER", "Encours en €": 200000},
    {"Numéro contrat": "C0003", "Nom": "DURAND", "Prénom": "PAUL", "Prestation": "AV", "Encours en €": 80000},
])

fonds_selectionnes = ["Fonds A", "Fonds B", "Fonds C"]

df_allocations = pd.DataFrame([
    {"Numéro contrat": "C0001", "Support": "Fonds A", "Encours en €": 35000},
    {"Numéro contrat": "C0001", "Support": "Fonds C", "Encours en €": 15000},
    {"Numéro contrat": "C0002", "Support": "Fonds A", "Encours en €": 50000},
    {"Numéro contrat": "C0002", "Support": "Fonds B", "Encours en €": 30000},
    {"Numéro contrat": "C0002", "Support": "Fonds C", "Encours en €": 40000},
    {"Numéro contrat": "C0003", "Support": "Fonds B", "Encours en €": 12000},
])

pdf_bytes = generate_exposition_filters_pdf(
    contrats_resume=contrats_resume,
    fonds_selectionnes=fonds_selectionnes,
    df_allocations=df_allocations,
)

out_dir = os.path.join(os.path.dirname(__file__), "00_Exports")
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, "Export_Exposition_Filtres_TEST.pdf")

with open(out_path, "wb") as f:
    f.write(pdf_bytes)

print(f"PDF généré: {out_path}")
