import requests
import secrets

# ==========================
# CONFIG
# ==========================
TORRENT_NAME = "Taken 2 (2012) Version Non Censurée MULTi VFF 1080p 10bit HDLight BluRay x265 AC3 5.1-MM91.mkv"
API_URL = "http://127.0.0.1:8124/api/torrent"

# ==========================
# GENERATE RANDOM HASH (40 hex chars like torrent info-hash)
# ==========================
def generate_random_hash():
    return secrets.token_hex(20)  # 20 bytes = 40 hex chars


def main():
    torrent_hash = generate_random_hash()

    parent_hash = "131fb13ty8974cf4agy_d9cda5fad89agsf4c4c1"

    payload = {
        "name": TORRENT_NAME,
        "hash": torrent_hash,
        "parent_hash": parent_hash
    }

    print("Payload envoyé :")
    print(payload)

    try:
        response = requests.post(API_URL, json=payload, timeout=10)

        print("\nStatus code :", response.status_code)
        print("Response :", response.text)

    except requests.exceptions.RequestException as e:
        print("Erreur lors de l'appel API :", e)


if __name__ == "__main__":
    main()