import requests
import json
import phonenumbers
from phonenumbers import carrier, geocoder, timezone

class GhostTrackService:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

    def ip_track(self, ip: str) -> str:
        if not ip:
            return "Geen IP adres ingevuld."
        try:
            url = f"http://ipwho.is/{ip}"
            resp = self.session.get(url, timeout=10)
            data = resp.json()
            if data.get("success"):
                conn = data.get("connection", {})
                tz = data.get("timezone", {})
                return (
                    f"✓ IP: {ip}\n"
                    f"✓ Land: {data.get('country', 'N/A')} ({data.get('country_code', 'N/A')})\n"
                    f"✓ Stad: {data.get('city', 'N/A')}\n"
                    f"✓ Regio: {data.get('region', 'N/A')}\n"
                    f"✓ Coördinaten: {data.get('latitude', 'N/A')}, {data.get('longitude', 'N/A')}\n"
                    f"✓ ISP: {conn.get('isp', 'N/A')}\n"
                    f"✓ Organisatie: {conn.get('organization', 'N/A')}\n"
                    f"✓ Tijdzone: {tz.get('id', 'N/A')} ({tz.get('current_time', 'N/A')})"
                )
            else:
                return f"Fout: {data.get('message', 'Onbekende fout')}"
        except Exception as e:
            return f"Netwerk fout: {e}"

    def phone_track(self, phone: str) -> str:
        if not phone:
            return "Geen telefoonnummer ingevuld."
        try:
            parsed = phonenumbers.parse(phone, "NL")
            if not phonenumbers.is_valid_number(parsed):
                return "Ongeldig telefoonnummer."
            region = phonenumbers.region_code_for_number(parsed)
            carrier_name = carrier.name_for_number(parsed, "NL")
            geo = geocoder.description_for_number(parsed, "NL")
            tzs = timezone.time_zones_for_number(parsed)
            return (
                f"✓ Nummer: {phone}\n"
                f"✓ Geldig: Ja\n"
                f"✓ Regio: {region}\n"
                f"✓ Locatie (ca.): {geo}\n"
                f"✓ Drager: {carrier_name}\n"
                f"✓ Tijdzone: {', '.join(tzs)}"
            )
        except Exception as e:
            return f"Fout: {e}"

# Dit is de naam die we gaan importeren in gui.py
ghost_service = GhostTrackService()

# --- BESTAANDE FUNCTIES (Behouden voor de rest van je app) ---

def get_public_ip():
    try:
        r = requests.get('http://ipwho.is', timeout=5)
        return r.json().get('ip')
    except:
        return "127.0.0.1"

def validate_url(url):
    try:
        from urllib.parse import urlparse
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def test_telegram_token(token):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
        return r.status_code == 200
    except:
        return False

def normalize_username_list(usernames):
    if not isinstance(usernames, list):
        usernames = [usernames]
    return [u.strip() for u in usernames if u.strip()]

def read_diagnostic_records():
    return []

class ConsentDiagnosticServer:
    def __init__(self):
        pass