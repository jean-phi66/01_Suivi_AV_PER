# Suivi AV/PER - Guide de lancement

## Lancement normal (données réelles)

```bash
streamlit run multi_page.py
```

ou en utilisant le script :

```bash
./run_app.sh
```

## Lancement en mode démo (données fictives)

```bash
streamlit run multi_page.py -- --demo
```

ou en utilisant le script :

```bash
./run_app.sh --demo
```

## Environnement

Vous pouvez aussi définir une variable d'environnement pour le mode démo :

```bash
DEMO_MODE=true streamlit run multi_page.py
```

## Notes

- Le mode démo charge les fichiers CSV de démonstration :
  - `DEMO_Export_selection_actifs.csv` (contrats fictifs)
  - `DEMO_Export_situations_detaillees.csv` (allocations fictives)
  
- Ces fichiers contiennent des données anonymisées avec des noms génériques et des valeurs simulées
- Idéal pour les démonstrations et les tests sans exposer les données réelles des clients
