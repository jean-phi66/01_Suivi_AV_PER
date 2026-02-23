#!/bin/bash

# Script de lancement de l'application Suivi AV/PER
# Utilisation : 
#   ./run_app.sh                 # Mode normal
#   ./run_app.sh --demo          # Mode démo

# Définir le répertoire de base
APP_DIR="/Users/jean-philippenavarro/Documents/10_CGP/20_Outils - Simulateurs/01_Suivi_AV_PER"

# Vérifier les paramètres
if [[ "$1" == "--demo" ]]; then
    echo "🎯 Lancement en mode DÉMONSTRATION..."
    export DEMO_MODE=true
    streamlit run "$APP_DIR/multi_page.py" -- --demo
else
    echo "📊 Lancement en mode NORMAL (données réelles)..."
    streamlit run "$APP_DIR/multi_page.py"
fi
