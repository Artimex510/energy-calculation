import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_FILE = Path("psv-data.json")

SOURCES = [
    "https://luce-gas.it/guida/mercato/andamento-prezzo/gas-psv",
    "https://selectra.net/energia/guide/mercato/psv",
]

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
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def strip_html(html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


def parse_psv_entries(text: str) -> dict:
    """
    Cerca coppie tipo 'Ottobre 2026 ... 0,445 €/Smc'
    e restituisce { '2026-10': 0.445 }.
    """
    pattern = re.compile(
        r"\b(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|"
        r"settembre|ottobre|novembre|dicembre)\s+(202[5-9])\b"
        r".{0,80}?(\d[.,]\d{2,4})\s*€\s*/?\s*smc",
        re.IGNORECASE,
    )

    found = {}
    for match in pattern.finditer(text):
        month_name = match.group(1).lower()
        year = match.group(2)
        raw_val = match.group(3).replace(",", ".")

        try:
            value = round(float(raw_val), 4)
        except ValueError:
            continue

        # Controllo di sicurezza: un PSV realistico in €/Smc sta tra 0.10 e 3.00
        if 0.10 <= value <= 3.00:
            key = f"{year}-{MONTH_MAP[month_name]}"
            if key not in found:
                found[key] = value

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
    extracted_any = False

    for url in SOURCES:
        try:
            html = fetch_html(url)
            clean_text = strip_html(html)
            entries = parse_psv_entries(clean_text)

            if entries:
                for ym, val in entries.items():
                    year, m_num = ym.split("-")
                    months[ym] = {
                        "label": f"{MONTH_LABELS[m_num]} {year}",
                        "psv": val,
                        "status": "provvisorio" if ym >= current_ym else "definitivo",
                    }
                data["source"] = url
                extracted_any = True
                print(f"Estratti {len(entries)} mesi da {url}")
                break
        except Exception as exc:
            print(f"Sorgente non raggiungibile ({url}): {exc}")

    # Ordina i mesi cronologicamente
    data["months"] = dict(sorted(months.items()))

    if extracted_any:
        data["updatedAt"] = today.strftime("%Y-%m-%d")
        DATA_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print("psv-data.json aggiornato correttamente.")
    else:
        print("Nessun nuovo dato estratto: psv-data.json lasciato invariato.")


if __name__ == "__main__":
    main()
