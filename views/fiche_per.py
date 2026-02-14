import streamlit as st
from streamlit import session_state as ss

from datetime import date
from io import BytesIO
import base64
import json
import re
import zlib
import urllib.error
import urllib.request

import pandas as pd
from pathlib import Path

import PyPDF2
from pdfrw import PdfDict, PdfName, PdfObject, PdfReader, PdfString, PdfWriter

TEMPLATE_PATH = Path("pdf/PER/Fiche Conseil Vierge Courtage PPv3.pdf")
MANDATAIRE_PATH = Path("mandataire.json")
HORIZON_RETIREMENT_VALUE = "/5"
PROFILE_BALANCED_VALUE = "/3"
OBJECTIVE_FIELD_MAP = {
    "Optimiser sa fiscalite": "cac_objectif_1[0]",
    "Optimiser la rentabilite de ses placements": "cac_objectif_2[0]",
    "Aider ses enfants": "cac_objectif_3[0]",
    "Proteger le conjoint survivant": "cac_objectif_4[0]",
    "Proteger ses proches": "cac_objectif_5[0]",
    "Preparer sa retraite": "cac_objectif_6[0]",
    "Financer un achat immobilier": "cac_objectif_7[0]",
    "Preparer la transmission de son patrimoine": "cac_objectif_8[0]",
    "Preparer la transmission de son entreprise": "cac_objectif_9[0]",
    "Obtenir des revenus complementaires": "cac_objectif_10[0]",
    "Se constituer un patrimoine": "cac_objectif_11[0]",
    "Se constituer une epargne de precaution": "cac_objectif_12[0]",
    "Placer des liquidites a court terme": "cac_objectif_13[0]",
    "Se premunir contre les accidents de la vie": "cac_objectif_14[0]",
}


def _normalize_label(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum() or ch.isspace()).strip()


def _load_contract_options():
    if not TEMPLATE_PATH.exists():
        return []

    with TEMPLATE_PATH.open("rb") as handle:
        reader = PyPDF2.PdfReader(handle)
        fields = reader.get_fields() or {}
        field = fields.get("nomcontrat", {})
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
        "Le PER permet d'acceder a une solution d'epargne complete pour preparer la retraite, "
        "completer ses revenus a terme, proteger ses proches tout en beneficiant d'une optimisation fiscale "
        "grace a la deductibilite des versements. Cette solution d'epargne souple permet une approche "
        "personnalisee, sur-mesure et evolutive tout au long de la vie pour constituer son capital et "
        "completer ses revenus a la retraite a son rythme en fonction de ses besoins et de sa capacite financiere. "
        "Au deces, l'epargne residuelle est transmise aux beneficiaires de son choix permettant d'assurer la protection "
        "de ses proches librement."
    )

    objective_texts = {
        "Preparer sa retraite": (
            "Preparer votre retraite en constituant un capital permettant d'obtenir des revenus complementaires a terme "
            "en fonction de vos besoins (sortie en capital total ou fractionne, ou rente). Dans ce cadre, vous beneficiez "
            "de la fiscalite specifique du PER suivant la nature des versements effectues a l'origine (deductibles ou non deductibles)."
        ),
        "Obtenir des revenus complementaires": (
            "Preparer votre retraite en constituant un capital permettant d'obtenir des revenus complementaires a terme "
            "en fonction de vos besoins (sortie en capital total ou fractionne, ou rente). Dans ce cadre, vous beneficiez "
            "de la fiscalite specifique du PER suivant la nature des versements effectues a l'origine (deductibles ou non deductibles)."
        ),
        "Optimiser la rentabilite de ses placements": (
            "Optimiser la rentabilite et valoriser votre epargne en beneficiant d'une enveloppe financiere permettant une allocation "
            "d'actifs sur-mesure et evolutive a long terme en fonction de votre profil de risque et de votre horizon de retraite."
        ),
        "Optimiser sa fiscalite": (
            "Optimiser sa fiscalite en beneficiant d'une deduction fiscale sur votre assiette imposable par les versements effectues "
            "dans la limite de vos plafonds de deduction."
        ),
        "Proteger ses proches": (
            "Optimiser la transmission de votre patrimoine en protegeant vos proches en transmettant un capital financier dans le cadre "
            "specifique du PER individuel qui beneficie d'un traitement hors-succession. Vous designez librement vos beneficiaires."
        ),
        "Proteger le conjoint survivant": (
            "Optimiser la transmission de votre patrimoine en protegeant vos proches en transmettant un capital financier dans le cadre "
            "specifique du PER individuel qui beneficie d'un traitement hors-succession. Vous designez librement vos beneficiaires."
        ),
        "Preparer la transmission de son patrimoine": (
            "Optimiser la transmission de votre patrimoine en protegeant vos proches en transmettant un capital financier dans le cadre "
            "specifique du PER individuel qui beneficie d'un traitement hors-succession. Vous designez librement vos beneficiaires."
        ),
        "Preparer la transmission de son entreprise": (
            "Optimiser la transmission de votre patrimoine en protegeant vos proches en transmettant un capital financier dans le cadre "
            "specifique du PER individuel qui beneficie d'un traitement hors-succession. Vous designez librement vos beneficiaires."
        ),
        "Financer un achat immobilier": (
            "Preparer l'acquisition de votre future residence principale en investissant sur une enveloppe PER permettant de se constituer "
            "un capital qui pourra etre investi sur les marches financiers afin de faire travailler votre argent."
        ),
    }

    selected_objectives = [objective_texts[obj] for obj in objectives if obj in objective_texts]
    if selected_objectives:
        return base_text + "\n\n" + "\n\n".join(selected_objectives)
    return base_text


def _build_contract_text(contract_label: str):
    contract_texts = {
        "PERtinence Retraite": (
            "Le PERtinence Retraite distribue par VIE PLUS offre l'ensemble des caracteristiques et standards qualitatifs d'un contrat haut de gamme "
            "(plus de 250 supports financiers, 19 fonds immobiliers ; des modes de gestion libre, pilotee et sous mandat) qui vous permet de beneficier "
            "d'un contrat complet et evolutif pour repondre a l'ensemble de vos besoins et objectifs patrimoniaux."
        ),
        "PER ERES by Swisslife": (
            "Le PER ERES by SwissLife distribue par ERES offre l'ensemble des caracteristiques et standards qualitatifs d'un contrat haut de gamme "
            "(plus de 110 supports financiers, 13 fonds immobiliers ; des modes de gestion libre et pilotee) qui vous permet de beneficier d'un contrat complet "
            "et evolutif pour repondre a l'ensemble de vos besoins et objectifs patrimoniaux. Votre contrat est assure par SwissLife, un des leaders europeens "
            "sur les solutions patrimoniales, permettant d'apporter le maximum de garantie a votre epargne."
        ),
        "PER ERES by Spirica": (
            "Le PER ERES by Spirica distribue par ERES offre l'ensemble des caracteristiques et standards qualitatifs d'un contrat haut de gamme "
            "(plus de 165 supports financiers, 21 fonds immobiliers ; des modes de gestion libre et pilotee) qui vous permet de beneficier d'un contrat complet "
            "et evolutif pour repondre a l'ensemble de vos besoins et objectifs patrimoniaux. Votre contrat est assure par Spirica, specialiste dans la conception "
            "et la gestion de solutions patrimoniales, et beneficia de la solidite du Groupe Credit Agricole."
        ),
        "Premavenir PER": (
            "Le Premavenir PER distribue par ODDO est un contrat dedie permettant d'acceder a la gestion exclusive Oddo BHF avec une poche en multigestion "
            "(33 supports financiers, 1 support immobilier SCI, et des modes de gestion libre et pilotee). Le contrat permet de beneficier d'un contrat complet "
            "pour repondre a l'ensemble de vos besoins et objectifs patrimoniaux. Votre contrat est assure par GENERATION VIE, issue de l'alliance d'Allianz et Oddo BHF."
        ),
        "Cristalliance EvoluPER": (
            "Le contrat EvoluPER distribue par APICIL offre l'ensemble des caracteristiques et standards qualitatifs d'un contrat haut de gamme "
            "(plus de 270 supports financiers, 33 fonds immobiliers ; des modes de gestion libre, pilotee et sous mandat) qui vous permet de beneficier d'un contrat complet "
            "et evolutif pour repondre a l'ensemble de vos besoins et objectifs patrimoniaux. Votre contrat est assure par Apicil Epargne."
        ),
    }

    for key, text in contract_texts.items():
        if _normalize_label(key) in _normalize_label(contract_label):
            return text
    return ""


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


def _apply_arbitrage_results(df_desinvest, df_invest, data):
    df_desinvest = df_desinvest.copy()
    df_invest = df_invest.copy()

    for item in data.get("desinvestissements", []) or []:
        pct = item.get("pourcentage")
        if pct is None:
            continue
        isin = (item.get("isin") or "").strip().upper()
        nom = (item.get("nom") or "").strip().lower()

        mask = pd.Series([False] * len(df_desinvest))
        if "Code ISIN" in df_desinvest.columns and isin:
            mask = df_desinvest["Code ISIN"].str.upper() == isin
        if not mask.any() and "Support" in df_desinvest.columns and nom:
            mask = df_desinvest["Support"].str.lower() == nom
        if mask.any():
            df_desinvest.loc[mask, "Desinvest %"] = float(pct)
        else:
            df_desinvest = pd.concat([
                df_desinvest,
                pd.DataFrame([
                    {"Support": item.get("nom", ""), "Code ISIN": isin or "", "Encours en EUR": "", "Desinvest %": float(pct)}
                ])
            ], ignore_index=True)

    for item in data.get("investissements", []) or []:
        pct = item.get("pourcentage")
        if pct is None:
            continue
        isin = (item.get("isin") or "").strip().upper()
        nom = (item.get("nom") or "").strip()

        mask = pd.Series([False] * len(df_invest))
        if "Code ISIN" in df_invest.columns and isin:
            mask = df_invest["Code ISIN"].str.upper() == isin
        if not mask.any() and "Support" in df_invest.columns and nom:
            mask = df_invest["Support"].str.lower() == nom.lower()

        if mask.any():
            df_invest.loc[mask, "Invest %"] = float(pct)
        else:
            df_invest = pd.concat([
                df_invest,
                pd.DataFrame([
                    {"Support": nom, "Code ISIN": isin or "", "Invest %": float(pct)}
                ])
            ], ignore_index=True)

    df_desinvest = df_desinvest.drop_duplicates(subset=["Support", "Code ISIN"], keep="last")
    df_invest = df_invest.drop_duplicates(subset=["Support", "Code ISIN"], keep="last")
    return df_desinvest, df_invest


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


def _build_allocation_text(operation_type, montant, periodicite, profile_choice, desinvest_rows, invest_rows, arbitrage_mode=None):
    lines = []

    if operation_type:
        base = f"Nous avons evoque votre souhait de mettre en place {operation_type.lower()}."
        if montant:
            base += f" Le montant de l'operation est de {montant} EUR"
            if periodicite:
                base += f" avec une periodicite {periodicite}"
            base += "."
        lines.append(base)

    #if profile_choice:
    #    lines.append(
    #        f"Cette operation s'inscrit dans un profil de risque {profile_choice.lower()} et respecte votre effort d'epargne ainsi que votre capacite financiere."
    #    )

    if operation_type == "Arbitrage":
        desinvest_list = _format_support_list(desinvest_rows, "Desinvest %")
        invest_list = _format_support_list(invest_rows, "Invest %")
        invest_total = sum(row.get("Invest %", 0) for row in invest_rows)

        if arbitrage_mode == "Arbitrage libre":
            #lines.append(
            #    "Le but de cette partie est de presenter l'operation qui va etre faite (supports desinvestis et reinvestis avec les pourcentages lies)."
            #)
            if profile_choice:
                lines.append(
                    "L'allocation de votre contrat apres arbitrage presente un profil de risque et de rendement pouvant aller jusqu'au profil "
                    f"\"{profile_choice}\" qui est en adequation avec le profil de risque maximum accepte que vous avez selectionne pour ce contrat."
                )
            lines.append(
                "Cette allocation se detaille comme suit pour l'allocation cible de mon contrat apres arbitrage :"
            )
            lines.append(
                "J'effectue un arbitrage au sein de la gestion libre de votre contrat qui consiste a :"
            )
        elif arbitrage_mode == "Fin gestion pilotee":
            lines.append(
                "Actuellement en gestion pilotee, je vous propose d'arreter ce mode de gestion afin de passer en gestion libre "
                "avec l'allocation suivante :"
            )
        elif arbitrage_mode == "Dynamisation progressive":
            lines.append(
                "En complement du present arbitrage, je vous propose la mise en place d'une dynamisation progressive afin de lisser "
                "le point d'entree sur les marches. L'allocation cible respecte votre profil de risque."
            )
        elif arbitrage_mode == "Versements programmes":
            lines.append(
                "Nous avons evoque votre souhait de mettre en place ou modifier des versements programmes en coherence avec votre profil de risque."
            )

        if desinvest_list:
            lines.append(f"Desinvestir {desinvest_list}.")
        if invest_list:
            lines.append(f"Reinvestir {invest_list}.")
            if invest_total and invest_total != 100:
                lines.append("Le total des pourcentages reinvestis doit faire 100 %.")
    else:
        if desinvest_rows:
            lines.append("Supports desinvestis et pourcentages :")
            for row in desinvest_rows:
                support = row.get("Support", "")
                isin = row.get("Code ISIN", "")
                ratio = row.get("Desinvest %", 0)
                lines.append(f"- {support} ({isin}) : {ratio} %")

        if invest_rows:
            lines.append("Supports investis et pourcentages :")
            for row in invest_rows:
                support = row.get("Support", "")
                isin = row.get("Code ISIN", "")
                ratio = row.get("Invest %", 0)
                lines.append(f"- {support} ({isin}) : {ratio} %")

    return "\n".join(lines).strip()


def _extract_calc_map(field_name):
    reader = PdfReader(str(TEMPLATE_PATH))
    target = None
    for page in reader.pages:
        if not page.Annots:
            continue
        for annot in page.Annots:
            if annot.T and PdfString.decode(annot.T) == field_name:
                target = annot
                break
        if target:
            break

    if not target:
        return {}

    aa = target.get("/AA")
    if not aa or not aa.get("/C"):
        return {}

    js = aa.get("/C").get("/JS")
    if not js or not hasattr(js, "stream"):
        return {}

    data = js.stream
    if isinstance(data, str):
        data = data.encode("latin-1")

    try:
        script = zlib.decompress(data).decode("latin-1")
    except Exception:
        return {}

    mapping = {}
    pattern = re.compile(r"numcontrat\s*==\s*(\d+)\)\s*\{event\.target\.value\s*=\s*\"([^\"]*)\";")
    for match in pattern.finditer(script):
        mapping[match.group(1)] = match.group(2)
    return mapping


def _fill_pdf(fields, horizon_value=None, profile_value=None, choice_indices=None):
    def to_pdf_value(value):
        if isinstance(value, str) and value.startswith("/"):
            return PdfName(value[1:])
        return PdfString.encode(str(value))

    nomcontrat_value = fields.get("nomcontrat")
    if "enveloppefiscale" not in fields and nomcontrat_value is not None:
        envelope_map = _extract_calc_map("enveloppefiscale")
        auto_value = envelope_map.get(str(nomcontrat_value))
        if auto_value:
            fields["enveloppefiscale"] = auto_value

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
            if parent and (horizon_value or profile_value):
                parent_name = PdfString.decode(parent.get("/T")) if parent.get("/T") else None
                if parent_name == "horizon" and horizon_value:
                    pdf_value = to_pdf_value(horizon_value)
                    parent.V = pdf_value
                    if annot.AP and annot.AP.get("/N") and pdf_value in annot.AP.get("/N"):
                        annot.AS = pdf_value
                    else:
                        annot.AS = PdfName("Off")
                if parent_name == "Profil" and profile_value:
                    pdf_value = to_pdf_value(profile_value)
                    parent.V = pdf_value
                    if annot.AP and annot.AP.get("/N") and pdf_value in annot.AP.get("/N"):
                        annot.AS = pdf_value
                    else:
                        annot.AS = PdfName("Off")

            if not annot.T:
                continue
            field_name = PdfString.decode(annot.T)
            if field_name not in fields:
                continue
            value = fields[field_name]
            if value is None:
                continue

            field_type = annot.FT or annot.get("/FT")
            pdf_value = to_pdf_value(value)
            annot.V = pdf_value
            if field_type == PdfName("Btn"):
                annot.AS = pdf_value
            elif field_type == PdfName("Ch"):
                if choice_indices and field_name in choice_indices:
                    annot.I = [PdfObject(str(choice_indices[field_name]))]
            else:
                if annot.AP:
                    annot.AP = None

    output = BytesIO()
    PdfWriter().write(output, reader)
    return output.getvalue()


def main():
    st.title("Fiche conseil PER")

    if "df_contrat_selected" not in ss or ss["df_contrat_selected"].empty:
        st.info("Veuillez selectionner un contrat dans la page 'Selection contrat'.")
        return

    df_contrat_selected = ss["df_contrat_selected"]
    contrat_enveloppe = df_contrat_selected["Enveloppe"].iloc[0] if "Enveloppe" in df_contrat_selected.columns else ""
    if contrat_enveloppe != "PER":
        st.warning("La fiche PER est reservee aux contrats PER. Le contrat selectionne n'est pas un PER.")
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
    with col1:
        invest1 = st.text_input(
            "Investisseur principal",
            value=str(df_contrat_selected["Titulaire(s)"].iloc[0]) if "Titulaire(s)" in df_contrat_selected.columns else ""
        )
        numcontrat = st.text_input(
            "Numero de contrat",
            value=str(df_contrat_selected["N° de contrat"].iloc[0]) if "N° de contrat" in df_contrat_selected.columns else ""
        )
    with col2:
        compagnie = st.text_input(
            "Compagnie",
            value=str(df_contrat_selected["Partenaire"].iloc[0]) if "Partenaire" in df_contrat_selected.columns else ""
        )
        signature_date = st.text_input("Date de signature", value=date.today().strftime("%d/%m/%Y"))

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

    st.subheader("Motivations PER")
    objectives = st.multiselect(
        "Objectifs (bonnes pratiques PER)",
        [
            "Optimiser sa fiscalite",
            "Optimiser la rentabilite de ses placements",
            "Aider ses enfants",
            "Proteger le conjoint survivant",
            "Proteger ses proches",
            "Preparer sa retraite",
            "Financer un achat immobilier",
            "Preparer la transmission de son patrimoine",
            "Preparer la transmission de son entreprise",
            "Obtenir des revenus complementaires",
            "Se constituer un patrimoine",
            "Se constituer une epargne de precaution",
            "Placer des liquidites a court terme",
            "Se premunir contre les accidents de la vie",
        ],
        default=["Preparer sa retraite", "Optimiser sa fiscalite"]
    )

    with st.expander("Textes enveloppe et contrat", expanded=False):
        envelope_text = st.text_area(
            "Votre enveloppe financiere",
            value=_build_envelope_text(objectives),
            height=220
        )

        contract_text = st.text_area(
            "Votre contrat",
            value=_build_contract_text(contrat_select_label),
            height=180
        )

    st.subheader("Operation et allocation")
    df_allocations_client = ss.get("df_allocations_client", pd.DataFrame())
    df_portfolio = ss.get("df_portfolio", pd.DataFrame())
    operation_type = "Arbitrage"
    arbitrage_mode = "Arbitrage libre"
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

    if operation_type == "Arbitrage" and "arbitrage_extraction" in ss:
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
        "Profil",
        ["Securise", "Prudent", "Equilibre", "Dynamique"],
        index=2
    )

    if operation_type != "Arbitrage":
        desinvest_rows = []
        invest_rows = []
    allocation_text_default = _build_allocation_text(
        operation_type,
        montant_operation,
        periodicite,
        profile_choice,
        desinvest_rows,
        invest_rows,
        arbitrage_mode,
    )

    if operation_type == "Arbitrage" and "arbitrage_extraction" in ss:
        ss["allocation_text"] = allocation_text_default
    elif "allocation_text" not in ss:
        ss["allocation_text"] = allocation_text_default

    allocation_text = st.text_area(
        "Votre allocation d'actifs et operation",
        key="allocation_text",
        placeholder="Decrire l'allocation proposee (supports et pourcentages).",
        height=180
    )

    if not TEMPLATE_PATH.exists():
        st.error("Le fichier PDF modele est introuvable. Verifiez le chemin pdf/PER/Fiche Conseil Vierge Courtage PPv3.pdf.")
        return

    contract_value = ""
    contract_index = None
    for idx, (label, value) in enumerate(contract_options):
        if label == contrat_select_label:
            contract_value = value
            contract_index = idx
            break

    form_fields = {
        "invest1": invest1,
        "numcontrat": numcontrat,
        "compagnie": compagnie,
        "signature_date_invest[0]": signature_date,
        "nomcslt": nomcslt,
        "prenomcslt": prenomcslt,
        "raisonsociale": raisonsociale,
        "Text1": envelope_text,
        "Text2": contract_text,
        "Text3": allocation_text,
        "Text4": "",
    }

    for objective in objectives:
        field_name = OBJECTIVE_FIELD_MAP.get(objective)
        if field_name:
            form_fields[field_name] = "/1"

    if contract_value:
        form_fields["nomcontrat"] = contract_value

    if st.button("Generer la fiche PER"):
        profile_value = {
            "Securise": "/1",
            "Prudent": "/2",
            "Equilibre": PROFILE_BALANCED_VALUE,
            "Dynamique": "/4",
        }.get(profile_choice, PROFILE_BALANCED_VALUE)
        choice_indices = {"nomcontrat": contract_index} if contract_index is not None else None
        pdf_bytes = _fill_pdf(
            form_fields,
            horizon_value=HORIZON_RETIREMENT_VALUE,
            profile_value=profile_value,
            choice_indices=choice_indices,
        )
        st.download_button(
            label="Telecharger la fiche PER remplie",
            data=pdf_bytes,
            file_name=f"Fiche_PER_{numcontrat or 'contrat'}.pdf",
            mime="application/pdf"
        )


if __name__ == "__main__":
    main()
