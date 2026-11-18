import glob
import io
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
from pypdf import PdfReader


# Merchant keyword dictionary tailored to BPER & Banca Popolare di Sondrio statements (Torino/Milano + Travel)
MERCHANT_RULES: List[Tuple[List[str], str, str]] = [
    (
        [
            "ESSELUNGA", "CONAD", "COOP", "CARREFOUR", "LIDL", "EUROSPIN", "MD SPA",
            "PAM ", "PENNY", "ALDI", "DESPAR", "IPER ", "TIGROS", "BENNET", "FAMILA",
            "SUPERMERCATO", "NATURAS", "TODIS", "IN'S MERCATO", "IN’S MERCATO", "CRAI",
            "MINI SUPERMA", "HOSSAIN", "CAROZZI FORMAGGI", "MERCATO'", "ALBERT HEIJN",
            "AH TO GO", "SPAR ", "CRF MKT",
        ],
        "Groceries & Supermarket",
        "Essential Pass",
    ),
    (
        [
            "PELLEGRINI", "MENSA", "EDENRED", "DAY RISTOSERVICE", "BUONI PASTO",
        ],
        "Dining Out, Bars & Aperitivo",
        "Essential Pass",
    ),
    (
        [
            "GLOVO", "DELIVEROO", "JUST EAT", "JUSTEAT", "UBER EATS", "UBEREATS",
            "POKE HOUSE", "MCDONALD", "MCD MILANO", "BURGER KING", "KFC", "OLD WILD WEST",
            "STARBUCKS", "DOMINO", "OLIMPICO PIZZA", "KEBAB",
        ],
        "Food Delivery (Glovo/Deliveroo/JustEat)",
        "Pending Review",
    ),
    (
        [
            "BAR ", "CAFFE", "COFFEE CAPP", "PASTICCERIA", "GELATERIA", "TABACCHI",
            "TABACCHERIA", "TABACC ", "RUBINO MARCELLO", "AUTOGRILL",
            "DISTRIBUTORE AUTOMATICO", "JFP SNC", "SMART SRL",
        ],
        "Coffee, Snacks & Tabacchi",
        "Pending Review",
    ),
    (
        [
            "RISTORANTE", "TRATTORIA", "OSTERIA", "PUB ", "DISTRICT PUB", "BIRRERIA",
            "BEER ROOM", "LA BUTTIGA", "SOL LEVANTE", "ENOTECA", "APERITIVO", "THEFORK",
            "EATALY", "ROSSOPOMODORO", "ROADHOUSE", "LA LOCOMOTIVA", "PIZZERIA", "SUSHI",
            "GIAPPONESE", "SKASSAPANZA", "SULTAN TURKISH", "CIN CIN", "SAPPORO-LAMEN",
            "NARCISSE PARIS", "CHAPEAU CHARLEROI", "FRITEAPAPA", "TWELVE", "BKNO SRL",
            "HHX SRL", "MANHATTNS BURGERS", "AI 4 ASSI", "SPICCHI DI MOLE", "WOK TO GO",
            "EXKI ", "MYSICILYFOOD", "WAFFLE FACTORY", "STREAT SRL", "FOCACCERIA",
            "LA TANA DEL LUPO", "QUEEN'S ROSE", "HIGHLANDER B.V",
        ],
        "Dining Out, Bars & Aperitivo",
        "Pending Review",
    ),
    (
        [
            "NETFLIX", "SPOTIFY", "DISNEY", "DAZN", "NOW TV", "APPLE.COM/BILL",
            "GOOGLE*GOOGLE ONE", "GOOGLE PLAY", "GOOGLE *", "YOUTUBE", "PRIME VIDEO",
            "NEGOZIO PRIME VIDEO", "AMAZON PRIME", "CHATGPT", "OPENAI", "CLAUDE",
            "PLAYSTATION", "STEAM", "XBOX", "NINTENDO", "NY TIMES", "NYTIM", "PATREON",
            "TWITCH", "MOBIMATTER",
        ],
        "Subscriptions & Digital Services",
        "Pending Review",
    ),
    (
        [
            "ENEL", "ENI PLENITUDE", "ENI SPA - ENI REGOLAMENT", "ENI SPA",
            "SDD-UTENZE", "A2A", "HERA", "IREN", "EDISON", "ACEA", "SORGENIA",
            "TIM ", "TELECOM ITALIA", "VODAFONE", "WINDTRE", "ILIAD", "FASTWEB",
            "SKY ", "AFFITTO", "DAVIDE MANCINI", "GIORGIO BARISONE", "CANONE LOCAZIONE",
            "CONDOMINIO", "MUTUO", "RATA MUTUO", "TARI", "ACQUA", "BOLLETTA", "PAGOPA",
            "CBILL", "F24", "LAUNDRY 2 DAY",
        ],
        "Rent / Mortgage & Utilities",
        "Essential Pass",
    ),
    (
        [
            "ENI STATION", "IP ", "Q8", "TAMOIL", "ESSO", "SHELL", "BENZINA", "DISTRIBUTORE",
            "TELEPASS", "UNIPOLMOVE", "AUTOSTRADE", "TRENITALIA", "ITALO", "ATM MILAN",
            "CLESS TICKET ATM", "ATAC", "GTT.TO.IT", "GTT ", "TAP & GO", "DUOMO CORDUSIO",
            "GARIBALDI M2", "LAMPUGNANO M1", "RATP PARIS", "APP TEC NAMUR", "UBER ", "FREENOW",
            "TAXI", "LIME", "BIRD", "DOTT ", "DOTT BIKE", "ENJOY", "SHARE NOW", "PARCHEGGIO",
            "EASYPARK", "FLIBCO", "STIB ", "STIBMIVB", "STIB/MIVB", "NS REIZIGERS",
            "OVPAY.NL", "NMBS ", "MILANO CENTRALE SELF", "TORINO P.S.SELF", "CHARLEROI AIRPORT",
        ],
        "Transport, Fuel & Transit",
        "Essential Pass",
    ),
    (
        [
            "FARMACIA", "PARAFARMACIA", "OSPEDALE", "TICKET SANITARIO", "DENTISTA",
            "MEDICO", "OTTICA", "SYNLAB", "CENTRO MEDICO", "SANTAGOSTINO",
        ],
        "Health, Pharmacy & Medical",
        "Essential Pass",
    ),
    (
        [
            "RYANAIR", "EASYJET", "WIZZ", "ITA AIRWAYS", "LUFTHANSA", "BOOKING.COM",
            "AIRBNB", "EXPEDIA", "HOTEL", "ALBERGO", "OSTELLO", "CONSULATE",
            "CHARLEROI BSCA",
        ],
        "Travel & Vacations",
        "Pending Review",
    ),
    (
        [
            "CINEMA", "UCI ITALIA", "UCI CINEMAS", "THE SPACE", "TICKETONE", "TICKETMASTER",
            "DICE.FM", "NAMELESS FESTIVAL", "MUSEES", "MUSEUM", "MUSEO", "IRSNB",
            "ASSOCIAZIONE ABBONAMEN", "BOSSCHE WINTER", "DISCOTECA", "CLUB", "PALESTRA",
            "MCFIT", "VIRGIN ACTIVE", "FITACTIVE", "CASSA AUTOMATICA MELEZ",
        ],
        "Entertainment, Nightlife & Hobbies",
        "Pending Review",
    ),
    (
        [
            "PAYPAL *PAGA IN 3 RATE", "PAGA IN 3 RATE", "PAYPAL EUROPE", "PAYPAL (EUROPE)",
            "PAYPAL *TEMU", "PAYPAL *AWESOMEBKS", "PAYPAL *1NCRIVELSIS", "PAYPAL *IRUNNING",
            "PAYPAL *", "KLARNA", "SCALAPAY", "TEMU", "SHEIN", "ALIEXPRESS", "EBAY",
            "VINTED", "SKINPORT", "AWESOMEBKS", "IRUNNING",
        ],
        "Online Shopping & PayPal",
        "Pending Review",
    ),
    (
        [
            "AMAZON", "AMZN", "ZALANDO", "ASOS", "ZARA", "H&M", "UNIQLO", "DECATHLON",
            "MEDIAWORLD", "UNIEURO", "APPLE STORE", "IKEA", "SEPHORA", "DOUGLAS",
            "FELTRINELLI", "MONDADORI", "TIGER STORE", "DHL", "OVS ", "PUMA OUTLET",
            "GIUNTI AL PUNTO", "FULL TREND", "JACK JONES", "JACK  JONES", "TWINSPORT",
            "ACTION 1387", "ROYAL SOUVENIRS", "TRN SHOP", "MAIOR SERVICE",
        ],
        "Shopping, Clothes & Amazon",
        "Pending Review",
    ),
    (
        [
            "SATISPAY", "REVOLUT", "WISE BRUXELLES", "WISE ", "BANCOMAT PAY", "BPLAY",
            "RICARICA CARTA", "CARTA PREPAGATA", "PRELIEVO", "ATM BPER",
            "VEENA CHATTERJEE", "CHATTERJEEVEEN", "BONIFICO ISTANTANEO",
            "VOSTRA DISPOSIZIONE", "DISPOSIZIONE BONIFICO",
        ],
        "Transfers & P2P (Satispay/Revolut/BancomatPay)",
        "Pending Review",
    ),
    (
        [
            "COMMISSIONI", "COMM. BON.", "IMPOSTA DI BOLLO", "RECUPERO IMPOSTA DI BOLLO",
            "CANONE MENSILE", "COMPETENZE", "SPESE TENUTA CONTO", "BPER BANCA",
        ],
        "Bank Fees, Taxes & Bollo",
        "Essential Pass",
    ),
    (
        [
            "STIPENDIO", "EMOLUMENTI", "CAPGEMINI", "ACCREDITOCOMPENSI", "CEDOLINO",
            "BONIFICO A VOSTRO FAVORE", "RIMBORSO COMMERCIALE", "RIMBORSO", "DIVIDEND",
            "STORNO SCRITTURA", "INTERESSI CREDITORI",
        ],
        "Income / Salary",
        "Income",
    ),
    (
        [
            "SOTTOSCRIZIONI FONDI", "SOTTOSCRIZIONE ETICA", "FONDI E SICAV",
            "DIRECTA", "DEGIRO", "FINECO", "TRADE REPUBLIC", "SCALABLE", "PAC ",
            "ETF", "INVESTIMENT", "CONTO DEPOSITO",
        ],
        "Savings & Investments",
        "Justified",
    ),
]


def parse_italian_number(val: object) -> Optional[float]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (int, float)):
        return float(val)

    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "-", ""):
        return None

    s = re.sub(r"[€$£\s\u00a0]", "", s)

    is_neg = False
    if s.startswith("(") and s.endswith(")"):
        is_neg = True
        s = s[1:-1]
    elif s.endswith("-"):
        is_neg = True
        s = s[:-1]
    elif s.startswith("-"):
        is_neg = True
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")

    try:
        num = float(s)
        return -num if is_neg else num
    except ValueError:
        return None


def parse_italian_date(val: object) -> Optional[str]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d")

    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "non contabilizzato"):
        return None

    s_short = s.split(" ")[0]
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s_short, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    try:
        dt = pd.to_datetime(s, dayfirst=True, errors="raise")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def clean_bper_merchant(description: str) -> str:
    """
    Extracts a clean, canonical counterparty/merchant name from BPER & Banca Popolare di Sondrio multi-line PDF & CSV descriptions.
    """
    desc = " ".join(str(description).replace("’", "'").split())
    up = desc.upper()

    # Check bank commissions first so they are not swallowed by underlying merchant keywords
    if "COMMISSIONI" in up and ("PAYPAL" in up or "SDD" in up):
        return "Commissione BPER (PayPal SDD)"
    if up.startswith(("COMMISSIONI", "COMM. BON.", "COMPETENZE - ONERI", "RECUPERO IMPOSTA DI BOLLO")):
        return "Commissione Bonifico BPER"

    # Fast canonical merchant normalization so variants group together cleanly
    if "DAVIDE MANCINI" in up:
        return "Affitto (Davide Mancini)"
    if "GIORGIO BARISONE" in up:
        if "RENT" in up or "AFFITTO" in up:
            return "Affitto (Giorgio Barisone)"
        return "Giorgio Barisone (Casa)"
    if "AFFITTO" in up:
        return "Affitto"
    if "CAPGEMINI" in up or "EMOLUMENTI" in up:
        return "Stipendio (Capgemini Italia)"
    if "SOTTOSCRIZIONE ETICA" in up or "SOTTOSCRIZIONI FONDI" in up:
        return "PAC Fondi Etica SGR"
    if "PELLEGRINI CM1726" in up or "PELLEGRINI" in up:
        return "Pellegrini Mensa"
    if "IN'S MERCATO" in up or "IN’S MERCATO" in up:
        return "In's Mercato"
    if "MERCATO'" in up:
        return "Mercatò Supermarket"
    if "BENNET" in up:
        return "Bennet"
    if "ALBERT HEIJN" in up or "AH TO GO" in up:
        return "Albert Heijn (NL)"
    if "GLOVO" in up:
        return "Glovo"
    if "DELIVEROO" in up:
        return "Deliveroo"
    if "CARTA PREPAGATA" in up or "RIC.PREP." in up:
        return "Ricarica Carta Prepagata"
    if "OVPAY.NL" in up or up.startswith("NLOV") or " NLOV" in up:
        return "OVpay Transit (NL)"
    if "NS REIZIGERS" in up:
        return "NS Dutch Railways"
    if "STIB " in up or "STIBMIVB" in up or "STIB/MIVB" in up:
        return "STIB/MIVB Brussels Transit"
    if "FLIBCO" in up:
        return "Flibco Airport Shuttle"
    if "MILANO CENTRALE SELF" in up or "TORINO P.S.SELF" in up:
        return "Trenitalia Ticket Machine"
    if "TAP & GO" in up:
        return "GTT Torino Transit"
    if "PAGA IN 3 RATE" in up:
        return "PayPal Paga in 3 Rate (BNPL)"
    if ("ADDEBITO SDD" in up or "ADDEBITI PREAUTORIZZATI SDD" in up) and "PAYPAL" in up:
        return "PayPal SDD"
    if ("ADDEBITO SDD" in up or "ADDEBITI PREAUTORIZZATI SDD" in up) and "SATISPAY" in up:
        return "Satispay Top-Up (SDD)"
    if "ENI SPA" in up or "ENI PLENITUDE" in up:
        return "Eni Plenitude (Gas & Luce)"
    if "REVOLUT" in up:
        if "SENT FROM REVOLUT" in up or "A FAVORE DI ARNAB MONDAL" in up or "ORD: ARNAB MONDAL" in up:
            return "Revolut (Inbound Transfer)"
        return "Revolut Top-Up / Transfer"
    if "WISE" in up:
        return "Wise Transfer"
    if "AMAZON PRIME" in up or "NEGOZIO PRIME VIDEO" in up or "PRIME VIDEO" in up:
        return "Amazon Prime"
    if "AMAZON" in up or "AMZN" in up:
        return "Amazon"
    if "PAYPAL *TEMU" in up or "TEMU" in up:
        return "PayPal (Temu)"
    if "PAYPAL *NY TIMES" in up or "NY TIMES" in up or "NYTIM" in up:
        return "New York Times (PayPal)"
    if "PAYPAL *TRENITALIA" in up or "TRENITALIA" in up:
        return "Trenitalia"
    if "PAYPAL *DOTT" in up or "DOTT BIKE" in up:
        return "Dott Mobility"
    if "PAYPAL *AWESOMEBKS" in up:
        return "PayPal (AwesomeBooks)"
    if "PAYPAL *IRUNNING" in up:
        return "PayPal (iRunning)"
    if "PAYPAL *1NCRIVELSIS" in up:
        return "PayPal (1ncrivelsis)"
    if "DECATHLON" in up:
        return "Decathlon"
    if "MEDIAWORLD" in up:
        return "MediaWorld"
    if "SKINPORT" in up:
        return "Skinport GmbH"
    if "VEENA CHATTERJEE" in up or "CHATTERJEEVEEN" in up:
        return "Bonifico (Veena Chatterjee)"
    if "CONSULATE GENERAL OF INDIA" in up:
        return "Consulate General of India"
    if "LA LOCOMOTIVA" in up:
        return "La Locomotiva"
    if "LA BUTTIGA" in up:
        return "La Buttiga Beer Room"
    if "RUBINO MARCELLO TABACC" in up:
        return "Tabaccheria Rubino Marcello"
    if "TABACCHERIA FILADELFIA" in up:
        return "Tabaccheria Filadelfia"
    if "TABACCHERIA BUTERA" in up:
        return "Tabaccheria Butera"
    if "GTT.TO.IT" in up:
        return "GTT Torino Transit"
    if "ATM MILAN" in up or "DUOMO CORDUSIO" in up or "GARIBALDI M2" in up or "LAMPUGNANO M1" in up:
        return "ATM Milano Transit"
    if "RATP PARIS" in up:
        return "RATP Paris Transit"
    if "GOOGLE PLAY" in up:
        return "Google Play"
    if "GOOGLE*GOOGLE ONE" in up:
        return "Google One"

    # Generic VOSTRA DISPOSIZIONE / SCT transfer recipient extraction ("Fv. Name ...")
    m_fv = re.search(r"\bFv\.\s*([A-Za-z][A-Za-z\s'\-]{2,30}?)(?:\s+(?:Rif\.|l'affitto|Rent|danni|Compleanno|moggio)|$)", desc, flags=re.IGNORECASE)
    if m_fv and ("VOSTRA DISPOSIZIONE" in up or "BONIFICO" in up):
        recip = " ".join(m_fv.group(1).split())
        return f"Bonifico ({recip})"[:42]

    # Generic PayPal *Merchant cleanup
    m_pp = re.search(r"PAYPAL\s*\*\s*([A-Za-z0-9._\-]+)", desc, flags=re.IGNORECASE)
    if m_pp:
        sub_m = m_pp.group(1).strip()
        return f"PayPal ({sub_m})"

    # 1. Older BPER / Popolare di Sondrio format: "... c/o: MERCHANT" or "... Carta n. **4521 MERCHANT NAME - CITY"
    m_co = re.search(r"\bc/o:\s*(.+?)$", desc, flags=re.IGNORECASE)
    if m_co:
        cleaned = m_co.group(1).strip(" -:/")
        if len(cleaned) >= 2:
            return cleaned[:42]

    m_card = re.search(r"Carta\s+[nN]\.\s*\*\*\d+\s+(.+?)(?:\s+-\s+[A-Za-z]{2,}.*|\s*$)", desc)
    if m_card:
        cleaned = m_card.group(1).strip(" -:/")
        if len(cleaned) >= 2:
            return cleaned[:42]

    # 2. Newer BPER format: "PAGAMENTO SU CIRCUITO INTERNAZIONALE <MERCHANT> Operazione carta ****7247..."
    m_int = re.search(
        r"PAGAMENTO SU CIRCUITO INTERNAZIONALE\s+(.+?)(?:\s+Operazione carta|\s+del\s+\d{2}\.\d{2}\.\d{4}|$)",
        desc,
        flags=re.IGNORECASE,
    )
    if m_int:
        cleaned = m_int.group(1).strip(" -:/")
        cleaned_short = re.sub(
            r"\s+(?:TORINO|MILANO|GRUGLIASCO|LUXEMBOURG|DUBLIN|BRUXELLES)\s+(?:ITA|LUX|IRL|BEL)\b.*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        res = cleaned_short if len(cleaned_short) >= 3 else cleaned
        return res[:42]

    return desc[:42]


def infer_default_recurrence(description: str, merchant: str, category: str, amount: float) -> str:
    """
    Infers whether a transaction is 'Recurring' (monthly bills, rent, utilities, subscriptions,
    PAC fund investments, Wise >€300 monthly investment transfers, BNPL installments, regular mensa/groceries/tabacchi/transit) or 'One-Time'.
    """
    if amount > 0:
        up = str(description).upper()
        if any(k in up for k in ("STIPENDIO", "EMOLUMENTI", "CAPGEMINI", "SALARY")):
            return "Recurring"
        return "One-Time"

    up_desc = str(description).upper()
    up_merch = str(merchant).upper()

    if "WISE" in up_merch and abs(float(amount)) > 300.0:
        return "Recurring"

    # Explicit One-Time repairs, travel groceries, or laundry
    if any(k in up_desc for k in ("DANNI FINESTRA", "LAUNDRY 2 DAY", "ALBERT HEIJN", "AH TO GO", "SPAR ", "CRF MKT")):
        return "One-Time"

    # Known recurring commitments, subscriptions, utilities, PAC, mensa, groceries
    recurring_merchants = (
        "AFFITTO (DAVIDE MANCINI)",
        "AFFITTO (GIORGIO BARISONE)",
        "ENI PLENITUDE (GAS & LUCE)",
        "PAC FONDI ETICA SGR",
        "AMAZON PRIME",
        "NEW YORK TIMES (PAYPAL)",
        "GOOGLE ONE",
        "PELLEGRINI MENSA",
        "IN'S MERCATO",
        "MERCATÒ SUPERMARKET",
        "BENNET",
        "PAYPAL PAGA IN 3 RATE (BNPL)",
        "PAYPAL SDD",
        "COMMISSIONE BPER (PAYPAL SDD)",
        "COMMISSIONE BONIFICO BPER",
        "GTT TORINO TRANSIT",
        "TABACCHERIA FILADELFIA",
        "TABACCHERIA BUTERA",
        "TABACCHERIA RUBINO MARCELLO",
    )
    if any(rm in up_merch for rm in recurring_merchants):
        return "Recurring"

    if category in (
        "Rent / Mortgage & Utilities",
        "Subscriptions & Digital Services",
        "Groceries & Supermarket",
        "Bank Fees, Taxes & Bollo",
        "Savings & Investments",
    ):
        return "Recurring"

    if any(k in up_desc for k in ("TIPO:CORE-RCUR", "SOTTOSCRIZIONE ETICA", "SOTTOSCRIZIONI FONDI", "CANONE", "ABBONAMENTO")):
        return "Recurring"

    return "One-Time"


def classify_bper_transaction(description: str, amount: float, suspect_threshold: float = 15.0) -> Tuple[str, str]:
    upper_desc = str(description).replace("’", "'").upper()

    if amount > 0:
        for keywords, cat, verdict in MERCHANT_RULES:
            if any(k in upper_desc for k in keywords):
                if cat == "Income / Salary":
                    return cat, "Income"
        return "Income / Salary", "Income"

    # Check bank fees first so "COMMISSIONI ... Davide Mancini" or "COMMISSIONI ... PayPal" doesn't get misclassified
    if upper_desc.startswith(("COMMISSIONI", "COMM. BON.", "COMPETENZE - ONERI", "RECUPERO IMPOSTA DI BOLLO")):
        return "Bank Fees, Taxes & Bollo", "Essential Pass"

    # Prevent "Carta n. **4521 ... GARIBALDI M2" from matching "PAM " or "IP " accidentally
    if any(k in upper_desc for k in ("GARIBALDI M2", "LAMPUGNANO M1", "DUOMO CORDUSIO", "ATM MILAN", "GTT.TO.IT", "TAP & GO", "RATP PARIS", "OVPAY.NL", "NS REIZIGERS", "STIB ", "STIBMIVB", "STIB/MIVB", "FLIBCO")):
        return "Transport, Fuel & Transit", "Essential Pass"

    # One-time house repair to landlord shouldn't auto-pass as Essential Pass
    if "DANNI FINESTRA" in upper_desc:
        return "Rent / Mortgage & Utilities", "Pending Review"

    # Monthly €100 stock/fund investments ("SOTTOSCRIZIONI FONDI E SICAV")
    if any(k in upper_desc for k in ("SOTTOSCRIZIONI FONDI", "SOTTOSCRIZIONE ETICA", "FONDI E SICAV")):
        return "Savings & Investments", "Justified"

    # Wise transfers > €300 include the 12,000 INR investment allocation
    if "WISE" in upper_desc and abs(float(amount)) > 300.0:
        return "Transfers & P2P (Satispay/Revolut/BancomatPay)", "Justified"

    for keywords, cat, verdict in MERCHANT_RULES:
        if any(k in upper_desc for k in keywords):
            if verdict == "Essential Pass":
                return cat, "Essential Pass"
            if verdict == "Justified":
                return cat, "Justified"
            return cat, "Pending Review"

    if abs(amount) >= suspect_threshold:
        return "Other / Uncategorized", "Pending Review"
    return "Other / Uncategorized", "Pending Review"


# --- BPER & BANCA POPOLARE DI SONDRIO PDF PARSER ---

_PDF_TX_LINE_RE = re.compile(
    r"^\s*(\d{1,2}/\d{2}/\d{2,4})\s+([DA])\s+([\d.,]+)\s+(\d{1,2}/\d{2}/\d{2,4})\s+(.*)$"
)

_SONDRIO_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_SONDRIO_NUM_RE = re.compile(r"^[\d.]+,\d{2}$")

_PDF_IGNORE_LINES = (
    "Mod. 05.13.0011",
    "OPERAZIONI SU SERVIZI DI PAGAMENTO",
    "RIEPILOGO MENSILE AL",
    "DEL CONTO CORRENTE",
    "PRESSO ",
    "FOGLIO N.",
    "ABI: 05387",
    "IBAN: COORDINATE",
    "PAESE CIN COORDINATE",
    "CIN ABI CAB CONTO",
    "IT 53 I 05387",
    "DATA SEGNO (D/A)",
    "05387-2076",
    "MONDAL ARNAB",
    "VIA PASQUALE PAOLI",
    "10134 TORINO TO",
    "BPER Banca",
)


def _extract_sondrio_hc42_records(reader: PdfReader) -> List[Dict[str, object]]:
    """
    Parses Banca Popolare di Sondrio / BPER Group 'ESTRATTO CONTO' PDFs (e.g. HC42_31_01_2026.pdf)
    using PDF text coordinate positioning for Data, Valuta, Movimenti Dare, Movimenti Avere, and Descrizione operazione.
    """
    records: List[Dict[str, object]] = []
    for page in reader.pages:
        page_items: List[Tuple[float, float, str]] = []

        def _visitor(text: str, cm: object, tm: List[float], font_dict: object, font_size: float) -> None:
            t = text.strip()
            if t:
                page_items.append((float(tm[4]), float(tm[5]), t))

        page.extract_text(visitor_text=_visitor)
        header_y = next((y for _, y, t in page_items if t == "Descrizione operazione"), None)
        if header_y is None:
            continue

        rows_by_y: List[Dict[str, object]] = []
        for x, y, t in page_items:
            if y >= header_y - 2.0 or y < 40.0:
                continue
            placed = False
            for bucket in rows_by_y:
                if abs(float(bucket["y"]) - y) <= 2.2:
                    bucket["items"].append((x, t))
                    placed = True
                    break
            if not placed:
                rows_by_y.append({"y": y, "items": [(x, t)]})

        rows_by_y.sort(key=lambda b: float(b["y"]), reverse=True)
        cur_tx: Optional[Dict[str, object]] = None

        for bucket in rows_by_y:
            items_sorted = sorted(bucket["items"], key=lambda it: it[0])
            texts = [t for _, t in items_sorted]
            joined = " ".join(texts)

            if any(
                k in joined
                for k in (
                    "Saldo iniziale",
                    "Saldo finale",
                    "Totale movimenti",
                    "IMPOSTA DI BOLLO ASSOLTA",
                    "Si rammenta che",
                    "BANCA POPOLARE DI SONDRIO",
                )
            ):
                if cur_tx is not None:
                    records.append(cur_tx)
                    cur_tx = None
                if "Saldo finale" in joined or "Totale movimenti" in joined:
                    break
                continue

            d_op: Optional[str] = None
            d_val: Optional[str] = None
            dare: Optional[float] = None
            avere: Optional[float] = None
            desc_parts: List[str] = []

            for x, t in items_sorted:
                if x < 50.0 and _SONDRIO_DATE_RE.match(t):
                    d_op = t
                elif 50.0 <= x < 120.0 and _SONDRIO_DATE_RE.match(t):
                    d_val = t
                elif 120.0 <= x < 225.0 and _SONDRIO_NUM_RE.match(t):
                    dare = parse_italian_number(t)
                elif 225.0 <= x < 325.0 and _SONDRIO_NUM_RE.match(t):
                    avere = parse_italian_number(t)
                elif x >= 325.0:
                    desc_parts.append(t)

            if d_op and d_val and (dare is not None or avere is not None):
                if cur_tx is not None:
                    records.append(cur_tx)
                signed_amt = -abs(dare) if dare is not None else abs(avere or 0.0)
                cur_tx = {
                    "tx_date": parse_italian_date(d_op),
                    "valuta_date": parse_italian_date(d_val),
                    "amount": round(signed_amt, 2),
                    "desc_lines": desc_parts,
                }
            elif cur_tx is not None and desc_parts:
                cur_tx["desc_lines"].extend(desc_parts)

        if cur_tx is not None:
            records.append(cur_tx)

    return records


def parse_bper_pdf_bytes(raw_bytes: bytes, filename: str = "statement.pdf", suspect_threshold: float = 15.0) -> Tuple[pd.DataFrame, str]:
    """
    Parses BPER Banca PDF monthly statements ('OPERAZIONI SU SERVIZI DI PAGAMENTO - RIEPILOGO MENSILE', e.g. LQ10_*.pdf)
    as well as Banca Popolare di Sondrio / BPER Group statements ('ESTRATTO CONTO', e.g. HC42_*.pdf).
    """
    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
    except Exception as e:
        return pd.DataFrame(), f"PDF read error in {filename}: {e}"

    records: List[Dict[str, object]] = []
    current_tx: Optional[Dict[str, object]] = None

    for page in reader.pages:
        text = page.extract_text() or ""
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line == "A":
                continue
            if any(line.startswith(prefix) for prefix in _PDF_IGNORE_LINES):
                continue
            if "DATA" in line and "SEGNO (D/A)" in line and "IMPORTO" in line:
                continue

            m = _PDF_TX_LINE_RE.match(raw_line)
            if m:
                if current_tx is not None:
                    records.append(current_tx)
                d_op, segno, imp_str, d_val, desc_start = m.groups()
                amt_raw = parse_italian_number(imp_str) or 0.0
                signed_amt = -abs(amt_raw) if segno.upper() == "D" else abs(amt_raw)
                current_tx = {
                    "tx_date": parse_italian_date(d_op),
                    "valuta_date": parse_italian_date(d_val),
                    "amount": round(signed_amt, 2),
                    "desc_lines": [desc_start.strip()],
                }
            else:
                # Continuation line of the active transaction description
                if current_tx is not None:
                    current_tx["desc_lines"].append(line)

    if current_tx is not None:
        records.append(current_tx)

    # Fallback to Banca Popolare di Sondrio (HC42 Estratto Conto) coordinate table layout
    if not records:
        records = _extract_sondrio_hc42_records(reader)

    if not records:
        return pd.DataFrame(), f"No bank transactions found in {filename}."

    parsed_rows = []
    for rec in records:
        full_desc = " ".join(rec["desc_lines"])
        amt = float(rec["amount"])
        t_date = str(rec["tx_date"])
        v_date = str(rec["valuta_date"] or t_date)
        merchant = clean_bper_merchant(full_desc)
        cat, verdict = classify_bper_transaction(full_desc, amt, suspect_threshold=suspect_threshold)
        recurrence = infer_default_recurrence(full_desc, merchant, cat, amt)

        parsed_rows.append(
            {
                "Include": True,
                "Date": t_date,
                "Valuta": v_date,
                "Merchant": merchant,
                "Description": full_desc,
                "Amount (€)": amt,
                "Category": cat,
                "Recurrence": recurrence,
                "Status / Verdict": verdict,
            }
        )

    df = pd.DataFrame(parsed_rows)
    return df, f"Parsed {len(df)} transactions from {filename}."


def scan_workspace_bper_pdfs(directory: str) -> List[str]:
    """Finds all PDF files in the workspace folder (e.g., LQ10_*.pdf)."""
    pdf_paths = sorted(glob.glob(os.path.join(directory, "*.pdf")))
    return pdf_paths


def parse_multiple_bper_pdfs(file_paths: List[str], suspect_threshold: float = 15.0) -> Tuple[pd.DataFrame, str]:
    frames = []
    for path in file_paths:
        try:
            with open(path, "rb") as f:
                df, _ = parse_bper_pdf_bytes(
                    f.read(),
                    filename=os.path.basename(path),
                    suspect_threshold=suspect_threshold,
                )
                if not df.empty:
                    frames.append(df)
        except Exception:
            continue

    if not frames:
        return pd.DataFrame(), "No transactions could be extracted from the workspace PDF files."

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values("Date", ascending=False).reset_index(drop=True)
    return combined, f"Extracted {len(combined)} transactions across {len(frames)} BPER PDF statements."


def _find_header_row(raw_df: pd.DataFrame) -> int:
    header_keywords = {
        "data", "data contabile", "data operazione", "data valuta",
        "descrizione", "causale", "dettagli", "operazione",
        "importo", "entrate", "uscite", "dare", "avere", "ammontare",
    }
    best_row = 0
    best_hits = 0

    max_scan = min(35, len(raw_df))
    for idx in range(max_scan):
        row_vals = [str(v).strip().lower() for v in raw_df.iloc[idx].values if pd.notna(v)]
        hits = sum(1 for v in row_vals if any(hk in v for hk in header_keywords))
        if hits > best_hits and hits >= 2:
            best_hits = hits
            best_row = idx

    return best_row


def parse_bper_file(uploaded_file, suspect_threshold: float = 15.0) -> Tuple[pd.DataFrame, str]:
    """
    Accepts a `.pdf`, `.xlsx`, `.xls`, or `.csv` file from BPER Banca.
    """
    filename = getattr(uploaded_file, "name", "bper_export.pdf")
    raw_bytes = uploaded_file.read()
    uploaded_file.seek(0)

    if filename.lower().endswith(".pdf"):
        return parse_bper_pdf_bytes(raw_bytes, filename=filename, suspect_threshold=suspect_threshold)

    raw_df = None
    if filename.lower().endswith((".xlsx", ".xls")):
        try:
            raw_df = pd.read_excel(io.BytesIO(raw_bytes), header=None)
        except Exception as e:
            return pd.DataFrame(), f"Excel read error: {e}"
    else:
        for enc in ("utf-8-sig", "latin-1", "cp1252", "utf-8"):
            try:
                text = raw_bytes.decode(enc)
                lines = [line for line in text.splitlines() if line.strip()]
                sep = ";" if sum(line.count(";") for line in lines[:25]) >= sum(line.count(",") for line in lines[:25]) else ","
                split_rows = [line.split(sep) for line in lines]
                max_cols = max((len(r) for r in split_rows), default=0)
                if max_cols >= 3:
                    padded_rows = [r + [None] * (max_cols - len(r)) for r in split_rows]
                    raw_df = pd.DataFrame(padded_rows)
                    break
            except Exception:
                continue

    if raw_df is None or raw_df.empty:
        return pd.DataFrame(), "Could not parse file. Upload a valid BPER PDF, Excel, or CSV statement."

    header_idx = _find_header_row(raw_df)
    headers = [str(c).strip() for c in raw_df.iloc[header_idx].values]
    df = raw_df.iloc[header_idx + 1 :].copy()
    df.columns = headers
    df = df.dropna(how="all").reset_index(drop=True)

    col_map: Dict[str, Optional[str]] = {
        "tx_date": None,
        "valuta_date": None,
        "description": None,
        "causal": None,
        "amount": None,
        "debit": None,
        "credit": None,
    }

    for col in df.columns:
        cl = col.lower()
        if col_map["tx_date"] is None and any(k in cl for k in ("data contabile", "data operazione", "data reg", "data mov", "data")):
            if "valuta" not in cl:
                col_map["tx_date"] = col
        elif col_map["valuta_date"] is None and "valuta" in cl:
            col_map["valuta_date"] = col
        elif col_map["description"] is None and any(k in cl for k in ("descrizione", "dettagli", "beneficiario", "esercente", "operazione", "movimento")):
            col_map["description"] = col
        elif col_map["causal"] is None and any(k in cl for k in ("causale", "tipo", "voce")):
            col_map["causal"] = col
        elif col_map["amount"] is None and any(k in cl for k in ("importo", "ammontare", "valore", "saldo mov", "euro")):
            col_map["amount"] = col
        elif col_map["debit"] is None and any(k in cl for k in ("uscite", "dare", "addebito", "addebiti")):
            col_map["debit"] = col
        elif col_map["credit"] is None and any(k in cl for k in ("entrate", "avere", "accredito", "accrediti")):
            col_map["credit"] = col

    if col_map["tx_date"] is None:
        for col in df.columns:
            if "data" in col.lower() or "date" in col.lower():
                col_map["tx_date"] = col
                break

    if col_map["tx_date"] is None or (col_map["amount"] is None and col_map["debit"] is None):
        return pd.DataFrame(), f"Could not detect Date and Amount columns. Headers found: {list(df.columns)}"

    parsed_rows = []
    for _, row in df.iterrows():
        t_date = parse_italian_date(row.get(col_map["tx_date"]))
        if not t_date:
            continue

        v_date = parse_italian_date(row.get(col_map["valuta_date"])) if col_map["valuta_date"] else t_date

        desc_parts = []
        if col_map["causal"] and pd.notna(row.get(col_map["causal"])):
            desc_parts.append(str(row.get(col_map["causal"])).strip())
        if col_map["description"] and pd.notna(row.get(col_map["description"])):
            desc_parts.append(str(row.get(col_map["description"])).strip())

        full_desc = " - ".join([p for p in desc_parts if p and p.lower() != "nan"]) or "Movimento BPER"

        amt = None
        if col_map["amount"] is not None:
            amt = parse_italian_number(row.get(col_map["amount"]))
        if amt is None and (col_map["debit"] is not None or col_map["credit"] is not None):
            deb = parse_italian_number(row.get(col_map["debit"])) if col_map["debit"] else 0.0
            cred = parse_italian_number(row.get(col_map["credit"])) if col_map["credit"] else 0.0
            deb = deb or 0.0
            cred = cred or 0.0
            if deb != 0 or cred != 0:
                amt = abs(cred) - abs(deb)

        if amt is None or amt == 0.0:
            continue

        merchant = clean_bper_merchant(full_desc)
        cat, verdict = classify_bper_transaction(full_desc, amt, suspect_threshold=suspect_threshold)
        recurrence = infer_default_recurrence(full_desc, merchant, cat, amt)

        parsed_rows.append(
            {
                "Include": True,
                "Date": t_date,
                "Valuta": v_date or t_date,
                "Merchant": merchant,
                "Description": full_desc,
                "Amount (€)": round(amt, 2),
                "Category": cat,
                "Recurrence": recurrence,
                "Status / Verdict": verdict,
            }
        )

    result_df = pd.DataFrame(parsed_rows)
    if result_df.empty:
        return pd.DataFrame(), "No valid transactions found."

    return result_df, f"Parsed {len(result_df)} transactions from {filename}."
