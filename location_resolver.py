from config import LOCATION_MAP, DEFAULT_LOCATION_ID, DEFAULT_LOCATION_NAME
import hashlib as _hashlib

LOCATION_TE_MAP = {
    # Andhra Pradesh
    "kurnool": "కర్నూలు",
    "ananthapur": "అనంతపురం",
    "ananthapuramu": "అనంతపురము",
    "kadapa": "కడప",
    "cuddapah": "కడప",
    "chittoor": "చిత్తూరు",
    "tirupati": "తిరుపతి",
    "nellore": "నెల్లూరు",
    "ongole": "ఒంగోలు",
    "guntur": "గుంటూరు",
    "vijayawada": "విజయవాడ",
    "machilipatnam": "మచిలీపట్నం",
    "eluru": "ఏలూరు",
    "bhimavaram": "భీమవరం",
    "rajahmundry": "రాజమండ్రి",
    "kakinada": "కాకినాడ",
    "amalapuram": "అమలాపురం",
    "vizianagaram": "విజయనగరం",
    "visakhapatnam": "విశాఖపట్నం",
    "vizag": "విశాఖపట్నం",
    "srikakulam": "శ్రీకాకుళం",
    "tenali": "తెనాలి",
    "narasaraopet": "నరసరావుపేట",
    "tadepalligudem": "తాడేపల్లిగూడెం",

    # Telangana
    "hyderabad": "హైదరాబాద్",
    "secunderabad": "సికింద్రాబాద్",
    "warangal": "వరంగల్",
    "hanamkonda": "హనుమకొండ",
    "karimnagar": "కరీంనగర్",
    "khammam": "ఖమ్మం",
    "nizamabad": "నిజామాబాద్",
    "adilabad": "ఆదిలాబాద్",
    "mahbubnagar": "మహబూబ్‌నగర్",
    "medak": "మెదక్",
    "siddipet": "సిద్దిపేట",
    "jagtial": "జగిత్యాల",
    "ramagundam": "రామగుండం",

    # Tamil Nadu
    "chennai": "చెన్నై",
    "coimbatore": "కోయంబత్తూరు",
    "madurai": "మదురై",
    "tiruchirappalli": "తిరుచిరాపల్లి",
    "trichy": "తిరుచిరాపల్లి",
    "salem": "సేలం",
    "erode": "ఈరోడ్",
    "vellore": "వెల్లూరు",
    "thoothukudi": "తూత్తుకుడి",
    "tuticorin": "తూత్తుకుడి",
    "tirunelveli": "తిరునెల్వేలి",
    "dindigul": "దిండిగుల్",
    "thanjavur": "తంజావూరు",
    "kanyakumari": "కన్యాకుమారి",

    # Karnataka
    "bengaluru": "బెంగళూరు",
    "bangalore": "బెంగళూరు",
    "mysuru": "మైసూరు",
    "mysore": "మైసూరు",
    "mangaluru": "మంగళూరు",
    "mangalore": "మంగళూరు",
    "hubli": "హుబ్లీ",
    "dharwad": "ధారవాడ",
    "belagavi": "బెలగావి",
    "belgaum": "బెలగావి",
    "shimoga": "శివమొగ్గ",
    "shivamogga": "శివమొగ్గ",
    "tumakuru": "తుమకూరు",
    "bellary": "బళ్లారి",
    "ballari": "బళ్లారి",

    # Kerala
    "thiruvananthapuram": "తిరువనంతపురం",
    "trivandrum": "తిరువనంతపురం",
    "kochi": "కొచ్చి",
    "ernakulam": "ఎర్నాకుళం",
    "kozhikode": "కోజికోడ్",
    "calicut": "కోజికోడ్",
    "thrissur": "త్రిస్సూర్",
    "kollam": "కొల్లం",
    "alappuzha": "అలప్పుజ",
    "palakkad": "పాలక్కాడ్",
    "kottayam": "కొట్టాయం",
    "kannur": "కన్నూర్",
}

def get_location_te(location_en: str) -> str:
    return LOCATION_TE_MAP.get(location_en.lower().strip(), location_en)



def resolve_location(address: str, openai_client=None) -> tuple:
    """
    3-tier location resolution:
    Tier 1 → LOCATION_MAP direct match
    Tier 2 → AI extraction
    Tier 3 → Default fallback
    """
    addr_lower = (address or '').lower()

    # Tier 1
    for keyword, loc_id in LOCATION_MAP.items():
        if keyword in addr_lower:
            print(f"📍 [T1] '{address}' → [{loc_id}] {keyword.title()}")
            return loc_id, keyword.title()

    # Tier 2
    if openai_client and address and address.strip():
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": (
                        f"Extract the primary city or district name from: \"{address}\"\n"
                        f"Reply with ONLY the city name in lowercase English. Nothing else."
                    )
                }],
                max_tokens=20,
                temperature=0,
            )
            city = response.choices[0].message.content.strip().lower()
            if city in LOCATION_MAP:
                print(f"📍 [T2-AI] '{address}' → [{LOCATION_MAP[city]}] {city.title()}")
                return LOCATION_MAP[city], city.title()
            for keyword, loc_id in LOCATION_MAP.items():
                if keyword in city or city in keyword:
                    print(f"📍 [T2-AI partial] '{address}' → [{loc_id}] {keyword.title()}")
                    return loc_id, keyword.title()
            print(f"⚠️ [T2-AI] '{city}' not in LOCATION_MAP")
        except Exception as e:
            print(f"⚠️ AI location detection failed: {e}")

    # Tier 3
    if address and address.strip():
        hash_id = int(_hashlib.md5(address.lower().strip().encode()).hexdigest()[:5], 16) + 10000
        loc_name = address.strip().split(',')[-2].strip().title() if ',' in address else address.strip()
        print(f"📍 [T3-Hash] '{address}' → [{hash_id}] {loc_name}")
        return hash_id, loc_name

    print(f"⚠️ [T3-Default] '{address}' → [{DEFAULT_LOCATION_ID}] {DEFAULT_LOCATION_NAME}")
    return DEFAULT_LOCATION_ID, DEFAULT_LOCATION_NAME