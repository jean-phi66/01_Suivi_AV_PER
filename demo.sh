#!/bin/bash

# Script de démonstration rapide
# Permet de tester l'application avec les données de démo

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📊 Application Suivi AV/PER - Mode Démonstration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

APP_DIR="/Users/jean-philippenavarro/Documents/10_CGP/20_Outils - Simulateurs/01_Suivi_AV_PER"

echo "✓ Répertoire : $APP_DIR"
echo "✓ Mode : DÉMONSTRATION"
echo "✓ Données : 45 contrats fictifs"
echo ""
echo "🚀 Lancement de l'application..."
echo ""

cd "$APP_DIR"
export DEMO_MODE=true
streamlit run multi_page.py -- --demo
