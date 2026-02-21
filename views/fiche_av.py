import streamlit as st
from streamlit import session_state as ss

from datetime import date
from io import BytesIO
import base64
import json
import re
import urllib.error
import urllib.request

import pandas as pd
from pathlib import Path

import PyPDF2
from pdfrw import PdfDict, PdfName, PdfObject, PdfReader, PdfString, PdfWriter

BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = BASE_DIR / "pdf" / "AV" / "Fiche Conseil Assurance Vie Arbitrage 03-25.pdf"
MANDATAIRE_PATH = BASE_DIR / "defaults" / "mandataire.json"
CATALOGUE_PATH = BASE_DIR / "defaults" / "fonds_catalogue.json"
TOP_FUNDS_PATH = BASE_DIR / "00_Exports" / "3_Fonds" / "Export_Top_10_test.csv"
PROFILE_BALANCED_VALUE = "/3"

OBJECTIVE_FIELD_MAP = {
    "Optimiser sa fiscalite": "obj1",
    "Optimiser la rentabilite de ses placements": "obj2",
    "Aider ses enfants": "obj3",
    "Proteger le conjoint survivant": "obj4",
    "Proteger ses proches": "obj5",
    "Preparer sa retraite": "obj6",
    "Financer un achat immobilier": "obj7",
    "Preparer la transmission de son patrimoine": "obj8",
    "Preparer la transmission de son entreprise": "obj9",
    "Obtenir des revenus complementaires": "obj10",
    "Se constituer un patrimoine": "obj11",
    "Se constituer une epargne de precaution": "obj12",
    "Placer des liquidites a court terme": "obj13",
    "Se premunir contre les accidents de la vie": "obj15",
}


def _normalize_label(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum() or ch.isspace()).strip()


def _load_contract_options():
    if not TEMPLATE_PATH.exists():
        return []

    with TEMPLATE_PATH.open("rb") as handle:
        reader = PyPDF2.PdfReader(handle)
        fields = reader.get_fields() or {}
        field = fields.get("choixcontrat", {})
        options = field.get("/Opt") or []

    cleaned = []
    for opt in options:
        if isinstance(opt, (list, tuple)) and len(opt) == 2:
            value, label = opt
        else:
            value = opt
            label = opt
        cleaned.append((str(label).strip(), str(value).strip()))
    return cleaned


def _load_choice_options(field_name: str):
    if not TEMPLATE_PATH.exists():
        return []
    with TEMPLATE_PATH.open("rb") as handle:
        reader = PyPDF2.PdfReader(handle)
        fields = reader.get_fields() or {}
        field = fields.get(field_name, {})
        options = field.get("/Opt") or []
    cleaned = []
    for opt in options:
        if isinstance(opt, (list, tuple)) and len(opt) == 2:
            value, label = opt
        else:
            value = opt
            label = opt
        cleaned.append((str(label).strip(), str(value).strip()))
    return cleaned


def _match_contract_option(contract_name: str, options):
    if not contract_name:
        return 0
    normalized_contract = _normalize_label(contract_name)
    for idx, (label, _value) in enumerate(options):
        if normalized_contract and normalized_contract in _normalize_label(label):
            return idx
    return 0


def _build_envelope_text(objectives):
    base_text = (
        "L'assurance-vie est une enveloppe d'epargne flexible qui permet d'investir sur une large selection de supports "
        "financiers, de faire evoluer votre allocation selon vos objectifs et de beneficier d'une fiscalite avantageuse "
        "au fil du temps. Elle permet egalement de preparer la transmission de votre patrimoine dans un cadre souple et "
        "personnalise."
    )

    objective_texts = {
        "Optimiser la rentabilite de ses placements": (
            "Optimiser la rentabilite et valoriser votre epargne en adaptant votre allocation au profil de risque retenu."
        ),
        "Optimiser sa fiscalite": (
            "Optimiser la fiscalite de votre epargne en tirant parti du cadre fiscal de l'assurance-vie."
        ),
        "Proteger ses proches": (
            "Organiser la transmission de votre patrimoine et proteger vos proches grace aux beneficiaires designes."
        ),
        "Proteger le conjoint survivant": (
            "Renforcer la protection du conjoint survivant via la clause beneficiaire."
        ),
        "Preparer la transmission de son patrimoine": (
            "Preparer la transmission de votre patrimoine en beneficiant des specificites de l'assurance-vie."
        ),
        "Financer un achat immobilier": (
            "Se constituer un capital a terme pour financer un projet immobilier."
        ),
    }

    selected_objectives = [objective_texts[obj] for obj in objectives if obj in objective_texts]
    if selected_objectives:
        return base_text + "\n\n" + "\n\n".join(selected_objectives)
    return base_text


def _load_mandataire_defaults():
    if not MANDATAIRE_PATH.exists():
        return {}
    try:
        with MANDATAIRE_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _load_top_funds():
    if not TOP_FUNDS_PATH.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(TOP_FUNDS_PATH, sep=";", decimal=",", encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(TOP_FUNDS_PATH, sep=";", decimal=",", encoding="latin-1")
    if "Nom" not in df.columns and "Nom du fonds" in df.columns:
        df = df.rename(columns={"Nom du fonds": "Nom"})
    if "Code ISIN" not in df.columns:
        df["Code ISIN"] = ""
    if "Nom" not in df.columns:
        df["Nom"] = ""
    df = df[["Nom", "Code ISIN"]].dropna(how="all").drop_duplicates()
    df["Nom"] = df["Nom"].astype(str).str.strip()
    df["Code ISIN"] = df["Code ISIN"].astype(str).str.strip().str.upper()

    # Keep only valid ISINs to avoid header/portfolio rows.
    df = df[df["Code ISIN"].str.match(r"^[A-Z0-9]{12}$", na=False)]
    return df


def _load_catalogue_funds():
    if not CATALOGUE_PATH.exists():
        return pd.DataFrame(columns=["Nom", "Code ISIN"])
    try:
        with CATALOGUE_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return pd.DataFrame(columns=["Nom", "Code ISIN"])
    if not isinstance(data, list):
        return pd.DataFrame(columns=["Nom", "Code ISIN"])
    df = pd.DataFrame(data)
    if "Nom" not in df.columns:
        df["Nom"] = ""
    if "Code ISIN" not in df.columns:
        df["Code ISIN"] = ""
    df = df[["Nom", "Code ISIN"]].dropna(how="all").drop_duplicates()
    df["Nom"] = df["Nom"].astype(str).str.strip()
    df["Code ISIN"] = df["Code ISIN"].astype(str).str.strip().str.upper()
    return df


def _call_gemini_extract(pdf_bytes, api_key, model_name="gemini-1.5-flash-latest"):
    prompt = (
        "Extrais les donnees d'arbitrage de ce document. "
        "Commence par extraire chaque ligne du tableau avec les colonnes : "
        "'nom', 'isin', 'situation_actuelle', 'desinvestissement', 'investissement', 'situation_cible'. "
        "Les pourcentages doivent etre des nombres reels (utilise null si la cellule est vide ou '-'). "
        "Affiche uniquement un objet JSON avec une cle 'lignes' (liste d'objets). "
        "Ensuite, pour construire les listes d'arbitrage : "
        "- 'desinvestissements' = lignes avec desinvestissement non nul. "
        "- 'investissements' = lignes avec investissement non nul. "
        "Ne pas utiliser 'situation_actuelle' ni 'situation_cible' pour arbitrer."
    )

    body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "application/pdf",
                            "data": base64.b64encode(pdf_bytes).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "response_mime_type": "application/json",
        },
    }

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + model_name
        + ":generateContent?key="
        + api_key
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Erreur Gemini: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Erreur Gemini: {exc.reason}") from exc

    payload = json.loads(raw)
    candidates = payload.get("candidates", [])
    if not candidates:
        raise RuntimeError("Aucune reponse Gemini.")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError("Reponse Gemini invalide.")

    text = parts[0].get("text", "")
    if not text:
        raise RuntimeError("Reponse Gemini vide.")

    data = json.loads(text)
    if "desinvestissements" in data and "investissements" in data:
        return data

    lignes = data.get("lignes", [])
    desinvestissements = []
    investissements = []
    for row in lignes:
        name = row.get("nom")
        isin = row.get("isin")
        des = row.get("desinvestissement")
        inv = row.get("investissement")
        if des not in (None, 0, "", "-"):
            desinvestissements.append({"nom": name, "isin": isin, "pourcentage": float(des)})
        if inv not in (None, 0, "", "-"):
            investissements.append({"nom": name, "isin": isin, "pourcentage": float(inv)})

    return {"desinvestissements": desinvestissements, "investissements": investissements}


def _list_gemini_models(api_key):
    url = "https://generativelanguage.googleapis.com/v1beta/models?key=" + api_key
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Erreur Gemini: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Erreur Gemini: {exc.reason}") from exc

    payload = json.loads(raw)
    models = payload.get("models", [])
    names = [m.get("name", "") for m in models if m.get("name")]
    return [name.replace("models/", "") for name in names]


def _rows_from_extraction(data, key, percent_col):
    rows = []
    items = data.get(key, []) or []
    if items:
        key_name = "desinvestissement" if "Desinvest" in percent_col else "investissement"
        for item in items:
            pct = item.get("pourcentage")
            if pct is None:
                pct = item.get(key_name)
            if pct is None:
                continue
            rows.append({
                "Support": (item.get("nom") or "").strip(),
                "Code ISIN": (item.get("isin") or "").strip(),
                percent_col: float(pct),
            })
        return rows

    lignes = data.get("lignes", []) or []
    if lignes:
        key_name = "desinvestissement" if "Desinvest" in percent_col else "investissement"
        for row in lignes:
            pct = row.get(key_name)
            if pct in (None, 0, "", "-"):
                continue
            rows.append({
                "Support": (row.get("nom") or "").strip(),
                "Code ISIN": (row.get("isin") or "").strip(),
                percent_col: float(pct),
            })
    return rows


def _format_support_list(rows, percent_key):
    parts = []
    for row in rows:
        support = row.get("Support", "")
        isin = row.get("Code ISIN", "")
        ratio = row.get(percent_key, 0)
        if support and ratio:
            isin_label = f" ({isin})" if isin else ""
            parts.append(f"{ratio} % du fonds {support}{isin_label}")
    return ", ".join(parts)


def _format_support_lines(rows, percent_key):
    lines = []
    for row in rows:
        support = row.get("Support", "")
        isin = row.get("Code ISIN", "")
        ratio = row.get(percent_key, 0)
        if support and ratio:
            isin_label = f" ({isin})" if isin else ""
            lines.append(f"{support}{isin_label} - {ratio} %")
    return "\n".join(lines)


def _build_allocation_text(operation_type, montant, periodicite, profile_choice, desinvest_rows, invest_rows):
    lines = []

    if operation_type:
        base = f"Nous avons evoque votre souhait de mettre en place {operation_type.lower()}."
        if montant:
            base += f" Le montant de l'operation est de {montant} EUR"
            if periodicite:
                base += f" avec une periodicite {periodicite}"
            base += "."
        lines.append(base)

    if operation_type == "Arbitrage":
        if desinvest_rows or invest_rows:
            lines.append("J'effectue un arbitrage au sein de la gestion libre de votre contrat qui consiste a :")
        if desinvest_rows:
            lines.append("Desinvestir les supports suivants :")
            lines.append(_format_support_list(desinvest_rows, "Desinvest %"))
        if invest_rows:
            lines.append("Reinvestir sur les supports suivants :")
            lines.append(_format_support_list(invest_rows, "Invest %"))

    return "\n".join([line for line in lines if line])


def _fill_pdf(fields, button_values=None, choice_indices=None):
    def to_pdf_value(value):
        if isinstance(value, str) and value.startswith("/"):
            return PdfName(value[1:])
        return PdfString.encode(str(value))

    reader = PdfReader(str(TEMPLATE_PATH))
    if reader.Root.AcroForm:
        reader.Root.AcroForm.update(PdfDict(NeedAppearances=PdfObject("true")))
    reader.Root.OpenAction = PdfDict(
        S=PdfName.JavaScript,
        JS=PdfString.encode("this.calculateNow();")
    )

    for page in reader.pages:
        if not page.Annots:
            continue
        for annot in page.Annots:
            parent = annot.get("/Parent")
            if parent and button_values:
                parent_name = PdfString.decode(parent.get("/T")) if parent.get("/T") else None
                if parent_name and parent_name in button_values:
                    pdf_value = to_pdf_value(button_values[parent_name])
                    parent.V = pdf_value
                    if annot.AP and annot.AP.get("/N") and pdf_value in annot.AP.get("/N"):
                        annot.AS = pdf_value
                    else:
                        annot.AS = PdfName("Off")

            field_name = PdfString.decode(annot.T) if annot.T else None
            target = annot
            if field_name is None and parent and parent.get("/T"):
                field_name = PdfString.decode(parent.get("/T"))
                target = parent
            if not field_name:
                continue
            if field_name not in fields and (not button_values or field_name not in button_values):
                continue
            value = fields.get(field_name)
            if value is None and button_values and field_name in button_values:
                value = button_values[field_name]
            if value is None:
                continue

            field_type = target.FT or target.get("/FT") or annot.FT or annot.get("/FT")
            pdf_value = to_pdf_value(value)
            target.V = pdf_value
            if parent and parent.get("/T") and PdfString.decode(parent.get("/T")) == field_name:
                parent.V = pdf_value
            if field_type == PdfName("Btn"):
                annot.AS = pdf_value
            elif field_type == PdfName("Ch"):
                if choice_indices and field_name in choice_indices:
                    target.I = [PdfObject(str(choice_indices[field_name]))]
            else:
                if annot.AP:
                    annot.AP = None

    output = BytesIO()
    PdfWriter().write(output, reader)
    return output.getvalue()


def _split_client_name(full_name: str):
    if not full_name:
        return "", ""
    parts = full_name.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _file_safe_name(value: str) -> str:
    cleaned = _normalize_label(value).replace(" ", "_")
    return cleaned or "investisseur"


def _is_av_contract(value: str) -> bool:
    if not value:
        return False
    upper = value.upper()
    return "AV" in upper or "ASSURANCE" in upper


def main():
    st.title("Fiche conseil Assurance-vie")

    ss.pop("arbitrage_manual_custom_funds", None)
    ss.pop("arbitrage_custom_name", None)
    ss.pop("arbitrage_custom_isin", None)
    ss.pop("arbitrage_custom_add", None)

    if "df_contrat_selected" not in ss or ss["df_contrat_selected"].empty:
        st.info("Veuillez selectionner un contrat dans la page 'Selection contrat'.")
        return

    df_contrat_selected = ss["df_contrat_selected"]
    contrat_enveloppe = df_contrat_selected["Enveloppe"].iloc[0] if "Enveloppe" in df_contrat_selected.columns else ""
    if not _is_av_contract(str(contrat_enveloppe)):
        st.warning("La fiche Assurance-vie est reservee aux contrats d'assurance-vie. Le contrat selectionne n'est pas une assurance-vie.")
        return

    contract_options = _load_contract_options()
    contract_labels = [label for label, _value in contract_options] or [" "]

    contrat_name = ""
    if "Contrat" in df_contrat_selected.columns:
        contrat_name = str(df_contrat_selected["Contrat"].iloc[0])
    elif "Partenaire" in df_contrat_selected.columns:
        contrat_name = str(df_contrat_selected["Partenaire"].iloc[0])

    default_contract_idx = _match_contract_option(contrat_name, contract_options)

    st.subheader("Informations contractuelles")
    col1, col2 = st.columns(2)
    titulaire = str(df_contrat_selected["Titulaire(s)"].iloc[0]) if "Titulaire(s)" in df_contrat_selected.columns else ""
    default_nom, default_prenom = _split_client_name(titulaire)
    with col1:
        nom_client = st.text_input("Nom du client", value=default_nom)
        prenom_client = st.text_input("Prenom du client", value=default_prenom)
    with col2:
        compagnie = st.text_input(
            "Compagnie",
            value=str(df_contrat_selected["Partenaire"].iloc[0]) if "Partenaire" in df_contrat_selected.columns else ""
        )
        numcontrat = st.text_input(
            "Numero de contrat",
            value=str(df_contrat_selected["N° de contrat"].iloc[0]) if "N° de contrat" in df_contrat_selected.columns else ""
        )

    contrat_select_label = st.selectbox(
        "Contrat (menu deroulant PDF)",
        options=contract_labels,
        index=default_contract_idx if contract_labels else 0
    )

    st.subheader("Mandataire habilite")
    mandataire_defaults = _load_mandataire_defaults()
    col3, col4, col5 = st.columns(3)
    with col3:
        nomcslt = st.text_input("Nom", value=str(mandataire_defaults.get("nom", "")))
    with col4:
        prenomcslt = st.text_input("Prenom", value=str(mandataire_defaults.get("prenom", "")))
    with col5:
        raisonsociale = st.text_input("Raison sociale", value=str(mandataire_defaults.get("raison_sociale", "")))

    st.subheader("Motivations")
    objectives = st.multiselect(
        "Objectifs",
        list(OBJECTIVE_FIELD_MAP.keys()),
        default=["Optimiser la rentabilite de ses placements", "Optimiser sa fiscalite"]
    )

    with st.expander("Texte enveloppe", expanded=False):
        envelope_text = st.text_area(
            "Votre enveloppe financiere",
            value=_build_envelope_text(objectives),
            height=220
        )

    st.subheader("Operation et allocation")
    df_allocations_client = ss.get("df_allocations_client", pd.DataFrame())
    operation_type = "Arbitrage"
    tab_manual, tab_pdf = st.tabs(["Arbitrage manuel", "Extraction PDF (Gemini)"])
    with tab_manual:
        st.write("Definissez les desinvestissements depuis les fonds du contrat, puis selectionnez les fonds a investir.")
        total_reinvest = 0.0
        if df_allocations_client.empty:
            st.info("Aucun fonds du contrat n'est charge. Importez les allocations pour pre-remplir le tableau.")
            ss["arbitrage_manual_desinvest_rows"] = []
        else:
            encours_col = None
            if "Encours en €" in df_allocations_client.columns:
                encours_col = "Encours en €"
            elif "Encours en EUR" in df_allocations_client.columns:
                encours_col = "Encours en EUR"

            base_cols = ["Support", "Code ISIN"]
            if encours_col:
                base_cols.append(encours_col)

            df_desinvest_base = df_allocations_client[base_cols].copy()
            df_desinvest_base["Desinvest %"] = 0.0

            df_prev_desinvest = ss.get("arbitrage_manual_desinvest_df", pd.DataFrame())
            if not df_prev_desinvest.empty:
                df_prev_desinvest = df_prev_desinvest[["Support", "Code ISIN", "Desinvest %"]]
                df_desinvest_base = df_desinvest_base.merge(
                    df_prev_desinvest,
                    on=["Support", "Code ISIN"],
                    how="left",
                    suffixes=("", "_prev"),
                )
                df_desinvest_base["Desinvest %"] = df_desinvest_base["Desinvest %_prev"].fillna(
                    df_desinvest_base["Desinvest %"]
                )
                df_desinvest_base.drop(columns=["Desinvest %_prev"], inplace=True)

            disabled_cols = ["Support", "Code ISIN"]
            if encours_col:
                disabled_cols.append(encours_col)

            desinvest_df = st.data_editor(
                df_desinvest_base,
                hide_index=True,
                disabled=disabled_cols,
                key="arbitrage_manual_desinvest_table",
                column_config={
                    "Desinvest %": st.column_config.NumberColumn(
                        "Desinvest %",
                        help="Pourcentage de desinvestissement par support",
                        min_value=0,
                        max_value=100,
                        step=1,
                        format="%d %%",
                    )
                },
            )
            ss["arbitrage_manual_desinvest_df"] = desinvest_df

            desinvest_rows = []
            if not desinvest_df.empty:
                for _, row in desinvest_df.iterrows():
                    pct = pd.to_numeric(row.get("Desinvest %"), errors="coerce")
                    if pct and pct > 0:
                        desinvest_rows.append(
                            {
                                "Support": row.get("Support", ""),
                                "Code ISIN": row.get("Code ISIN", ""),
                                "Desinvest %": float(pct),
                            }
                        )
            ss["arbitrage_manual_desinvest_rows"] = desinvest_rows

            if encours_col and not desinvest_df.empty:
                pct_values = pd.to_numeric(desinvest_df["Desinvest %"], errors="coerce").fillna(0)
                encours_values = pd.to_numeric(desinvest_df[encours_col], errors="coerce").fillna(0)
                total_reinvest = (pct_values * encours_values / 100).sum()
                st.metric("Montant total a reinvestir", f"{total_reinvest:,.2f} EUR")

        top_funds_df = _load_top_funds()
        catalogue_df = _load_catalogue_funds()
        if top_funds_df.empty:
            st.info("Aucun fichier de fonds disponible dans 00_Exports/3_Fonds/Export_Top_10_test.csv.")
            top_funds_df = pd.DataFrame(columns=["Nom", "Code ISIN"])
        if catalogue_df.empty:
            catalogue_df = pd.DataFrame(columns=["Nom", "Code ISIN"])

        available_funds_df = pd.concat([top_funds_df, catalogue_df], ignore_index=True).drop_duplicates()
        if available_funds_df.empty:
            ss["arbitrage_manual_invest_rows"] = []
        else:
            available_funds_df = available_funds_df.copy()
            def _label_row(row):
                if "Nom" in row:
                    name = str(row["Nom"]).strip()
                else:
                    name = str(row.get("Support", "")).strip()
                isin = str(row.get("Code ISIN", "")).strip()
                return f"{name} ({isin})" if isin else name

            available_funds_df["Label"] = available_funds_df.apply(_label_row, axis=1)
            options = sorted(available_funds_df["Label"].unique())
            selected_default = ss.get("arbitrage_manual_funds", []) or []
            df_prev_invest = ss.get("arbitrage_manual_invest_df", pd.DataFrame())
            if selected_default == [] and not df_prev_invest.empty:
                df_prev_invest = df_prev_invest[["Support", "Code ISIN"]].copy()
                df_prev_invest["Label"] = df_prev_invest.apply(_label_row, axis=1)
                selected_default = df_prev_invest["Label"].tolist()
            selected_default = [label for label in selected_default if label in options]
            use_default = "arbitrage_manual_funds" not in ss
            multiselect_kwargs = {
                "label": "Fonds disponibles",
                "options": options,
                "key": "arbitrage_manual_funds",
            }
            if use_default:
                multiselect_kwargs["default"] = selected_default
            selected_labels = st.multiselect(**multiselect_kwargs)
            selected_df = available_funds_df[available_funds_df["Label"].isin(selected_labels)][["Nom", "Code ISIN"]].drop_duplicates()

            if selected_df.empty:
                st.info("Selectionnez un ou plusieurs fonds pour construire le tableau d'investissement.")
                ss["arbitrage_manual_invest_rows"] = []
            else:
                invest_base = selected_df.rename(columns={"Nom": "Support"}).copy()
                invest_base["Invest %"] = 0.0

                df_prev_invest = ss.get("arbitrage_manual_invest_df", pd.DataFrame())
                if not df_prev_invest.empty:
                    df_prev_invest = df_prev_invest[["Support", "Code ISIN", "Invest %"]]
                    invest_base = invest_base.merge(
                        df_prev_invest,
                        on=["Support", "Code ISIN"],
                        how="left",
                        suffixes=("", "_prev"),
                    )
                    invest_base["Invest %"] = invest_base["Invest %_prev"].fillna(invest_base["Invest %"])
                    invest_base.drop(columns=["Invest %_prev"], inplace=True)

                invest_base["Somme reinvestie (EUR)"] = (
                    pd.to_numeric(invest_base["Invest %"], errors="coerce").fillna(0) * total_reinvest / 100
                )

                invest_df = st.data_editor(
                    invest_base,
                    hide_index=True,
                    disabled=["Support", "Code ISIN", "Somme reinvestie (EUR)"],
                    key="arbitrage_manual_invest_table",
                    column_config={
                        "Invest %": st.column_config.NumberColumn(
                            "Invest %",
                            help="Pourcentage d'investissement par support",
                            min_value=0,
                            max_value=100,
                            step=1,
                            format="%d %%",
                        ),
                        "Somme reinvestie (EUR)": st.column_config.NumberColumn(
                            "Somme reinvestie (EUR)",
                            help="Montant reinvesti en EUR en fonction du pourcentage saisi",
                            format="%.2f EUR",
                        )
                    },
                )

                prev_invest_df = ss.get("arbitrage_manual_invest_df", pd.DataFrame())
                invest_df["Somme reinvestie (EUR)"] = (
                    pd.to_numeric(invest_df["Invest %"], errors="coerce").fillna(0) * total_reinvest / 100
                )
                ss["arbitrage_manual_invest_df"] = invest_df

                should_rerun = False
                if not prev_invest_df.empty:
                    prev_compare = prev_invest_df[["Support", "Code ISIN", "Invest %"]].copy()
                    prev_compare["Invest %"] = pd.to_numeric(prev_compare["Invest %"], errors="coerce").fillna(0)

                    curr_compare = invest_df[["Support", "Code ISIN", "Invest %"]].copy()
                    curr_compare["Invest %"] = pd.to_numeric(curr_compare["Invest %"], errors="coerce").fillna(0)

                    compare_df = curr_compare.merge(
                        prev_compare,
                        on=["Support", "Code ISIN"],
                        how="outer",
                        suffixes=("_curr", "_prev"),
                    ).fillna(0)
                    should_rerun = not (compare_df["Invest %_curr"] - compare_df["Invest %_prev"]).abs().le(1e-9).all()

                if should_rerun:
                    st.rerun()

                invest_rows = []
                for _, row in invest_df.iterrows():
                    pct = pd.to_numeric(row.get("Invest %"), errors="coerce")
                    if pct and pct > 0:
                        invest_rows.append(
                            {
                                "Support": row.get("Support", ""),
                                "Code ISIN": row.get("Code ISIN", ""),
                                "Invest %": float(pct),
                            }
                        )
                ss["arbitrage_manual_invest_rows"] = invest_rows

                total_invest = pd.to_numeric(invest_df["Invest %"], errors="coerce").fillna(0).sum()
                if total_invest and abs(total_invest - 100) > 0.01:
                    st.warning(f"La somme des investissements est de {total_invest:.2f} %, elle doit etre egale a 100 %.")

    with tab_pdf:
        pdf_file = st.file_uploader("PDF arbitrage", type=["pdf"], key="arbitrage_pdf")
        with st.expander("Extraction d'arbitrage (Gemini)"):
            model_options = ss.get("gemini_models") or [
                "gemini-2.5-pro",
                "gemini-2.5-flash",
                "gemini-1.5-pro",
                "gemini-1.5-flash",
            ]
            default_model = "gemini-2.5-flash"
            default_index = model_options.index(default_model) if default_model in model_options else 0
            col_key, col_model = st.columns([2, 2])
            with col_key:
                api_key = st.text_input("Cle API Gemini", type="password")
            with col_model:
                model_name = st.selectbox("Modele Gemini", options=model_options, index=default_index)
            col_list, col_extract = st.columns([1, 1])
            with col_list:
                list_models = st.button("Lister les modeles")
            with col_extract:
                extract_arbitrage = st.button("Extraire l'arbitrage")
            if list_models:
                if not api_key:
                    st.warning("Cle API requise.")
                else:
                    try:
                        models = _list_gemini_models(api_key)
                        ss["gemini_models"] = models
                    except Exception as exc:
                        st.error(str(exc))
            if extract_arbitrage:
                if not api_key or not pdf_file:
                    st.warning("Cle API et PDF requis.")
                else:
                    try:
                        data = _call_gemini_extract(pdf_file.getvalue(), api_key, model_name=model_name)
                        ss["arbitrage_extraction"] = data
                        st.success("Extraction terminee.")
                    except Exception as exc:
                        st.error(str(exc))
            if "arbitrage_extraction" in ss:
                st.json(ss["arbitrage_extraction"], expanded=False)

    montant_operation = ""
    periodicite = ""

    manual_desinvest_rows = ss.get("arbitrage_manual_desinvest_rows", [])
    manual_invest_rows = ss.get("arbitrage_manual_invest_rows", [])

    if manual_desinvest_rows or manual_invest_rows:
        desinvest_rows = manual_desinvest_rows
        invest_rows = manual_invest_rows
    elif operation_type == "Arbitrage" and "arbitrage_extraction" in ss:
        desinvest_rows = _rows_from_extraction(
            ss["arbitrage_extraction"],
            "desinvestissements",
            "Desinvest %",
        )
        invest_rows = _rows_from_extraction(
            ss["arbitrage_extraction"],
            "investissements",
            "Invest %",
        )
    else:
        desinvest_rows = []
        invest_rows = []

    st.subheader("Profil de risque")
    profile_choice = st.selectbox(
        "Profil accepte",
        ["Securise", "Prudent", "Equilibre", "Dynamique"],
        index=2
    )
    profile_target = st.selectbox(
        "Profil allocation cible",
        ["Securise", "Prudent", "Equilibre", "Dynamique"],
        index=2
    )

    st.subheader("Horizon")
    horizon_labels = [
        "< 2 ans",
        "entre 2 et 5 ans",
        "entre 5 et 8 ans",
        "> 8 ans",
        "Retraite",
    ]
    horizon_choice = st.selectbox(
        "Horizon d'investissement",
        horizon_labels,
        index=2,
    )

    st.subheader("Objectif d'arbitrage")
    st.subheader("Nature de l'arbitrage")
    nature_choices = st.multiselect(
        "Nature",
        [
            "Modification de la selection des supports",
            "Reequilibrage du portefeuille",
            "Autres",
        ],
        default=["Modification de la selection des supports"],
    )
    autres_nature = ""
    if "Autres" in nature_choices:
        autres_nature = st.text_input("Autres (preciser)", value="")

    objectif_options = _load_choice_options("objectifarbitrage")
    objectif_labels = [label for label, _value in objectif_options]
    default_objectif = "Changement support(s) / Optimisation de la sélection des supports"
    default_objectif_idx = objectif_labels.index(default_objectif) if default_objectif in objectif_labels else 0
    objectif_label = st.selectbox(
        "Objectif",
        options=objectif_labels,
        index=default_objectif_idx if objectif_labels else None
    )
    justif_kwargs = {
        "label": "Justification",
        "height": 120,
        "key": "av_justif_arbitrage",
    }
    if "av_justif_arbitrage" not in ss:
        justif_kwargs["value"] = ""
    justif_arbitrage = st.text_area(**justif_kwargs)

    option_choices = _load_choice_options("options")
    option_labels = [label for label, _value in option_choices]
    option_label = st.selectbox(
        "Option",
        options=option_labels,
        index=0 if option_labels else None
    )

    desinvest_text = _format_support_lines(desinvest_rows, "Desinvest %")
    invest_text = _format_support_lines(invest_rows, "Invest %")
    allocation_text = "\n".join([part for part in [desinvest_text, invest_text] if part])

    st.subheader("Apercu fiche conseil")
    col_left, col_right = st.columns(2)
    with col_left:
        st.text_area(
            "Supports desinvestis (fiche conseil)",
            value=desinvest_text,
            height=140,
            disabled=True,
        )
    with col_right:
        st.text_area(
            "Supports investis (fiche conseil)",
            value=invest_text,
            height=140,
            disabled=True,
        )

    if not TEMPLATE_PATH.exists():
        st.error("Le fichier PDF modele est introuvable. Verifiez le chemin pdf/AV/Fiche Conseil Assurance Vie Arbitrage 03-25.pdf.")
        return

    contract_value = ""
    contract_index = None
    for idx, (label, value) in enumerate(contract_options):
        if label == contrat_select_label:
            contract_value = value
            contract_index = idx
            break

    choice_indices = {}
    if contract_index is not None:
        choice_indices["choixcontrat"] = contract_index

    if objectif_label in objectif_labels:
        choice_indices["objectifarbitrage"] = objectif_labels.index(objectif_label)
    if option_label in option_labels:
        choice_indices["options"] = option_labels.index(option_label)

    profil_map = {
        "Securise": "/Choix1",
        "Prudent": "/Choix2",
        "Equilibre": "/Choix3",
        "Dynamique": "/Choix4",
    }
    profilcible_map = {
        "Securise": "/1",
        "Prudent": "/2",
        "Equilibre": PROFILE_BALANCED_VALUE,
        "Dynamique": "/4",
    }
    profil_code_map = {
        "Securise": "1",
        "Prudent": "2",
        "Equilibre": "3",
        "Dynamique": "4",
    }

    objectif_value = dict(objectif_options).get(objectif_label, objectif_label)

    form_fields = {
        "Nomclient": nom_client,
        "Prenomclient": prenom_client,
        "Nomclient2": nom_client,
        "Prenomclient2": prenom_client,
        "Nomconsultant": nomcslt,
        "Prenomconsultant": prenomcslt,
        "Raisonsociale": raisonsociale,
        "compagnie": compagnie,
        "enveloppe": numcontrat,
        "Profilaccepte": profile_choice,
        "Profilallocode": profil_code_map.get(profile_target, "3"),
        "horizonretraite": horizon_choice,
        "objectifarbitrage": objectif_value or "",
        "justifmotifarbitrage": justif_arbitrage,
        "justifautre": autres_nature,
        "Justifoption": autres_nature,
        "RemarqueGestionlibre": allocation_text,
        "TexteGestionPilote": allocation_text,
        "TexteGestionProfile": allocation_text,
    }

    if contract_value:
        form_fields["choixcontrat"] = contract_value
    if option_label:
        option_value = dict(option_choices).get(option_label, option_label)
        form_fields["options"] = option_value

    desinvest_text = _format_support_lines(desinvest_rows, "Desinvest %")
    invest_text = _format_support_lines(invest_rows, "Invest %")
    form_fields["JustifVC"] = desinvest_text
    form_fields["JustifVC2"] = invest_text
    form_fields["Justifdyna"] = desinvest_text
    form_fields["Justidyna2"] = invest_text

    form_fields["Profilacceptecode"] = profil_code_map.get(profile_choice, "3")

    for objective in objectives:
        field_name = OBJECTIVE_FIELD_MAP.get(objective)
        if field_name:
            form_fields[field_name] = "/Oui"

    if st.button("Generer la fiche Assurance-vie"):
        horizon_map = {
            "< 2 ans": "/1",
            "entre 2 et 5 ans": "/2",
            "entre 5 et 8 ans": "/3",
            "> 8 ans": "/4",
            "Retraite": "/5",
        }
        button_values = {
            "profil": profil_map.get(profile_choice, "/Choix3"),
            "profilcible": profilcible_map.get(profile_target, PROFILE_BALANCED_VALUE),
            "horizon": horizon_map.get(horizon_choice, "/3"),
            "SelectionGestionlibre": "/1",
        }
        if "Modification de la selection des supports" in nature_choices:
            button_values["Selectop"] = "/2"
        if "Reequilibrage du portefeuille" in nature_choices:
            button_values["Selectop2"] = "/5"
        if "Autres" in nature_choices:
            button_values["Selectop3"] = "/6"
        pdf_bytes = _fill_pdf(
            form_fields,
            button_values=button_values,
            choice_indices=choice_indices,
        )
        investor_file_label = "_".join(
            part for part in [_file_safe_name(prenom_client), _file_safe_name(nom_client)] if part
        )
        st.download_button(
            label="Telecharger la fiche Assurance-vie remplie",
            data=pdf_bytes,
            file_name=f"Fiche_AV_{investor_file_label}.pdf",
            mime="application/pdf"
        )


if __name__ == "__main__":
    main()
