# 🎯 Mode Démonstration - Intégration Complète

## 📋 Résumé des modifications

### ✅ 3 nouvelles lignes dans `multi_page.py`
- Import du module `config` pour détecter le mode démo
- Affichage d'un badge d'avertissement quand le mode démo est activé

### ✅ Modification de `views/data_ingestion.py`
- Import de `config` pour déterminer les chemins des fichiers
- Charge automatiquement les fichiers démo si le mode est activé
- Sinon, utilise les données réelles

### ✅ Nouveau fichier `config.py`
- Détecte le mode démo via argument `--demo` ou variable d'environnement `DEMO_MODE`
- Définit les chemins centralisés pour les données

### ✅ Scripts de lancement
- `run_app.sh` - Lancement flexible (normal ou démo)
- `demo.sh` - Lancement direct en mode démo

### ✅ Documentation
- `MODE_DEMO.md` - Guide complet du mode démo
- `LANCEMENT.md` - Instructions de lancement

## 🚀 Commandes principales

```bash
# Mode démo - 3 façons de lancer

# 1. Avec streamlit (directement)
cd /Users/jean-philippenavarro/Documents/10_CGP/20_Outils\ -\ Simulateurs/01_Suivi_AV_PER
streamlit run multi_page.py -- --demo

# 2. Avec le script run_app.sh
./run_app.sh --demo

# 3. Avec le script demo.sh (démo uniquement)
./demo.sh
```

## 📊 Données de démonstration

**Fichiers utilisés :**
- `00_Exports/DEMO_Export_selection_actifs.csv` (45 contrats)
- `00_Exports/DEMO_Export_situations_detaillees.csv` (détails des fonds)

**Structure :** Identique aux fichiers réels pour une compatible totale

## 🔍 Vérification rapide

```bash
# Tester que la détection fonctionne
cd /Users/jean-philippenavarro/Documents/10_CGP/20_Outils\ -\ Simulateurs/01_Suivi_AV_PER
python3 -c "import sys; sys.argv.append('--demo'); from config import DEMO_MODE; print('Mode démo:', DEMO_MODE)"
```

## 📁 Structure finale

```
01_Suivi_AV_PER/
├── config.py                           [NOUVEAU] Configuration centralisée
├── multi_page.py                       [MODIFIÉ] Affiche badge démo
├── run_app.sh                          [NOUVEAU] Script flexible
├── demo.sh                             [NOUVEAU] Script démo simple
├── MODE_DEMO.md                        [NOUVEAU] Guide complet
├── LANCEMENT.md                        [NOUVEAU] Instructions
├── views/
│   ├── data_ingestion.py              [MODIFIÉ] Charge données démo
│   └── ... (autres fichiers inchangés)
└── 00_Exports/
    ├── DEMO_Export_selection_actifs.csv        [NOUVEAU]
    ├── DEMO_Export_situations_detaillees.csv   [NOUVEAU]
    ├── 1_Selection_Actifs/
    ├── 2_Situations_Detaillées/
    └── ... (autres dossiers)
```

## ✨ Avantages

- 🎯 **Zéro code** - Juste un argument de ligne de commande
- 🔒 **Sécurisé** - Données réelles jamais touchées
- 📊 **Complètes** - 45 contrats avec structure réaliste
- 🔄 **Flexible** - 3 façons de lancer le mode démo
- 📚 **Documenté** - Guides complets fournis

## 🎓 Cas d'usage

✅ Démonstrations aux clients potentiels
✅ Onboarding de nouveaux collaborateurs
✅ Tests de fonctionnalités sans données sensibles
✅ Présentation à des tiers
✅ Environnement de développement sûr

---

**Prêt à tester ?** Lancez : `./demo.sh`
