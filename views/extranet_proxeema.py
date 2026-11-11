from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from config import (
    BASE_EXPORTS_PATH,
    REAL_DATA_ALLOCATIONS_PATH,
    REAL_DATA_CONTRATS_PATH,
    REAL_DATA_FONDS_PATH,
)
from pdf_tri_analysis import DEFAULT_PDF_DIR
from proxeema_client import (
    authenticate_proxeema,
    delete_proxeema_credentials,
    delete_suravenir_credentials,
    extract_portfolio_funds_from_exports,
    fetch_and_save_proxeema_exports,
    fetch_and_save_quantalys_top10_csv,
    fetch_and_save_suravenir_pdfs,
    load_proxeema_credentials,
    load_suravenir_credentials,
    proxeema_credentials_exist,
    save_proxeema_credentials,
    save_suravenir_credentials,
    suravenir_credentials_exist,
)

st.title("Import Extranet Proxeema")
st.caption(
    "Récupération automatique des derniers exports Contrats et Situations détaillées (Supports) "
    "depuis https://proxeema.finzzle-groupe.com/contrats-stellium"
)

saved_creds = load_proxeema_credentials()

with st.container(border=True):
    st.subheader("Identifiants Proxeema (Finzzle / Prodemial)")
    if proxeema_credentials_exist() and saved_creds["username"]:
        st.success(f"Identifiants mémorisés dans le coffre local chiffré ({saved_creds['username']}).")
    else:
        st.info("Saisissez vos identifiants Proxeema ci-dessous.")

    col_u, col_p = st.columns(2)
    with col_u:
        username = st.text_input(
            "Identifiant (adresse email)",
            value=saved_creds["username"],
            placeholder="prenom.nom@...",
        )
    with col_p:
        password = st.text_input(
            "Mot de passe",
            value=saved_creds["password"],
            type="password",
        )

    col_save, col_del, _ = st.columns([1, 1, 2])
    with col_save:
        if st.button("💾 Mémoriser les identifiants"):
            try:
                save_proxeema_credentials(username, password)
                st.success("Identifiants enregistrés dans le coffre local chiffré.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with col_del:
        if st.button("🗑️ Supprimer du coffre", disabled=not proxeema_credentials_exist()):
            try:
                delete_proxeema_credentials()
                st.success("Identifiants supprimés du coffre local.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

archive_previous = st.checkbox(
    "Archiver automatiquement les précédents exports dans 00_Exports/old/",
    value=True,
    help="Déplace les fichiers CSV existants de 1_Selection_Actifs et 2_Situations_Detaillées vers old/ avant d'enregistrer les nouveaux.",
)

with st.expander("Option avancée : utiliser un jeton Bearer manuellement (si double facteur actif)"):
    manual_token = st.text_input(
        "Bearer Token OAuth2 (optionnel)",
        type="password",
        help="Si renseigné, ce jeton sera utilisé directement sans passer par le formulaire CAS.",
    )

fetch_clicked = st.button(
    "🚀 Récupérer les derniers exports (Contrats & Situations)",
    type="primary",
    use_container_width=True,
)

if fetch_clicked:
    try:
        with st.status("Connexion et génération des exports sur Proxeema...", expanded=True) as status:
            if manual_token and manual_token.strip():
                st.write("🔑 Utilisation du jeton Bearer fourni manuellement...")
                token = manual_token.strip()
            else:
                st.write("🔐 Authentification sur le serveur CAS Prodemial / Finzzle...")
                token = authenticate_proxeema(username, password)
                st.write("✅ Authentification réussie.")

            st.write("📥 Génération et téléchargement des fichiers Contrats et Supports via l'API Proxeema...")
            result = fetch_and_save_proxeema_exports(token, archive_previous=archive_previous)
            status.update(label="Exports récupérés et enregistrés avec succès !", state="complete")

        st.success(
            f"Fichiers enregistrés :\n"
            f"- **Contrats** : `{result['contrats_path'].name}` ({result['contrats_size'] / 1024:.1f} Ko)\n"
            f"- **Supports / Situations** : `{result['supports_path'].name}` ({result['supports_size'] / 1024:.1f} Ko)\n\n"
            "Rendez-vous sur la page **Données** pour recharger l'application avec ces nouveaux fichiers."
        )
    except Exception as exc:
        st.error(f"Échec de la récupération : {exc}")

st.divider()
st.subheader("Extranet Oriadys Suravenir (Éditions de situation des contrats)")

saved_surav = load_suravenir_credentials()
with st.container(border=True):
    st.markdown("**Identifiants Oriadys Suravenir (`oriadys.suravenir.fr`)**")
    if suravenir_credentials_exist() and saved_surav["username"]:
        st.success(f"Identifiants Suravenir mémorisés dans le coffre local chiffré ({saved_surav['username']}).")
    else:
        st.info("Saisissez vos identifiants Oriadys Suravenir ci-dessous puis cliquez sur Mémoriser.")

    col_su, col_sp = st.columns(2)
    with col_su:
        surav_username = st.text_input(
            "Identifiant Oriadys Suravenir",
            value=saved_surav["username"],
            key="surav_user_input",
        )
    with col_sp:
        surav_password = st.text_input(
            "Mot de passe Oriadys Suravenir",
            value=saved_surav["password"],
            type="password",
            key="surav_pass_input",
        )

    col_ssave, col_sdel, _ = st.columns([1, 1, 2])
    with col_ssave:
        if st.button("💾 Mémoriser les identifiants Suravenir"):
            try:
                save_suravenir_credentials(surav_username, surav_password)
                st.success("Identifiants Suravenir enregistrés dans le coffre local chiffré.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with col_sdel:
        if st.button("🗑️ Supprimer Suravenir du coffre", disabled=not suravenir_credentials_exist()):
            try:
                delete_suravenir_credentials()
                st.success("Identifiants Suravenir supprimés du coffre local.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

col_opt1, col_opt2 = st.columns(2)
with col_opt1:
    complete_situation = st.checkbox(
        "Inclure la liste des mouvements dans le PDF (requis pour le calcul de TRI)",
        value=True,
        help="Équivalent à la case « Souhaitez-vous intégrer la liste des mouvements au document généré ? » sur Oriadys.",
    )
with col_opt2:
    archive_pdf_prev = st.checkbox(
        "Archiver les anciennes éditions PDF des contrats mis à jour dans 00_Exports/old/04_Opérations/",
        value=True,
        help="Déplace les anciens fichiers PDF du contrat (y compris les doublons (1), (2)...) vers old/04_Opérations/.",
    )

fetch_surav_clicked = st.button(
    "📄 Récupérer les éditions de situation de tous les contrats Suravenir (PDF)",
    type="primary",
    use_container_width=True,
)

if fetch_surav_clicked:
    try:
        with st.status("Récupération des éditions de situation Suravenir en cours...", expanded=True) as s_status:
            if manual_token and manual_token.strip():
                st.write("🔑 Utilisation du jeton Bearer Proxeema fourni manuellement...")
                prox_token = manual_token.strip()
            else:
                st.write("🔐 Authentification sur Proxeema pour lister les contrats Suravenir et leurs identifiants...")
                prox_token = authenticate_proxeema(username, password)
                st.write("✅ Liste des contrats récupérée depuis Proxeema.")

            st.write("🔐 Authentification sur Oriadys Suravenir (Liferay + OAuth2 PKCE) et téléchargement des PDF...")
            progress_bar = st.progress(0.0, text="Initialisation du téléchargement des PDF Suravenir...")
            progress_label = st.empty()

            def _on_progress(idx: int, total: int, num_contrat: str, titulaire: str):
                frac = idx / max(total, 1)
                label_txt = f"[{idx}/{total}] Téléchargement du contrat **{num_contrat}** ({titulaire})..."
                progress_bar.progress(frac, text=f"{idx}/{total} — {num_contrat}")
                progress_label.markdown(label_txt)

            surav_result = fetch_and_save_suravenir_pdfs(
                proxeema_token=prox_token,
                suravenir_username=surav_username,
                suravenir_password=surav_password,
                complete_situation=complete_situation,
                archive_previous=archive_pdf_prev,
                progress_callback=_on_progress,
            )
            progress_bar.progress(1.0, text="Téléchargement terminé !")
            progress_label.empty()

            # Vider les caches d'analyse TRI PDF afin que les pages Performance et TRI PDF prennent en compte les nouveaux fichiers
            st.cache_resource.clear()
            st.cache_data.clear()

            nb_ok = len(surav_result["downloaded"])
            nb_err = len(surav_result["errors"])
            nb_tot = surav_result["total"]
            s_status.update(
                label=f"Éditions Suravenir terminées : {nb_ok}/{nb_tot} PDF enregistrés dans 04_Opérations !",
                state="complete" if nb_err == 0 else "error",
            )

        if surav_result["downloaded"]:
            total_kb = sum(d["size_bytes"] for d in surav_result["downloaded"]) / 1024
            st.success(
                f"✅ **{len(surav_result['downloaded'])} / {surav_result['total']}** éditions de situation PDF "
                f"téléchargées dans `{surav_result['pdf_dir']}` ({total_kb:.1f} Ko au total)."
            )
            with st.expander(f"Voir le détail des {len(surav_result['downloaded'])} contrats téléchargés"):
                df_dl = pd.DataFrame(
                    [
                        {
                            "N° de contrat": d["numero_contrat"],
                            "Titulaire": d["titulaire"],
                            "Produit": d["produit"],
                            "Fichier PDF": d["file_name"],
                            "Taille (Ko)": round(d["size_bytes"] / 1024, 1),
                        }
                        for d in surav_result["downloaded"]
                    ]
                )
                st.dataframe(df_dl, use_container_width=True, hide_index=True)

        if surav_result["errors"]:
            st.warning(f"⚠️ {len(surav_result['errors'])} contrat(s) n'ont pas pu être téléchargés :")
            st.dataframe(pd.DataFrame(surav_result["errors"]), use_container_width=True, hide_index=True)

    except Exception as exc:
        st.error(f"Échec de la récupération des éditions Suravenir : {exc}")

st.divider()
st.subheader("Quantalys Optimiz-Portfolio (Historique de performance des fonds)")
st.caption(
    "Récupération automatique de tous les supports utilisés dans le portefeuille, mise à jour "
    "d'une allocation iso-weight sur https://optimiz-portfolio.quantalys.com/Stellium "
    "(mêmes identifiants CAS Prodemial / Proxeema que ci-dessus) et téléchargement de l'historique quotidien en CSV (`Export_Top_10_test.csv`)."
)

col_q1, col_q2 = st.columns([1, 2])
with col_q1:
    quantalys_alloc_name = st.text_input(
        "Nom de l'allocation sur Optimiz-Portfolio",
        value="Top 10 test",
        help="Si une allocation personnelle portant ce nom existe déjà sur Optimiz-Portfolio, sa composition sera mise à jour ; sinon elle sera créée.",
    )
with col_q2:
    include_structured_q = st.checkbox(
        "Inclure les produits structurés dans l'allocation Optimiz-Portfolio",
        value=False,
        help="Par défaut, les supports en euros et les produits structurés sont exclus afin qu'un produit structuré échu ne bloque pas la date de fin de la courbe agrégée du portefeuille.",
    )
    archive_fonds_prev = st.checkbox(
        "Archiver l'ancien fichier d'historique des fonds dans 00_Exports/old/3_Fonds/",
        value=True,
        help="Déplace les fichiers CSV existants de 3_Fonds vers old/3_Fonds/ avant d'enregistrer le nouveau fichier.",
    )

try:
    preview_funds_info = extract_portfolio_funds_from_exports(include_structured=include_structured_q)
    with st.expander(
        f"Aperçu des supports détectés dans `{preview_funds_info['source_file'].name}` "
        f"({len(preview_funds_info['target_funds'])} fonds retenus / {preview_funds_info['all_unique_count']} supports uniques)"
    ):
        df_preview_target = pd.DataFrame(preview_funds_info["target_funds"]).rename(
            columns={"code_isin": "Code ISIN", "support": "Support", "type": "Type"}
        )
        st.dataframe(df_preview_target, use_container_width=True, hide_index=True)
        if preview_funds_info["excluded_supports"]:
            st.caption(f"Supports exclus ({len(preview_funds_info['excluded_supports'])}) :")
            df_preview_excl = pd.DataFrame(preview_funds_info["excluded_supports"]).rename(
                columns={"code_isin": "Code ISIN", "support": "Support", "type": "Type", "raison": "Raison"}
            )
            st.dataframe(df_preview_excl, use_container_width=True, hide_index=True)
except Exception as exc:
    st.warning(f"Impossible de prévisualiser les supports du portefeuille : {exc}")

fetch_quantalys_clicked = st.button(
    "📈 Mettre à jour l'allocation iso-weight et télécharger l'historique des fonds (CSV)",
    type="primary",
    use_container_width=True,
)

if fetch_quantalys_clicked:
    try:
        with st.status(
            "Mise à jour de l'allocation iso-weight et export CSV sur Quantalys Optimiz-Portfolio...",
            expanded=True,
        ) as q_status:
            q_progress_bar = st.progress(0.0, text="Initialisation...")

            def _on_q_progress(step: int, total_steps: int, msg: str):
                st.write(f"🔄 **Étape {step}/{total_steps}** — {msg}")
                q_progress_bar.progress(min(step / max(total_steps, 1), 1.0), text=msg)

            q_result = fetch_and_save_quantalys_top10_csv(
                username=username,
                password=password,
                allocation_name=quantalys_alloc_name,
                include_structured=include_structured_q,
                archive_previous=archive_fonds_prev,
                progress_callback=_on_q_progress,
            )
            q_progress_bar.progress(1.0, text="Historique des fonds mis à jour !")
            st.cache_data.clear()
            q_status.update(
                label=(
                    f"Historique des fonds mis à jour avec succès : {q_result['file_path'].name} "
                    f"({q_result['unique_products_count']} fonds dans l'allocation « {q_result['allocation_name']} ») !"
                ),
                state="complete",
            )

        plage_dates = (
            f"du **{q_result['min_portfolio_date']}** au **{q_result['max_portfolio_date']}**"
            if q_result["min_portfolio_date"] and q_result["max_portfolio_date"]
            else "disponible"
        )
        st.success(
            f"✅ Fichier enregistré : **`{q_result['file_path'].name}`** "
            f"({q_result['size_bytes'] / (1024 * 1024):.2f} Mo, {q_result['line_count']:,} lignes, "
            f"historique {plage_dates}).\n\n"
            f"- **Allocation Optimiz-Portfolio** : `{q_result['allocation_name']}` (ID `{q_result['allocation_id']}`)\n"
            f"- **Fonds inclus (iso-weight)** : **{q_result['unique_products_count']}** fonds Quantalys "
            f"(couvrant **{len(q_result['resolved_funds'])}** codes ISIN du portefeuille)"
        )

        with st.expander(f"Voir les {len(q_result['resolved_funds'])} supports résolus et intégrés dans l'historique"):
            df_res = pd.DataFrame(q_result["resolved_funds"]).rename(
                columns={
                    "code_isin_portefeuille": "ISIN Portefeuille",
                    "support_portefeuille": "Support Portefeuille",
                    "type_portefeuille": "Type",
                    "code_isin_quantalys": "ISIN Quantalys",
                    "nom_quantalys": "Nom Quantalys",
                    "id_produit": "ID Quantalys",
                    "mode_resolution": "Résolution",
                }
            )
            st.dataframe(df_res, use_container_width=True, hide_index=True)

        if q_result["unresolved_funds"]:
            st.warning(
                f"⚠️ {len(q_result['unresolved_funds'])} support(s) n'ont pas été trouvés dans Quantalys Optimiz-Portfolio :"
            )
            st.dataframe(pd.DataFrame(q_result["unresolved_funds"]), use_container_width=True, hide_index=True)

    except Exception as exc:
        st.error(f"Échec de la mise à jour de l'historique des fonds sur Quantalys : {exc}")

st.divider()
st.subheader("Fichiers actuellement présents dans 00_Exports")

col_c, col_s, col_f, col_p = st.columns(4)

with col_c:
    st.markdown("**1_Selection_Actifs (Contrats)**")
    contrats_files = sorted(Path(REAL_DATA_CONTRATS_PATH).glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not contrats_files:
        st.warning("Aucun fichier CSV présent.")
    else:
        for f in contrats_files:
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
            st.caption(f"📄 `{f.name}` — modifié le {mtime} ({f.stat().st_size / 1024:.1f} Ko)")
        try:
            df_c_preview = pd.read_csv(contrats_files[0], sep=";", decimal=",", thousands=" ")
            st.metric("Nombre de contrats dans le dernier export", len(df_c_preview))
            if "Date de valorisation" in df_c_preview.columns:
                st.caption(f"Dates de valorisation : {', '.join(df_c_preview['Date de valorisation'].dropna().astype(str).unique()[:3])}")
        except Exception:
            pass

with col_s:
    st.markdown("**2_Situations_Detaillées (Supports)**")
    supports_files = sorted(Path(REAL_DATA_ALLOCATIONS_PATH).glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not supports_files:
        st.warning("Aucun fichier CSV présent.")
    else:
        for f in supports_files:
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
            st.caption(f"📄 `{f.name}` — modifié le {mtime} ({f.stat().st_size / 1024:.1f} Ko)")
        try:
            df_s_preview = pd.read_csv(supports_files[0], sep=";", decimal=",", thousands=" ")
            st.metric("Nombre de lignes de supports dans le dernier export", len(df_s_preview))
            if "Date d'import" in df_s_preview.columns:
                st.caption(f"Date d'import : {', '.join(df_s_preview['Date d\'import'].dropna().astype(str).unique()[:3])}")
        except Exception:
            pass

with col_f:
    st.markdown("**3_Fonds (Historique Quantalys)**")
    fonds_files = sorted(Path(REAL_DATA_FONDS_PATH).glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not fonds_files:
        st.warning("Aucun fichier CSV présent.")
    else:
        for f in fonds_files:
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
            st.caption(f"📈 `{f.name}` — modifié le {mtime} ({f.stat().st_size / (1024 * 1024):.2f} Mo)")
        try:
            df_f_preview = pd.read_csv(fonds_files[0], sep=";", decimal=",", encoding="latin-1")
            nb_fonds_hist = df_f_preview[df_f_preview["Code ISIN"] != "Portefeuille"]["Code ISIN"].nunique()
            st.metric("Fonds dans l'historique", nb_fonds_hist)
            df_port_rows = df_f_preview[df_f_preview["Code ISIN"] == "Portefeuille"]
            if not df_port_rows.empty:
                st.caption(f"Dernière date : {df_port_rows['Date'].iloc[-1]}")
        except Exception:
            pass

with col_p:
    st.markdown("**04_Opérations (Éditions PDF Suravenir)**")
    pdf_files = sorted(Path(DEFAULT_PDF_DIR).glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not pdf_files:
        st.warning("Aucun fichier PDF présent.")
    else:
        st.metric("Nombre de fichiers PDF dans 04_Opérations", len(pdf_files))
        latest_mtime = datetime.fromtimestamp(pdf_files[0].stat().st_mtime).strftime("%d/%m/%Y %H:%M")
        st.caption(f"Dernier PDF mis à jour : `{pdf_files[0].name}` ({latest_mtime})")
        with st.expander("Voir les derniers PDF modifiés"):
            for pf in pdf_files[:15]:
                pmtime = datetime.fromtimestamp(pf.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
                st.caption(f"📑 `{pf.name}` — {pmtime} ({pf.stat().st_size / 1024:.1f} Ko)")

