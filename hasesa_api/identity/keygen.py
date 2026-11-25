"""Generate the secrets Hasesa Accounts needs, ready to paste into Vercel.

    uv run python -m hasesa_api.identity.keygen > secrets.env

Writes to stdout only; nothing is saved. Keep the output out of git and chat.
"""

import secrets

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    web_secret = secrets.token_urlsafe(32)
    print("# hasesa-api (Vercel > hasesa-api > Settings > Environment Variables)")
    print("JWT_PRIVATE_KEY=" + pem.strip().replace("\n", "\\n"))
    print("JWT_KEY_ID=hasesa-" + secrets.token_hex(4))
    print("REFRESH_TOKEN_SECRET=" + secrets.token_urlsafe(48))
    print("CLIENT_SECRETS=hasesa-web:" + web_secret)
    print()
    print("# hasesa-lab-web (Vercel > web project > Settings > Environment Variables)")
    print("HASESA_CLIENT_SECRET=" + web_secret)


if __name__ == "__main__":
    main()
