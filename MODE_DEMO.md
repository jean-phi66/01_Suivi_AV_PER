# 🎯 Mode Démonstration - Guide Complet

## Vue d'ensemble

Un mode démonstration a été ajouté à l'application pour permettre une présentation rapide sans données réelles. Le mode démo charge automatiquement des fichiers CSV avec des données fictives anonymisées.

## 📁 Fichiers ajoutés/modifiés

### Nouveaux fichiers :
- **`config.py`** - Configuration centralisée avec détection du mode démo
- **`run_app.sh`** - Script de lancement avec option `--demo`
- **`LANCEMENT.md`** - Guide d'utilisation

### Fichiers modifiés :
- **`multi_page.py`** - Affiche un badge quand le mode démo est activé
- **`views/data_ingestion.py`** - Charge les données de démo au lieu des données réelles

## 🚀 Utilisation

### Option 1 : Ligne de commande directe
```bash
# Mode normal (données réelles)
streamlit run multi_page.py

# Mode démo (données fictives)
streamlit run multi_page.py -- --demo
```

### Option 2 : Script de lancement
```bash
# Mode normal
./run_app.sh

# Mode démo
./run_app.sh --demo
```

### Option 3 : Variable d'environnement
```bash
# Mode démo via variable d'environnement
DEMO_MODE=true streamlit run multi_page.py
```

## 📊 Données de démonstration

### Fichiers utilisés :
- `00_Exports/DEMO_Export_selection_actifs.csv` (45 contrats fictifs)
- `00_Exports/DEMO_Export_situations_detaillees.csv` (détail des allocations)

### Contenu simulé :
- **Noms de clients** : Martin Sophie, Bernard Thomas, Dubois Marie, etc.
- **Contrats** : Assurance-vie, PER, PEA, Comptes titres, Livrets
- **Partenaires** : SURAVENIR, Apicil, Eres, Vie Plus
- **Performances** : Entre -7% et +30% pour les contrats
- **Montants** : Entre 12k€ et 156k€

## 🎨 Indicateurs visuels

Quand le mode démo est activé :
1. Un badge d'avertissement apparaît en haut de la page d'accueil
2. Le message "Mode de démonstration activé" s'affiche
3. Un message d'information confirme l'utilisation des données de démo

## 🔐 Sécurité et confidentialité

- ✅ Les données réelles restent complètement inchangées
- ✅ Aucune donnée réelle dans les fichiers de démo
- ✅ Les noms et valeurs sont complètement anonymisés
- ✅ Parfait pour les démonstrations client et les tests

## 🛠️ Fonctionnement technique

### config.py
Détecte le mode démo via :
1. Argument de ligne de commande : `--demo`
2. Variable d'environnement : `DEMO_MODE=true`

### data_ingestion.py
- Vérifie si `DEMO_MODE` est activé
- Si oui → Charge les fichiers DEMO_*.csv
- Si non → Charge les fichiers des dossiers réels

## 📝 Exemple d'utilisation en terminal

```bash
# Se déplacer dans le répertoire
cd /Users/jean-philippenavarro/Documents/10_CGP/20_Outils\ -\ Simulateurs/01_Suivi_AV_PER

# Lancer en mode démo
streamlit run multi_page.py -- --demo

# Ou avec le script
./run_app.sh --demo
```

## ✨ Avantages du mode démo

- 🎯 Démonstrations rapides sans données sensibles
- 📊 Structure identique aux données réelles (même format CSV)
- 🔄 Facile de basculer entre mode réel et démo
- 👥 Données de test pour onboarding de nouveaux utilisateurs
- 🧪 Environnement de test sans risque
