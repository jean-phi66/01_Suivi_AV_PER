from __future__ import annotations

from pathlib import Path
import unicodedata

import pandas as pd

from pdf_tri_analysis import DEFAULT_PDF_DIR, analyze_directory, compute_tri_at_valuation


def normalize_contract_number(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def build_contract_aliases(value: object) -> set[str]:
    digits = normalize_contract_number(value)
    if not digits:
        return set()

    aliases = {digits}
    if len(digits) > 9:
        aliases.add(digits[-9:])
    return aliases


def normalize_person_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    tokens = []
    for token in text.upper().replace("-", " ").replace("'", " ").split():
        if token in {"MADAME", "MONSIEUR", "MADEMOISELLE", "MME", "M.", "MLLE"}:
            continue
        cleaned = "".join(ch for ch in token if ch.isalnum())
        if cleaned:
            tokens.append(cleaned)
    return " ".join(tokens)


def load_tri_analyses(pdf_dir: str | Path = DEFAULT_PDF_DIR) -> list[dict[str, object]]:
    return analyze_directory(Path(pdf_dir))


def match_tri_analyses_to_contracts(
    analyses: list[dict[str, object]],
    df_contrats: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, dict[str, object]]]:
    if df_contrats.empty:
        return pd.DataFrame(), {}

    contracts_df = df_contrats.copy()
    contracts_df["app_contract"] = contracts_df["N° de contrat"].astype(str)
    contracts_df["app_contract_key"] = contracts_df["app_contract"].map(normalize_contract_number)
    contracts_df["app_subscriber_key"] = contracts_df["Titulaire(s)"].map(normalize_person_name)

    alias_index: dict[str, set[str]] = {}
    contract_meta: dict[str, dict[str, object]] = {}
    for row in contracts_df[["app_contract", "app_contract_key", "app_subscriber_key", "Titulaire(s)", "Enveloppe", "Partenaire"]].drop_duplicates().itertuples(index=False):
        contract_meta[row.app_contract] = {
            "Titulaire(s)": row[3],
            "Enveloppe": row[4],
            "Partenaire": row[5],
            "app_subscriber_key": row.app_subscriber_key,
            "app_contract_key": row.app_contract_key,
        }
        for alias in build_contract_aliases(row.app_contract):
            alias_index.setdefault(alias, set()).add(row.app_contract)

    matched_rows: list[dict[str, object]] = []
    matched_map: dict[str, dict[str, object]] = {}

    for analysis in analyses:
        if analysis.get("error"):
            continue

        subscriber_key = normalize_person_name(analysis.get("subscriber_name"))
        candidates: set[str] = set()
        for alias in build_contract_aliases(analysis.get("contract_number")):
            candidates.update(alias_index.get(alias, set()))

        if len(candidates) > 1 and subscriber_key:
            filtered = {
                candidate
                for candidate in candidates
                if contract_meta.get(candidate, {}).get("app_subscriber_key") == subscriber_key
            }
            if filtered:
                candidates = filtered

        matched_contract = sorted(candidates)[0] if len(candidates) == 1 else None
        meta = contract_meta.get(matched_contract or "", {})
        matched_analysis = dict(analysis)
        matched_analysis["matched_contract"] = matched_contract

        matched_rows.append(
            {
                "N° de contrat": matched_contract,
                "Contrat PDF": analysis.get("contract_number"),
                "Titulaire(s)": meta.get("Titulaire(s)"),
                "Souscripteur PDF": analysis.get("subscriber_name"),
                "Enveloppe": meta.get("Enveloppe", analysis.get("contract_type")),
                "Partenaire": meta.get("Partenaire"),
                "Date de valorisation TRI": analysis.get("valuation_date"),
                "Valorisation TRI": analysis.get("valuation_amount"),
                "TRI net": analysis.get("tri_net"),
                "TRI brut": analysis.get("tri_gross"),
                "Versements nets": analysis.get("net_payments_total"),
                "Versements bruts": analysis.get("gross_payments_total"),
                "Nb versements": analysis.get("versements_count"),
                "Nb arbitrages": analysis.get("arbitrages_count"),
                "PDF": analysis.get("file_name"),
                "Match trouve": matched_contract is not None,
            }
        )

        if matched_contract:
            matched_map[matched_contract] = matched_analysis

    matched_df = pd.DataFrame(matched_rows)
    if not matched_df.empty:
        matched_df["Date de valorisation TRI"] = pd.to_datetime(
            matched_df["Date de valorisation TRI"], errors="coerce"
        )

    return matched_df, matched_map


def build_contract_tri_history(
    analysis: dict[str, object],
    df_history: pd.DataFrame,
) -> pd.DataFrame:
    if df_history.empty:
        return pd.DataFrame()

    history = df_history.copy()
    history["Date de valorisation"] = pd.to_datetime(history["Date de valorisation"], errors="coerce").dt.normalize()
    history["Valorisation"] = pd.to_numeric(history["Valorisation"], errors="coerce")
    history = history.dropna(subset=["Date de valorisation", "Valorisation"])
    history = history[history["Valorisation"] > 0]
    history = history.sort_values("Date de valorisation").drop_duplicates(
        subset=["Date de valorisation"], keep="last"
    )
    if history.empty:
        return pd.DataFrame()

    movements = analysis.get("movements")
    if movements is None:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for row in history.to_dict("records"):
        valuation_date = pd.Timestamp(row["Date de valorisation"]).normalize()
        valuation_amount = float(row["Valorisation"])
        rows.append(
            {
                "Date de valorisation": valuation_date,
                "Valorisation": valuation_amount,
                "TRI net": compute_tri_at_valuation(movements, valuation_date, valuation_amount, "amount_net"),
                "TRI brut": compute_tri_at_valuation(movements, valuation_date, valuation_amount, "amount_gross"),
                "Date export": row.get("Date export", pd.NaT),
            }
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    result["Date export"] = pd.to_datetime(result["Date export"], errors="coerce")
    return result.sort_values("Date de valorisation").reset_index(drop=True)


def build_portfolio_tri_history(
    matched_map: dict[str, dict[str, object]],
    df_contrat_agg: pd.DataFrame,
) -> pd.DataFrame:
    if not matched_map or df_contrat_agg.empty:
        return pd.DataFrame()

    history_rows: list[pd.DataFrame] = []
    for contract_number, analysis in matched_map.items():
        contract_history = df_contrat_agg[df_contrat_agg["N° de contrat"].astype(str) == str(contract_number)].copy()
        tri_history = build_contract_tri_history(analysis, contract_history)
        if tri_history.empty:
            continue
        tri_history["N° de contrat"] = contract_number
        tri_history["Titulaire(s)"] = analysis.get("subscriber_name")
        tri_history["Enveloppe"] = analysis.get("contract_type")
        history_rows.append(tri_history)

    if not history_rows:
        return pd.DataFrame()

    return pd.concat(history_rows, ignore_index=True)


def summarize_portfolio_tri_history(df_history: pd.DataFrame) -> pd.DataFrame:
    if df_history.empty:
        return pd.DataFrame()

    history = df_history.dropna(subset=["Date de valorisation", "TRI net", "Valorisation"]).copy()
    if history.empty:
        return pd.DataFrame()

    grouped_rows: list[dict[str, object]] = []
    for valuation_date, group in history.groupby("Date de valorisation"):
        valuation_weights = group["Valorisation"].clip(lower=0)
        weight_sum = valuation_weights.sum()
        weighted_tri_net = None
        weighted_tri_brut = None
        if weight_sum > 0:
            weighted_tri_net = float((group["TRI net"].fillna(0) * valuation_weights).sum() / weight_sum)
            if group["TRI brut"].notna().any():
                weighted_tri_brut = float((group["TRI brut"].fillna(0) * valuation_weights).sum() / weight_sum)

        grouped_rows.append(
            {
                "Date de valorisation": valuation_date,
                "TRI net median": group["TRI net"].median(),
                "TRI brut median": group["TRI brut"].median() if group["TRI brut"].notna().any() else None,
                "TRI net pondéré": weighted_tri_net,
                "TRI brut pondéré": weighted_tri_brut,
                "Valorisation totale": group["Valorisation"].sum(),
                "Contrats apparies": group["N° de contrat"].nunique(),
            }
        )

    return pd.DataFrame(grouped_rows).sort_values("Date de valorisation").reset_index(drop=True)