## 📈 Ajout du graphique d'évolution de la valorisation - Rapports par lot

### ✅ **Problème résolu**

Le graphique d'évolution de la valorisation était manquant dans les rapports générés par lot, alors qu'il apparaît correctement dans les rapports individuels.

### 🔍 **Analyse du graphique d'évolution**

Ce graphique est généré dans `perfo.py` et montre :
- **Évolution temporelle** : Valorisation du contrat au fil du temps
- **Ligne des versements bruts** : Ligne horizontale rouge en pointillés
- **Effort d'épargne** : Pour les PER, ligne bleue après avantage fiscal
- **Filtrage intelligent** : Supprime les baisses > 30% (erreurs de données)
- **Données historiques** : Combinaison de `df_contrat_agg` + données actuelles

### 🛠️ **Implémentation**

#### 1. **Code repris intégralement de perfo.py**
```python
# EXACTEMENT les mêmes étapes que perfo.py (lignes 147-237)

# 1. Filtrer les données historiques pour le contrat
df_historical_for_contract = df_contrat_agg[df_contrat_agg['N° de contrat'] == contrat_num].copy()

# 2. Combiner données historiques + actuelles
df_combined_plot_data = pd.concat([df_historical_for_plot, df_current_for_plot], ignore_index=True)

# 3. Supprimer doublons et trier par date
df_combined_plot_data.drop_duplicates(subset=['N° de contrat', 'Date de valorisation'], inplace=True)
df_combined_plot_data.sort_values(by='Date de valorisation', inplace=True)

# 4. Filtrer les baisses > 30% (erreurs de données)
variation = df_combined_plot_data_filtered['Valorisation'].pct_change()
condition_filtrage = (variation >= -0.30) | variation.isnull()
```

#### 2. **Génération du graphique identique**
```python
# Même titre dynamique
if titulaire_pour_titre:
    fig_evol_title = f"Évolution de la valorisation pour {titulaire_pour_titre} - Contrat {contrat_num}"
else:
    fig_evol_title = f"Évolution de la valorisation du contrat {contrat_num}"

# Graphique en ligne avec marqueurs (identique à perfo.py)
fig_evol = px.line(df_combined_plot_data_filtered, x='Date de valorisation', y='Valorisation',
                 title=fig_evol_title, markers=True)
```

#### 3. **Lignes horizontales pour contexte**
```python
# Ligne rouge : Versements bruts
fig_evol.add_hline(y=montant_versements_bruts,
                 line_dash="dash",
                 line_color="red",
                 annotation_text=f"Versements Bruts: {montant_versements_bruts:,.0f} €")

# Ligne bleue : Effort d'épargne (PER uniquement)
if df_contrat_selected['Enveloppe'].iloc[0] == "PER":
    effort_epargne = montant_versements_bruts * (1 - 0.30)  # TMI 30% par défaut
    fig_evol.add_hline(y=effort_epargne, line_color="blue", ...)
```

### 📊 **Fonctionnalités du graphique**

| Élément | Description | Couleur/Style |
|---------|-------------|---------------|
| **Courbe principale** | Évolution de la valorisation | Bleu, avec marqueurs |
| **Ligne versements** | Montant total investi | Rouge, pointillés |
| **Ligne effort épargne** | Coût réel après fiscalité (PER) | Bleu, pointillés |
| **Titre dynamique** | Nom du titulaire + contrat | Adaptatif |
| **Filtrage automatique** | Supprime les erreurs > 30% | Transparent |

### 🔧 **Gestion des cas particuliers**

1. **Pas de données historiques** → `fig_evol = None` (graceful degradation)
2. **Colonnes manquantes** → Vérification avant traitement  
3. **Données vides** → Tests de présence avec `not df.empty`
4. **Erreurs de calcul** → Try/catch avec message d'erreur
5. **Contrats récents** → Fonctionne même avec un seul point

### 🎯 **Résultat**

Les rapports par lot incluent maintenant **TOUS les graphiques** :
- ✅ **Composition** : Camemberts par type et support
- ✅ **Performance** : Graphiques waterfall (contrat + allocations)  
- ✅ **SRI** : Distribution et note du contrat
- ✅ **Évolution** : **NOUVEAU** - Courbe de valorisation temporelle

### 🚀 **Impact**

**Avant** : Rapports par lot incomplets (pas d'évolution temporelle)  
**Après** : Rapports par lot **identiques** aux rapports individuels

**Le graphique d'évolution de la valorisation comme celui montré dans l'image (ALIOS-DUPLAT Emmanuelle - Contrat 270745982) apparaîtra maintenant dans tous les rapports générés par lot ! 📈**

---

**Note** : Pour les PER en génération par lot, le TMI est fixé à 30% par défaut pour l'effort d'épargne, contrairement à la page individuelle où l'utilisateur peut le personnaliser.