import json
import os
import sys

import requests


def main():
    endpoint = os.environ.get("BACKUP_ENDPOINT", "").strip()
    token = os.environ.get("BACKUP_JOB_TOKEN", "").strip()
    if not endpoint or not token:
        raise RuntimeError("Faltan BACKUP_ENDPOINT o BACKUP_JOB_TOKEN.")
    response = requests.post(
        endpoint,
        headers={"Authorization": "Bearer " + token},
        timeout=(20, 900),
    )
    try:
        result = response.json()
    except ValueError:
        result = {"response": response.text[:1000]}
    print(json.dumps(result, ensure_ascii=False))
    response.raise_for_status()
    if result.get("ok") is not True or result.get("verified") is not True:
        raise RuntimeError("El servidor no confirmó una copia legible y verificada.")
    print(
        "Respaldo guardado y verificado: "
        + str(result.get("filename"))
        + " | tablas: " + str(result.get("table_count"))
        + " | filas: " + str(result.get("total_rows"))
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        raise
