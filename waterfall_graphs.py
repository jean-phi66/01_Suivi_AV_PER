def generate_contrats_waterfall(df_contrats_upd, contrat, add_reduction_IR, IR_num):
    import pandas as pd
    # Waterfall Contract overall
    df_contrats_waterfall = df_contrats_upd[['Titulaire(s)', 'N° de contrat', 'Enveloppe',
                                            'Montant total des versements bruts', 'Frais',
                                            'Montant total des versements nets',
                                            'Performance embarquée', 'Performance allocation', 'Valorisation']]
    df_contrats_waterfall['Sanity_check'] = df_contrats_waterfall['Montant total des versements bruts'] + \
        df_contrats_waterfall['Frais'] + df_contrats_waterfall['Performance embarquée'] + \
        df_contrats_waterfall['Performance allocation']

    df_client_waterfall = df_contrats_waterfall[df_contrats_waterfall['N° de contrat'] == contrat]
    df_client_waterfall_wide = df_client_waterfall.copy()


    df_client_waterfall.drop(
        ['N° de contrat', 'Enveloppe', 'Sanity_check'], axis=1, inplace=True)
    if add_reduction_IR:
        df_client_waterfall.insert(1, 'Avantage fiscal', IR_num *
                                df_client_waterfall['Montant total des versements bruts'])
        df_client_waterfall.insert(
            1, 'Effort Epargne', df_client_waterfall['Montant total des versements bruts'] - df_client_waterfall['Avantage fiscal'])
        measure = ["relative", "relative", "total", "relative",
                "total", "relative", "relative", "total"]
    else:
        measure = ["relative", "relative", "total",
                "relative", "relative", "total"]

    df_client_waterfall = pd.melt(df_client_waterfall, id_vars=['Titulaire(s)'])

    df_client_waterfall['variable'] = df_client_waterfall['variable'].str.replace('Montant total des versements bruts',
                                                                                'Versements bruts')
    df_client_waterfall['variable'] = df_client_waterfall['variable'].str.replace('Montant total des versements nets',
                                                                                'Versements nets')
    return([df_client_waterfall, measure])





# Waterfall allocation
def generate_allocations_waterfall(df_allocations, contrat):
    df_allocations_waterfall = df_allocations[df_allocations['Numéro contrat'] == contrat]
    df_allocations_waterfall = df_allocations_waterfall[~df_allocations_waterfall['Type'].isin(
        ["Fonds en Euros"])]
    df_allocations_waterfall['measure'] = 'relative'
    df_allocations_waterfall.loc['Total'] = df_allocations_waterfall.sum(
        numeric_only=True, axis=0)
    df_allocations_waterfall.at['Total', "Support"] = "Total"
    df_allocations_waterfall.at['Total', "measure"] = "total"
    return(df_allocations_waterfall)

