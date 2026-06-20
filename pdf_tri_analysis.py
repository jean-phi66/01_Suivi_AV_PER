from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re

import pandas as pd
import PyPDF2


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PDF_DIR = BASE_DIR / "00_Exports" / "04_Opérations"

DATE_PATTERN = re.compile(r"Situation de votre contrat au\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
NUMBER_PATTERN = r"([0-9\s]+,\d{2})"
CONTRACT_PATTERN = re.compile(r"N[°ºo]?\s+([A-Z0-9 ]+)\s+du\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
SUBSCRIBER_PATTERN = re.compile(
    r"Situation de votre contrat au \d{2}/\d{2}/\d{4}\s*(Madame|Monsieur|Mademoiselle|Mme|M\.|Mlle)\s+([A-ZÀ-ÖØ-Ý'\- ]+)",
    re.IGNORECASE,
)
TOTAL_PATTERN = re.compile(r"TOTAL\s*" + NUMBER_PATTERN)
GROSS_PAYMENTS_PATTERN = re.compile(r"Cumul des versements bruts\s*" + NUMBER_PATTERN)
GROSS_REDEMPTIONS_PATTERN = re.compile(r"Cumul des rachats bruts\s*" + NUMBER_PATTERN)
MOVEMENTS_SECTION_PATTERN = re.compile(
    r"LISTE DES MOUVEMENTS EFFECTUES SUR VOTRE CONTRAT.*?DATE LIBELLE DU MOUVEMENT MONTANT NET \(EN €\)(.*)",
    re.S,
)
MOVEMENT_LINE_PATTERN = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?[0-9\s]+,\d{2})$")


@dataclass
class ParsedContract:
    file_path: Path
    contract_number: str
    contract_label: str
    subscriber_name: str
    contract_type: str
    opening_date: pd.Timestamp | None
    valuation_date: pd.Timestamp
    valuation_amount: float
    gross_payments_total: float
    gross_redemptions_total: float
    movements: pd.DataFrame
    net_contributions_total: float
    gross_rebuilt_ratio: float
    assumption_note: str


def parse_french_amount(raw_value: str | None) -> float:
    if not raw_value:
        return 0.0
    cleaned = str(raw_value).replace("\xa0", " ").replace(" ", "").replace(",", ".")
    return float(cleaned)


def _extract_text(pdf_path: Path) -> str:
    reader = PyPDF2.PdfReader(str(pdf_path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_match(pattern: re.Pattern[str], text: str, group: int = 1, default: str = "") -> str:
    match = pattern.search(text)
    if not match:
        return default
    return match.group(group).strip()


def _parse_movements(text: str, valuation_date: pd.Timestamp) -> pd.DataFrame:
    section_match = MOVEMENTS_SECTION_PATTERN.search(text)
    if not section_match:
        return pd.DataFrame(columns=["date", "label", "amount_net", "movement_type", "include_in_irr"])

    rows: list[dict[str, object]] = []
    for raw_line in section_match.group(1).splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        match = MOVEMENT_LINE_PATTERN.match(line)
        if not match:
            continue

        movement_date = pd.to_datetime(match.group(1), dayfirst=True, errors="coerce")
        if pd.isna(movement_date) or movement_date > valuation_date:
            continue

        label = match.group(2).strip()
        amount_net = parse_french_amount(match.group(3))
        upper_label = label.upper()

        movement_type = "other"
        include_in_irr = False
        if "ARBITRAGE" in upper_label:
            movement_type = "arbitrage"
        elif "RACHAT" in upper_label:
            movement_type = "redemption"
            include_in_irr = True
        elif "VERSEMENT" in upper_label or "SOUSCRIPTION" in upper_label or "ADHESION" in upper_label:
            movement_type = "contribution"
            include_in_irr = True
        elif (
            ("PRELEV" in upper_label or "PRLV" in upper_label)
            and ("PROGRAM" in upper_label or "PROG" in upper_label)
            and amount_net > 0
        ):
            # Certains releves libellent les versements programmes comme des prelevements programmes.
            movement_type = "contribution"
            include_in_irr = True
        elif "FRAIS" in upper_label or "REVALORISATION" in upper_label or "PRELEV" in upper_label:
            movement_type = "ignored_fee"

        rows.append(
            {
                "date": movement_date.normalize(),
                "label": label,
                "amount_net": amount_net,
                "movement_type": movement_type,
                "include_in_irr": include_in_irr,
            }
        )

    if not rows:
        return pd.DataFrame(columns=["date", "label", "amount_net", "movement_type", "include_in_irr"])

    return pd.DataFrame(rows).sort_values(["date", "label"]).reset_index(drop=True)


def _detect_contract_type(contract_label: str, contract_number: str) -> str:
    label = (contract_label or "").upper()
    number = (contract_number or "").upper()

    if "RETRAITE" in label or " PER" in label or label.startswith("PER"):
        return "PER"
    if "AVENIR" in label or "ASSURANCE VIE" in label or "VIE" in label:
        return "AV"
    if number.startswith("B7"):
        return "PER"
    if number.startswith("9E"):
        return "AV"
    return "Inconnu"


def _extract_subscriber_name(text: str) -> str:
    match = SUBSCRIBER_PATTERN.search(text)
    if match:
        civilite = match.group(1).strip().title()
        nom = " ".join(match.group(2).split()).title()
        return f"{civilite} {nom}"

    # Fallback: civilite + nom dans les lignes d'en-tete (haut droite du releve)
    fallback = re.search(
        r"(Madame|Monsieur|Mademoiselle|Mme|M\.|Mlle)\s+([A-ZÀ-ÖØ-Ý'\- ]{2,})",
        text,
        re.IGNORECASE,
    )
    if fallback:
        civilite = fallback.group(1).strip().title()
        nom = " ".join(fallback.group(2).split()).title()
        return f"{civilite} {nom}"

    return "Souscripteur inconnu"


def _extract_contract_label(text: str, pdf_path: Path) -> str:
    prefix = text.split("N°", 1)[0]
    upper_prefix = prefix.upper()

    if "PERTINENCE RETRAITE" in upper_prefix:
        return "PERTINENCE RETRAITE"
    if "CRISTALLIANCE AVENIR" in upper_prefix:
        return "CRISTALLIANCE AVENIR"

    lines = [line.strip() for line in prefix.splitlines() if line.strip()]
    for line in lines:
        if "Réf::" in line or "Ref::" in line or "REF::" in line:
            candidate = line.split("::", 1)[-1].strip()
            if candidate:
                # Garder la partie finale souvent egale au nom du contrat.
                tokens = candidate.split()
                if len(tokens) >= 2:
                    return " ".join(tokens[-2:]).upper()
                return candidate.upper()

    return pdf_path.stem


def parse_contract_pdf(pdf_path: Path) -> ParsedContract:
    text = _extract_text(pdf_path)

    valuation_date_raw = _extract_match(DATE_PATTERN, text)
    if not valuation_date_raw:
        raise ValueError(f"Date de valorisation introuvable dans {pdf_path.name}")
    valuation_date = pd.to_datetime(valuation_date_raw, dayfirst=True)

    contract_match = CONTRACT_PATTERN.search(text)
    contract_number = contract_match.group(1).replace(" ", "") if contract_match else pdf_path.stem
    opening_date = pd.to_datetime(contract_match.group(2), dayfirst=True) if contract_match else None

    contract_label = _extract_contract_label(text, pdf_path)

    subscriber_name = _extract_subscriber_name(text)
    contract_type = _detect_contract_type(contract_label, contract_number)

    valuation_amount = parse_french_amount(_extract_match(TOTAL_PATTERN, text))
    gross_payments_total = parse_french_amount(_extract_match(GROSS_PAYMENTS_PATTERN, text))
    gross_redemptions_total = parse_french_amount(_extract_match(GROSS_REDEMPTIONS_PATTERN, text))

    movements = _parse_movements(text, valuation_date)
    net_contributions_total = movements.loc[movements["movement_type"] == "contribution", "amount_net"].sum()
    gross_rebuilt_ratio = gross_payments_total / net_contributions_total if net_contributions_total > 0 and gross_payments_total > 0 else 1.0
    assumption_note = ""

    if not movements.empty:
        movements = movements.copy()
        movements["amount_gross"] = movements["amount_net"]
        contribution_mask = movements["movement_type"] == "contribution"
        if contribution_mask.any() and gross_payments_total > 0 and net_contributions_total > 0:
            movements.loc[contribution_mask, "amount_gross"] = (
                movements.loc[contribution_mask, "amount_net"] * gross_rebuilt_ratio
            )
            if not math.isclose(gross_rebuilt_ratio, 1.0, rel_tol=1e-6, abs_tol=1e-6):
                assumption_note = (
                    "Les versements bruts sont reconstitues au prorata des versements nets car le releve ne detaille "
                    "pas les frais d'entree par operation."
                )
        redemption_mask = movements["movement_type"] == "redemption"
        if redemption_mask.any() and gross_redemptions_total > 0:
            net_redemptions_total = movements.loc[redemption_mask, "amount_net"].sum()
            if net_redemptions_total > 0:
                redemption_ratio = gross_redemptions_total / net_redemptions_total
                movements.loc[redemption_mask, "amount_gross"] = (
                    movements.loc[redemption_mask, "amount_net"] * redemption_ratio
                )
    else:
        movements["amount_gross"] = pd.Series(dtype=float)

    return ParsedContract(
        file_path=pdf_path,
        contract_number=contract_number,
        contract_label=contract_label,
        subscriber_name=subscriber_name,
        contract_type=contract_type,
        opening_date=opening_date,
        valuation_date=valuation_date.normalize(),
        valuation_amount=valuation_amount,
        gross_payments_total=gross_payments_total,
        gross_redemptions_total=gross_redemptions_total,
        movements=movements,
        net_contributions_total=net_contributions_total,
        gross_rebuilt_ratio=gross_rebuilt_ratio,
        assumption_note=assumption_note,
    )


def xirr(cashflows: list[tuple[pd.Timestamp, float]]) -> float | None:
    dated_cashflows = [(pd.Timestamp(flow_date), float(amount)) for flow_date, amount in cashflows if amount != 0]
    if len(dated_cashflows) < 2:
        return None

    amounts = [amount for _date, amount in dated_cashflows]
    if not any(amount < 0 for amount in amounts) or not any(amount > 0 for amount in amounts):
        return None

    base_date = min(flow_date for flow_date, _amount in dated_cashflows)

    def npv(rate: float) -> float:
        total = 0.0
        for flow_date, amount in dated_cashflows:
            years = (flow_date - base_date).days / 365.25
            total += amount / ((1.0 + rate) ** years)
        return total

    low = -0.9999
    high = 0.10
    npv_low = npv(low)
    npv_high = npv(high)

    for _ in range(60):
        if npv_low == 0:
            return low
        if npv_high == 0:
            return high
        if npv_low * npv_high < 0:
            break
        high = high * 2 + 0.10
        if high > 1_000:
            return None
        npv_high = npv(high)
    else:
        return None

    for _ in range(200):
        mid = (low + high) / 2
        npv_mid = npv(mid)
        if abs(npv_mid) < 1e-8:
            return mid
        if npv_low * npv_mid < 0:
            high = mid
            npv_high = npv_mid
        else:
            low = mid
            npv_low = npv_mid

    return (low + high) / 2


def build_cashflows(contract: ParsedContract, amount_column: str) -> list[tuple[pd.Timestamp, float]]:
    cashflows: list[tuple[pd.Timestamp, float]] = []
    if not contract.movements.empty:
        for row in contract.movements.itertuples(index=False):
            if row.movement_type == "contribution":
                cashflows.append((row.date, -float(getattr(row, amount_column))))
            elif row.movement_type == "redemption":
                cashflows.append((row.date, float(getattr(row, amount_column))))
    cashflows.append((contract.valuation_date, contract.valuation_amount))
    return cashflows


def build_cashflows_until(
    movements: pd.DataFrame,
    valuation_date: pd.Timestamp,
    valuation_amount: float,
    amount_column: str,
) -> list[tuple[pd.Timestamp, float]]:
    valuation_ts = pd.Timestamp(valuation_date).normalize()
    cashflows: list[tuple[pd.Timestamp, float]] = []

    if movements is not None and not movements.empty:
        filtered = movements.loc[movements["date"] <= valuation_ts]
        for row in filtered.itertuples(index=False):
            amount = float(getattr(row, amount_column, 0.0) or 0.0)
            if row.movement_type == "contribution":
                cashflows.append((pd.Timestamp(row.date).normalize(), -amount))
            elif row.movement_type == "redemption":
                cashflows.append((pd.Timestamp(row.date).normalize(), amount))

    cashflows.append((valuation_ts, float(valuation_amount)))
    return cashflows


def compute_tri_at_valuation(
    movements: pd.DataFrame,
    valuation_date: pd.Timestamp,
    valuation_amount: float,
    amount_column: str,
) -> float | None:
    return xirr(build_cashflows_until(movements, valuation_date, valuation_amount, amount_column))


def analyze_contract_pdf(pdf_path: Path) -> dict[str, object]:
    contract = parse_contract_pdf(pdf_path)
    tri_net = xirr(build_cashflows(contract, "amount_net"))
    tri_gross = xirr(build_cashflows(contract, "amount_gross"))

    arbitrages_count = 0
    versements_count = 0
    if not contract.movements.empty:
        arbitrages_count = int((contract.movements["movement_type"] == "arbitrage").sum())
        versements_count = int((contract.movements["movement_type"] == "contribution").sum())

    return {
        "file_name": contract.file_path.name,
        "file_path": str(contract.file_path),
        "contract_number": contract.contract_number,
        "contract_label": contract.contract_label,
        "subscriber_name": contract.subscriber_name,
        "contract_type": contract.contract_type,
        "opening_date": contract.opening_date,
        "valuation_date": contract.valuation_date,
        "valuation_amount": contract.valuation_amount,
        "gross_payments_total": contract.gross_payments_total,
        "net_payments_total": contract.net_contributions_total,
        "tri_net": tri_net,
        "tri_gross": tri_gross,
        "movements": contract.movements,
        "assumption_note": contract.assumption_note,
        "arbitrages_count": arbitrages_count,
        "versements_count": versements_count,
    }


def analyze_directory(pdf_dir: Path = DEFAULT_PDF_DIR) -> list[dict[str, object]]:
    if not pdf_dir.exists():
        return []

    analyses: list[dict[str, object]] = []
    for pdf_path in sorted(pdf_dir.glob("*.pdf")):
        try:
            analyses.append(analyze_contract_pdf(pdf_path))
        except Exception as exc:
            analyses.append(
                {
                    "file_name": pdf_path.name,
                    "file_path": str(pdf_path),
                    "error": str(exc),
                }
            )
    return analyses
