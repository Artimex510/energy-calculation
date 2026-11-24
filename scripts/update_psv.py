import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_FILE = Path("psv-data.json")

# Powergas: mesi già chiusi con 6 decimali ufficiali (PCS 38,52 MJ/Smc)
CLOSED_MONTHS_URL = "https://www.powergas.it/indici/psv/"
# Luce-Gas.it: media mensile provvisoria del mese in corso aggiornata ogni giorno
LIVE_MONTH_URL = "https://luce-gas.it/guida/mercato/andamento-prezzo/gas-metano"

MONTH_MAP = {
    "gennaio": "01",
    "febbraio": "02",
    "marzo": "03",
    "aprile": "04",
    "maggio": "05",
    "giugno": "06",
    "luglio": "07",
    "agosto": "08",
    "settembre": "09",
    "ottobre": "10",
    "novembre": "11",
    "dicembre": "12",
}

MONTH_LABELS = {
    "01": "Gennaio",
    "02": "Febbraio",
    "03": "Marzo",
    "04": "Aprile",
    "05": "Maggio",
    "06": "Giugno",
    "07": "Luglio",
    "08": "Agosto",
    "09": "Settembre",
    "10": "Ottobre",
    "11": "Novembre",
    "12": "Dicembre",
}

MONTH_REGEX = (
    r"\b(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|"
    r"settembre|ottobre|novembre|dicembre)\s+(202[6-9])\b"
)


def fetch_html(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "it-IT,it;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def strip_html(html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


def parse_psv_entries(html: str) -> dict:
    found = {}

    # 1) Cerca nelle righe di tabella <tr> (es. "Ottobre 2026 | 0,945436" o "PSV novembre 2026 | 0,955")
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        clean_row = strip_html(row)
        m_date = re.search(MONTH_REGEX, clean_row, flags=re.I)
        if not m_date:
            continue

        after_date = clean_row[m_date.end():]
        m_val = re.search(r"\b(\d[.,]\d{2,6})\b", after_date)
        if not m_val:
            continue

        try:
            value = round(float(m_val.group(1).replace(",", ".")), 6)
        except ValueError:
            continue

        if 0.10 <= value <= 3.00:
            key = f"{m_date.group(2)}-{MONTH_MAP[m_date.group(1).lower()]}"
            found.setdefault(key, value)

    if found:
        return found

    # 2) Fallback su testo libero con unità esplicita "€/Smc"
    clean_text = strip_html(html)
    pattern = re.compile(
        MONTH_REGEX + r".{0,80}?(\d[.,]\d{2,6})\s*€\s*/?\s*smc",
        re.IGNORECASE,
    )
    for match in pattern.finditer(clean_text):
        try:
            value = round(float(match.group(3).replace(",", ".")), 6)
        except ValueError:
            continue

        if 0.10 <= value <= 3.00:
            key = f"{match.group(2)}-{MONTH_MAP[match.group(1).lower()]}"
            found.setdefault(key, value)

    return found


def main():
    if DATA_FILE.exists():
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    else:
        data = {
            "updatedAt": "",
            "source": "Mercato PSV Italia",
            "unit": "EUR/Smc",
            "months": {},
        }

    months = data.get("months", {})
    today = datetime.now(timezone.utc)
    current_ym = today.strftime("%Y-%m")
    sources_ok = []

    # 1) Leggi i mesi ufficialmente chiusi da Powergas (6 decimali)
    try:
        html_closed = fetch_html(CLOSED_MONTHS_URL)
        closed_entries = parse_psv_entries(html_closed)
        print(f"[Powergas] Estratti {len(closed_entries)} mesi")
        if closed_entries:
            sources_ok.append(CLOSED_MONTHS_URL)
            for ym, val in closed_entries.items():
                existing = months.get(ym)
                if existing and existing.get("status") == "definitivo":
                    continue
                year, m_num = ym.split("-")
                is_provvisorio = ym >= current_ym
                label = f"{MONTH_LABELS[m_num]} {year}"
                if is_provvisorio:
                    label += " (provvisorio)"
                months[ym] = {
                    "label": label,
                    "psv": val,
                    "status": "provvisorio" if is_provvisorio else "definitivo",
                }
    except Exception as exc:
        print(f"[Powergas] Errore: {exc}")

    # 2) Leggi SEMPRE anche Luce-Gas.it per aggiornare il mese in corso (provvisorio)
    try:
        html_live = fetch_html(LIVE_MONTH_URL)
        live_entries = parse_psv_entries(html_live)
        print(f"[Luce-Gas.it] Estratti {len(live_entries)} mesi")
        if live_entries:
            sources_ok.append(LIVE_MONTH_URL)
            for ym, val in live_entries.items():
                existing = months.get(ym)
                # Non sovrascrive mai i mesi già consolidati come definitivi
                if existing and existing.get("status") == "definitivo":
                    continue
                # Aggiorna il mese in corso (o eventuali mesi non ancora chiusi su Powergas)
                if ym >= current_ym or not existing:
                    year, m_num = ym.split("-")
                    months[ym] = {
                        "label": f"{MONTH_LABELS[m_num]} {year} (provvisorio)",
                        "psv": val,
                        "status": "provvisorio",
                    }
    except Exception as exc:
        print(f"[Luce-Gas.it] Errore: {exc}")

    data["months"] = dict(sorted(months.items()))

    if sources_ok:
        data["source"] = " + ".join(sources_ok)
        data["updatedAt"] = today.strftime("%Y-%m-%d")
        DATA_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"psv-data.json salvato con updatedAt={data['updatedAt']}")
    else:
        print("Nessuna sorgente raggiungibile: psv-data.json lasciato invariato.")


if __name__ == "__main__":
    main()
