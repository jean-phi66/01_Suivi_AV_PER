def generate_fig_SRI(df_allocations_client):
    import plotly.express as px
    import numpy as np
    import pandas as pd

    df = df_allocations_client.copy() if df_allocations_client is not None else pd.DataFrame()
    if df.empty or 'Encours en €' not in df.columns:
        empty_df = pd.DataFrame(columns=['SRI', 'Encours en €', 'ratio SRI'])
        fig_empty = px.bar(title="Répartition SRI")
        return [empty_df, fig_empty, fig_empty]

    df['Encours en €'] = pd.to_numeric(df['Encours en €'], errors='coerce').fillna(0.0)

    # Convertir le SRI en numérique (les chaînes comme 'Non disponible' deviennent NaN)
    col_sri = 'SRI' if 'SRI' in df.columns else ('SRRI' if 'SRRI' in df.columns else None)
    if col_sri:
        df['SRI'] = pd.to_numeric(df[col_sri], errors='coerce')
    else:
        df['SRI'] = np.nan

    # Ne conserver que les lignes ayant un SRI valide (entre 1 et 7) et un encours > 0
    df_valid = df[df['SRI'].notna() & (df['SRI'] >= 1) & (df['SRI'] <= 7) & (df['Encours en €'] > 0)].copy()

    if df_valid.empty:
        empty_df = pd.DataFrame(columns=['SRI', 'Encours en €', 'ratio SRI'])
        fig_dist_empty = px.bar(title="Répartition SRI (aucun support noté)")
        fig_sri_empty = px.bar(title="SRI global du contrat (non disponible)")
        return [empty_df, fig_dist_empty, fig_sri_empty]

    df_valid['SRI'] = df_valid['SRI'].astype(int)
    total_encours_sri = df_valid['Encours en €'].sum()

    df_allocations_client_SRI = df_valid.groupby(
        'SRI', as_index=False)['Encours en €'].sum()
    df_allocations_client_SRI['ratio SRI'] = df_allocations_client_SRI['Encours en €'] / (
        total_encours_sri if total_encours_sri > 0 else 1.0
    )

    fig_distribution_SRI = px.bar(df_allocations_client_SRI, x='SRI', y='ratio SRI',
                                text_auto='.0%')
    fig_distribution_SRI.update_layout(
        title="Répartition SRI",
        xaxis_range=[.5, 7.5],
        xaxis=dict(tickmode='linear', tick0=1, dtick=1))
    fig_distribution_SRI.update_traces(width=0.5)


    df_allocations_client_SRI_moyen = float(np.sum(
        df_allocations_client_SRI['ratio SRI'] * df_allocations_client_SRI['SRI']))
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