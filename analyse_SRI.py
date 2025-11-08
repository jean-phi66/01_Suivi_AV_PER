def generate_fig_SRI(df_allocations_client):
    import plotly.express as px
    import numpy as np
    import pandas as pd

    df_allocations_client_SRI = df_allocations_client.groupby(
        'SRI')['Encours en €'].sum().reset_index()
    df_allocations_client_SRI['ratio SRI'] = df_allocations_client_SRI['Encours en €'] / \
        df_allocations_client_SRI['Encours en €'].sum()

    fig_distribution_SRI = px.bar(df_allocations_client_SRI, x='SRI', y='ratio SRI',
                                text_auto='.0%')
    fig_distribution_SRI.update_layout(
        title="Répartition SRI",
        xaxis_range=[.5, 7.5])
    fig_distribution_SRI.update_traces(width=0.5)


    df_allocations_client_SRI_moyen = np.sum(
        df_allocations_client_SRI['ratio SRI'] * df_allocations_client_SRI['SRI'])
    print("SRI moyen contrat:", np.round(df_allocations_client_SRI_moyen, 2))

    df_allocations_client_SRI_moyen = pd.DataFrame(
        {'SRI Contrat': [df_allocations_client_SRI_moyen]})

    fig_SRI_contrat = px.bar(df_allocations_client_SRI_moyen, x='SRI Contrat',
                            text_auto=True)
    fig_SRI_contrat.update_layout(title="SRI global du contrat",
                                xaxis_range=[1, 7.5])
    fig_SRI_contrat.update_yaxes(visible=False, showticklabels=False)
    fig_SRI_contrat.update_traces(
        marker_line_width=0,
        texttemplate="%{value:.1f}"
    )
    fig_SRI_contrat.add_shape(
        type="rect", x0=1, y0=-.5, x1=1.5, y1=.7,
        fillcolor=None, line_width=2, layer="above")
    fig_SRI_contrat.add_shape(
        type="rect", x0=1.5, y0=-.5, x1=3.5, y1=.7,
        fillcolor=None, line_width=2, layer="above")
    fig_SRI_contrat.add_shape(
        type="rect", x0=3.5, y0=-.5, x1=4.5, y1=.7,
        fillcolor=None, line_width=2, layer="above")
    fig_SRI_contrat.add_shape(
        type="rect", x0=4.5, y0=-.5, x1=7.5, y1=.7,
        fillcolor=None, line_width=2, layer="above")
    fig_SRI_contrat.add_annotation(x=1.25, y=.6,
                                text="Sécurité", showarrow=False)
    fig_SRI_contrat.add_annotation(x=2.5, y=.6,
                                text="Prudent", showarrow=False)
    fig_SRI_contrat.add_annotation(x=4., y=.6,
                                text="Equilibré", showarrow=False)
    fig_SRI_contrat.add_annotation(x=6., y=.6,
                                text="Dynamique", showarrow=False)

    return([df_allocations_client_SRI, fig_distribution_SRI, fig_SRI_contrat])