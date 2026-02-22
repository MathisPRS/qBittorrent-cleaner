import requests
import secrets

# ==========================
# CONFIG
# ==========================
TORRENT_NAME = "Mathis.fais.des.tests.2160p.5.1.X265.mkv"
API_URL = "http://192.168.10.5:8124/api/torrent"

# ==========================
# GENERATE RANDOM HASH (40 hex chars like torrent info-hash)
# ==========================
def generate_random_hash():
    return secrets.token_hex(20)  # 20 bytes = 40 hex chars


def main():
    torrent_hash = "964e60a5dec633cbfd463da8ac2fc0100b066189"

    payload = {
        "name": TORRENT_NAME,
        "hash": torrent_hash
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