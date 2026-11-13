import importlib
import os
import sys
from datetime import datetime

import pandas as pd
import streamlit as st
from streamlit import session_state as ss

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pptx_report_generator as _pptx_report_generator

if not all(
    hasattr(_pptx_report_generator, _sym)
    for _sym in (
        "build_batch_pptx_targets",
        "build_contract_pptx_context",
        "generate_batch_contract_pptx",
        "generate_contract_pptx",
        "sanitize_pptx_filename",
    )
):
    _pptx_report_generator = importlib.reload(_pptx_report_generator)

build_batch_pptx_targets = _pptx_report_generator.build_batch_pptx_targets
build_contract_pptx_context = _pptx_report_generator.build_contract_pptx_context
generate_batch_contract_pptx = _pptx_report_generator.generate_batch_contract_pptx
generate_contract_pptx = _pptx_report_generator.generate_contract_pptx
sanitize_pptx_filename = _pptx_report_generator.sanitize_pptx_filename
from reporting_helpers import load_latest_fund_perf_file, prepare_portfolio_lines_table
from tri_integration import load_tri_analyses, match_tri_analyses_to_contracts, pdf_dir_signature


@st.cache_resource(show_spinner=False)
def _get_tri_analyses(pdf_signature: tuple = ()):
    return load_tri_analyses()


def _render_fund_dates_and_overlays(df_perfs: pd.DataFrame, key_suffix: str):
    """Affiche les sélecteurs communs (plage de dates des fonds et marqueurs d'opérations)."""
    date_debut = None
    date_fin = None
    if not df_perfs.empty:
        min_date = df_perfs["Date"].min().date()
        max_date = df_perfs["Date"].max().date()
        default_start = (df_perfs["Date"].max() - pd.DateOffset(years=1)).date()
        if default_start < min_date:
            default_start = min_date
        d1, d2 = st.columns(2)
        with d1:
            date_debut = st.date_input(
                "Date de début (évolution des fonds base 100)",
                value=default_start,
                min_value=min_date,
                max_value=max_date,
                key=f"pptx_funds_start_{key_suffix}",
            )
        with d2:
            date_fin = st.date_input(
                "Date de fin (évolution des fonds base 100)",
                value=max_date,
                min_value=min_date,
                max_value=max_date,
                key=f"pptx_funds_end_{key_suffix}",
            )
        if date_debut >= date_fin:
            st.error("La date de début doit être antérieure à la date de fin.")
            st.stop()
    else:
        st.info("Aucun fichier de performance quotidienne des fonds (*Top*.csv) trouvé dans 00_Exports/3_Fonds.")

    e1, e2 = st.columns(2)
    with e1:
        show_versements = st.checkbox(
            "Afficher les versements",
            value=True,
            key=f"pptx_show_versements_{key_suffix}",
        )
    with e2:
        show_arbitrages = st.checkbox(
            "Afficher les arbitrages",
            value=True,
            key=f"pptx_show_arbitrages_{key_suffix}",
        )
    return date_debut, date_fin, show_versements, show_arbitrages


st.title("Bilan de contrat PowerPoint")
st.caption(
    "Exportez une présentation PowerPoint complète pour un contrat ou pour l'ensemble des contrats de plusieurs clients."
)

df_contrats = ss.get("df_contrats", pd.DataFrame())
df_allocations = ss.get("df_allocations", pd.DataFrame())
df_contrat_agg = ss.get("df_contrat_agg_filtered", ss.get("df_contrat_agg", pd.DataFrame()))

required_contrats_cols = {"Titulaire(s)", "N° de contrat", "Enveloppe", "Partenaire", "Valorisation"}
required_alloc_cols = {"Numéro contrat"}

if (
    df_contrats.empty
    or df_allocations.empty
    or not required_contrats_cols.issubset(df_contrats.columns)
    or not required_alloc_cols.issubset(df_allocations.columns)
):
    st.warning("Aucune donnée contrats/allocations disponible.")
    st.info("Cliquez sur le bouton ci-dessous pour ouvrir l'onglet Données et charger automatiquement les exports.")
    if st.button("Ouvrir Données", key="pptx_open_data_ingestion"):
        st.switch_page("views/data_ingestion.py")
    st.stop()

clients_options = sorted(df_contrats["Titulaire(s)"].dropna().astype(str).unique().tolist())
if not clients_options:
    st.warning("Aucun titulaire disponible dans les données chargées.")
    st.stop()

_, tri_contracts_map = match_tri_analyses_to_contracts(
    _get_tri_analyses(pdf_dir_signature()),
    df_contrats[["N° de contrat", "Titulaire(s)", "Enveloppe", "Partenaire"]].drop_duplicates().copy(),
)
df_perfs, _ = load_latest_fund_perf_file()

export_mode = st.radio(
    "Mode de génération",
    options=["Contrat unique", "Multi-clients (tous leurs contrats)"],
    horizontal=True,
    key="pptx_export_mode",
)

if export_mode == "Contrat unique":
    # --- Mode 1 : Contrat unique ---
    default_client = ss.get("client") if ss.get("client") in clients_options else clients_options[0]
    client_idx = clients_options.index(default_client) if default_client in clients_options else 0

    col_cli, col_ctr = st.columns(2)
    with col_cli:
        selected_client = st.selectbox(
            "Titulaire",
            options=clients_options,
            index=client_idx,
            key="pptx_client_select",
        )

    df_contrats_client = df_contrats[df_contrats["Titulaire(s)"].astype(str) == str(selected_client)].copy()
    contrats_options = df_contrats_client["N° de contrat"].dropna().astype(str).unique().tolist()
    default_contrat = (
        str(ss.get("contrat"))
        if ss.get("contrat") is not None and str(ss.get("contrat")) in contrats_options
        else (contrats_options[0] if contrats_options else None)
    )
    contrat_idx = contrats_options.index(default_contrat) if default_contrat in contrats_options else 0

    with col_ctr:
        selected_contrat = st.selectbox(
            "Contrat",
            options=contrats_options,
            index=contrat_idx,
            key="pptx_contrat_select",
        )

    if not selected_contrat:
        st.warning("Aucun contrat disponible pour ce client.")
        st.stop()

    df_contrat_selected = df_contrats_client[df_contrats_client["N° de contrat"].astype(str) == str(selected_contrat)].copy()
    df_allocations_client = df_allocations[df_allocations["Numéro contrat"].astype(str) == str(selected_contrat)].copy()

    if df_contrat_selected.empty:
        st.warning("Données introuvables pour le contrat sélectionné.")
        st.stop()

    enveloppe = str(df_contrat_selected["Enveloppe"].iloc[0]) if "Enveloppe" in df_contrat_selected.columns else "N/A"
    partenaire = str(df_contrat_selected["Partenaire"].iloc[0]) if "Partenaire" in df_contrat_selected.columns else "N/A"
    valorisation = float(df_contrat_selected["Valorisation"].iloc[0]) if "Valorisation" in df_contrat_selected.columns else 0.0
    is_per = "PER" in enveloppe.upper()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Enveloppe", enveloppe)
    m2.metric("Partenaire", partenaire)
    m3.metric("Valorisation", f"{valorisation:,.0f} €".replace(",", " "))
    m4.metric("Avantage fiscal PER", "IR 30 % inclus" if is_per else "Non applicable")

    tri_analysis = tri_contracts_map.get(str(selected_contrat))

    st.subheader("Paramètres du bilan PowerPoint")

    default_source_idx = 1 if tri_analysis is not None else 0
    preferred_source = st.radio(
        "Source des versements",
        options=["CSV contrats", "Releve d'operations TRI"],
        index=default_source_idx,
        horizontal=True,
        key=f"pptx_source_{selected_contrat}",
        help="Si aucun relevé d'opérations TRI n'est apparié à ce contrat, le calcul utilise automatiquement les données CSV.",
    )

    if tri_analysis is not None:
        st.caption("Relevé d'opérations TRI apparié : les versements et arbitrages seront affichés sur les graphiques.")
    else:
        st.caption("Aucun relevé d'opérations TRI apparié à ce contrat (les versements/arbitrages détaillés ne seront pas superposés).")

    date_debut, date_fin, show_versements, show_arbitrages = _render_fund_dates_and_overlays(
        df_perfs, key_suffix=str(selected_contrat)
    )

    gui_vp = None
    if f"proj_monthly_{selected_contrat}" in ss:
        try:
            gui_vp = float(ss[f"proj_monthly_{selected_contrat}"])
        except (ValueError, TypeError):
            gui_vp = None

    ctx = build_contract_pptx_context(
        client_name=selected_client,
        contrat_num=selected_contrat,
        df_contrats_all=df_contrats,
        df_allocations_all=df_allocations,
        df_contrat_selected=df_contrat_selected,
        df_allocations_client=df_allocations_client,
        df_contrat_agg=df_contrat_agg,
        tri_analysis=tri_analysis,
        preferred_source=preferred_source,
        date_debut=date_debut,
        date_fin=date_fin,
        show_versements=show_versements,
        show_arbitrages=show_arbitrages,
        monthly_contribution=gui_vp,
    )

    if ctx["missing_funds_labels"]:
        labels_preview = ", ".join(ctx["missing_funds_labels"][:5])
        suffix = "…" if len(ctx["missing_funds_labels"]) > 5 else ""
        st.warning(f"{len(ctx['missing_funds_labels'])} support(s) sans historique dans le fichier fonds : {labels_preview}{suffix}")

    classes_count = len(ctx["figures_by_class"])
    has_proj_8 = 1 if ctx.get("fig_projection_8ans") is not None else 0
    has_proj_2 = 1 if ctx.get("fig_projection_2ans") is not None else 0
    total_slides = 9 + classes_count + has_proj_8 + has_proj_2

    curr_n = 4
    if classes_count:
        cls_range = f"5-{4 + classes_count}" if classes_count > 1 else "5"
        cls_desc = f"{cls_range}) Évolution par classe d'actifs ({classes_count} classe(s)), "
        curr_n = 4 + classes_count
    else:
        cls_desc = ""

    curr_n += 1
    vl_slide_num = curr_n

    proj_desc_items = []
    if has_proj_8:
        curr_n += 1
        proj_desc_items.append(f"{curr_n}) Plan de projection à long terme (8 ans)")
    if has_proj_2:
        curr_n += 1
        proj_desc_items.append(f"{curr_n}) Plan de projection à court terme (2 ans)")
    proj_desc = f"{', '.join(proj_desc_items)}, " if proj_desc_items else ""

    curr_n += 1
    back_cover_num = curr_n
    curr_n += 1
    wf_c_num = curr_n
    curr_n += 1
    wf_a_num = curr_n
    curr_n += 1
    ops_num = curr_n

    st.info(
        f"Le document contiendra **{total_slides} slides** : "
        f"1) Page de garde ({'PER' if ctx['is_per'] else 'Assurance-vie'}), "
        f"2) Détail des lignes du portefeuille, "
        f"3) Composition (classes simplifiées & supports), "
        f"4) Évolution des fonds (base 100), "
        f"{cls_desc}"
        f"{vl_slide_num}) Évolution temporelle de la VL, "
        f"{proj_desc}"
        f"{back_cover_num}) 4ème de couverture (Cabinet & Clôture), "
        f"{wf_c_num}) Annexe : Waterfall contrat{' (avec IR 30 %)' if ctx['is_per'] else ''}, "
        f"{wf_a_num}) Annexe : Waterfall allocation, "
        f"{ops_num}) Annexe : Détail des versements et arbitrages."
    )

    state_signature = (
        str(selected_client),
        str(selected_contrat),
        preferred_source,
        str(date_debut),
        str(date_fin),
        show_versements,
        show_arbitrages,
    )

    if st.button("Générer le bilan PowerPoint (.pptx)", type="primary", key="btn_generate_pptx"):
        with st.spinner("Génération des graphiques et assemblage du PowerPoint en cours..."):
            pptx_bytes = generate_contract_pptx(
                client_name=selected_client,
                contrat_num=selected_contrat,
                df_contrat_sel=df_contrat_selected,
                fig_typologie_simplifiee=ctx["fig_typologie_simplifiee"],
                fig_supports=ctx["fig_supports"],
                fig_waterfall_contract=ctx["fig_waterfall_contract"],
                fig_waterfall_allocation=ctx["fig_waterfall_allocation"],
                fig_all_funds=ctx["fig_all_funds"],
                figures_by_class=ctx["figures_by_class"],
                fig_evol=ctx["fig_evol"],
                fig_projection_8ans=ctx.get("fig_projection_8ans"),
                fig_projection_2ans=ctx.get("fig_projection_2ans"),
                df_allocations_client=ctx.get("df_allocations_client"),
                kpis=ctx["kpis"],
                is_per=ctx["is_per"],
                tri_analysis=ctx["tri_analysis"],
            )
            ss["pptx_generated_bytes"] = pptx_bytes
            ss["pptx_generated_signature"] = state_signature
        st.success("Bilan PowerPoint généré avec succès !")

    if ss.get("pptx_generated_signature") == state_signature and ss.get("pptx_generated_bytes"):
        file_name = f"{sanitize_pptx_filename(selected_client, 'client')} - {sanitize_pptx_filename(selected_contrat)} - Bilan.pptx"
        st.download_button(
            label="Télécharger le bilan PowerPoint (.pptx)",
            data=ss["pptx_generated_bytes"],
            file_name=file_name,
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            key="download_bilan_pptx",
        )

    with st.expander("Aperçu des graphiques et tableaux du bilan", expanded=False):
        tab_names = [
            "1. Lignes portefeuille",
            "2. Composition",
            "3. Fonds (global & classes)",
            "4. Évolution VL",
            "5. Projections",
            "6. 4ème de couverture",
            "7. Annexes : Waterfalls",
            "8. Annexes : Opérations",
        ]
        t0, t1, t2, t3, t4, t5, t6, t7 = st.tabs(tab_names)
        with t0:
            df_lines_prev, _, _, meta_prev = prepare_portfolio_lines_table(ctx.get("df_allocations_client"))
            if not df_lines_prev.empty:
                def _hl_prev_row(row):
                    val = row.get("Évolution (%)", 0.0)
                    if isinstance(val, (int, float)):
                        if val > 0:
                            return ["background-color: #F0F9F4; color: #1F2937;"] * len(row)
                        elif val < 0:
                            return ["background-color: #FDF4F4; color: #1F2937;"] * len(row)
                    return [""] * len(row)

                def _col_prev_cell(val):
                    if isinstance(val, (int, float)):
                        if val > 0:
                            return "background-color: #DCF2E4; color: #137333; font-weight: 600;"
                        elif val < 0:
                            return "background-color: #FDEDEC; color: #C5221F; font-weight: 600;"
                    return ""

                styled_prev = (
                    df_lines_prev.style
                    .apply(_hl_prev_row, axis=1)
                    .map(_col_prev_cell, subset=["Évolution (%)"])
                    .format({
                        "Encours (€)": lambda x: f"{x:,.2f} €".replace(",", " ").replace(".", ","),
                        "Évolution (%)": lambda x: f"{x:+.2f} %".replace(".", ","),
                    })
                )
                st.dataframe(
                    styled_prev,
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Aucune ligne de portefeuille disponible pour ce contrat.")
        with t1:
            c_left, c_right = st.columns(2)
            with c_left:
                if ctx["fig_typologie_simplifiee"] is not None:
                    st.plotly_chart(ctx["fig_typologie_simplifiee"], use_container_width=True)
            with c_right:
                if ctx["fig_supports"] is not None:
                    st.plotly_chart(ctx["fig_supports"], use_container_width=True)
        with t2:
            if ctx["fig_all_funds"] is not None:
                st.plotly_chart(ctx["fig_all_funds"], use_container_width=True)
            else:
                st.info("Aucun historique de performance disponible pour les fonds du contrat.")
            for _, fig_cls in ctx["figures_by_class"]:
                st.plotly_chart(fig_cls, use_container_width=True)
        with t3:
            if ctx["fig_evol"] is not None:
                st.plotly_chart(ctx["fig_evol"], use_container_width=True)
            else:
                st.info("Historique de valorisation indisponible pour ce contrat.")
        with t4:
            has_p = False
            if ctx.get("fig_projection_8ans") is not None:
                has_p = True
                st.subheader("Plan de projection à long terme (8 ans)")
                st.plotly_chart(ctx["fig_projection_8ans"], use_container_width=True)
            if ctx.get("fig_projection_2ans") is not None:
                has_p = True
                st.subheader("Plan de projection à court terme (2 ans)")
                st.plotly_chart(ctx["fig_projection_2ans"], use_container_width=True)
            if not has_p:
                st.info("Aucun plan de projection disponible pour ce contrat.")
        with t5:
            st.markdown("### 4ème de couverture — Clôture du bilan")
            c_card1, c_card2 = st.columns(2)
            with c_card1:
                st.info(
                    "**VOTRE CABINET CONSEIL**\n\n"
                    "### Avenir-Patrimoine\n\n"
                    "**Jean-Philippe NAVARRO**\n\n"
                    "*Conseil en Gestion de Patrimoine*"
                )
            with c_card2:
                st.success(
                    f"**RÉFÉRENCES DU DOSSIER**\n\n"
                    f"### {selected_client}\n\n"
                    f"**{df_contrat_selected.get('Enveloppe', pd.Series(['N/A'])).iloc[0]}  •  N° {selected_contrat}**\n\n"
                    f"Partenaire : {df_contrat_selected.get('Partenaire', pd.Series(['N/A'])).iloc[0]}"
                )
            st.caption(
                "Avertissement & Mentions réglementaires : Le bilan patrimonial est un document confidentiel remis au client. "
                "Les performances passées ne préjugent pas des performances futures. Risque de perte en capital sur les UC."
            )
        with t6:
            if ctx["fig_waterfall_contract"] is not None:
                st.subheader("Annexe : Waterfall de performance globale du contrat")
                st.plotly_chart(ctx["fig_waterfall_contract"], use_container_width=True)
            if ctx["fig_waterfall_allocation"] is not None:
                st.subheader("Annexe : Waterfall de l'allocation par support")
                st.plotly_chart(ctx["fig_waterfall_allocation"], use_container_width=True)
        with t7:
            ops_meta = ctx.get("ops_meta") or {}
            st.subheader("Annexe : Détail des opérations")
            c_v, c_a = st.columns(2)
            with c_v:
                st.markdown(f"**Versements ({ops_meta.get('v_count', 0)})**")
                df_v = ctx.get("df_versements")
                if df_v is not None and not df_v.empty:
                    st.dataframe(df_v, use_container_width=True, hide_index=True)
                else:
                    st.info("Aucun versement extrait du relevé TRI.")
            with c_a:
                st.markdown(f"**Arbitrages ({ops_meta.get('a_count', 0)})**")
                df_a = ctx.get("df_arbitrages")
                if df_a is not None and not df_a.empty:
                    st.dataframe(df_a, use_container_width=True, hide_index=True)
                else:
                    st.info("Aucun arbitrage extrait du relevé TRI.")
            if ops_meta.get("assumption_note"):
                st.caption(ops_meta["assumption_note"])

else:
    # --- Mode 2 : Multi-clients (un PPTX par contrat de chaque client sélectionné) ---
    select_all_clients = st.checkbox(
        "Sélectionner tous les titulaires",
        value=False,
        key="pptx_multi_select_all",
    )
    default_multi_clients = (
        [ss["client"]]
        if ss.get("client") in clients_options
        else clients_options[:1]
    )
    selected_clients = (
        clients_options
        if select_all_clients
        else st.multiselect(
            "Titulaire(s) à inclure (un PowerPoint généré par contrat)",
            options=clients_options,
            default=default_multi_clients,
            key="pptx_multi_clients_select",
        )
    )

    targets = build_batch_pptx_targets(selected_clients, df_contrats)

    if not selected_clients or not targets:
        st.info("Sélectionnez au moins un titulaire pour préparer la génération multi-PowerPoint.")
        st.stop()

    per_count = sum(1 for t in targets if t["is_per"])
    av_count = len(targets) - per_count
    tri_matched_count = sum(1 for t in targets if t["contrat_num"] in tri_contracts_map)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Clients sélectionnés", len(selected_clients))
    c2.metric("PowerPoint à générer", len(targets))
    c3.metric("PER / Assurance-vie", f"{per_count} / {av_count}")
    c4.metric("Relevés TRI appariés", f"{tri_matched_count} / {len(targets)}")

    preview_rows = [
        {
            "Titulaire": t["client_name"],
            "N° de contrat": t["contrat_num"],
            "Type": "PER (IR 30 %)" if t["is_per"] else "Assurance-vie",
            "Enveloppe": t["enveloppe"],
            "Partenaire": t["partenaire"],
            "Valorisation (€)": round(t["valorisation"], 0),
            "Relevé TRI": "Oui" if t["contrat_num"] in tri_contracts_map else "Non",
            "Fichier généré": f"{sanitize_pptx_filename(t['client_name'], 'client')} - {sanitize_pptx_filename(t['contrat_num'])} - Bilan.pptx",
        }
        for t in targets
    ]
    with st.expander(f"Contrats inclus dans la génération ({len(targets)})", expanded=True):
        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

    st.subheader("Paramètres communs des bilans PowerPoint")
    preferred_source_batch = st.radio(
        "Source des versements",
        options=["Releve d'operations TRI", "CSV contrats"],
        index=0,
        horizontal=True,
        key="pptx_batch_source",
        help="Repli automatique sur les données CSV si un contrat n'a pas de relevé TRI apparié.",
    )
    date_debut_batch, date_fin_batch, show_versements_batch, show_arbitrages_batch = _render_fund_dates_and_overlays(
        df_perfs, key_suffix="batch"
    )
    group_by_client_folder = st.checkbox(
        "Organiser les fichiers par dossier client dans l'archive ZIP",
        value=False,
        key="pptx_batch_group_folders",
    )

    batch_signature = (
        tuple(selected_clients),
        preferred_source_batch,
        str(date_debut_batch),
        str(date_fin_batch),
        show_versements_batch,
        show_arbitrages_batch,
        group_by_client_folder,
    )

    if st.button(
        f"Générer les {len(targets)} bilan(s) PowerPoint (.pptx)",
        type="primary",
        key="btn_generate_batch_pptx",
    ):
        progress_bar = st.progress(0.0)
        status_placeholder = st.empty()

        def _on_progress(done_idx: int, total_items: int, target: dict):
            status_placeholder.text(
                f"Génération {done_idx}/{total_items} : {target['client_name']} — {target['contrat_num']}..."
            )
            progress_bar.progress((done_idx - 1) / max(total_items, 1))

        result = generate_batch_contract_pptx(
            selected_clients=selected_clients,
            df_contrats_all=df_contrats,
            df_allocations_all=df_allocations,
            df_contrat_agg=df_contrat_agg,
            tri_contracts_map=tri_contracts_map,
            preferred_source=preferred_source_batch,
            date_debut=date_debut_batch,
            date_fin=date_fin_batch,
            show_versements=show_versements_batch,
            show_arbitrages=show_arbitrages_batch,
            auto_extract_tri=False,
            group_by_client_folder=group_by_client_folder,
            progress_callback=_on_progress,
        )
        progress_bar.progress(1.0)
        status_placeholder.text("Génération terminée !")
        ss["pptx_batch_result"] = result
        ss["pptx_batch_signature"] = batch_signature

    batch_result = ss.get("pptx_batch_result")
    if ss.get("pptx_batch_signature") == batch_signature and batch_result:
        items = batch_result.get("items") or []
        errors = batch_result.get("errors") or []
        zip_bytes = batch_result.get("zip_bytes")

        if items:
            st.success(f"{len(items)} bilan(s) PowerPoint généré(s) avec succès.")
        if errors:
            for err in errors:
                st.error(f"{err['client_name']} — {err['contrat_num']} : {err['error']}")

        if zip_bytes:
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            st.download_button(
                label=f"Télécharger tous les bilans (.zip — {len(items)} fichier(s))",
                data=zip_bytes,
                file_name=f"Bilans_PowerPoint_{ts}.zip",
                mime="application/zip",
                key="download_batch_pptx_zip",
            )

        if items:
            with st.expander("Télécharger chaque bilan individuellement (.pptx)", expanded=False):
                for idx, item in enumerate(items):
                    st.download_button(
                        label=f"{item['file_name']} ({item['slides_count']} slides)",
                        data=item["data"],
                        file_name=item["file_name"],
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        key=f"download_batch_pptx_item_{idx}_{item['contrat_num']}",
                    )
