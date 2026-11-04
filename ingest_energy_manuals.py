import argparse

from energy_machine_manuals import ingest_machine_manuals
from rag_service import list_documents


def main():
    parser = argparse.ArgumentParser(description="Genera e indexa los manuales RAG de los activos Energy")
    parser.add_argument("--if-empty", action="store_true", help="No reindexar si ya existen manuales Energy")
    args = parser.parse_args()
    if args.if_empty and any(row["document_name"].startswith("MAN-ENE-") for row in list_documents()):
        print("Los manuales Energy ya se encuentran indexados.")
        return
    machines, chunks = ingest_machine_manuals()
    print(f"Manuales Energy indexados: {machines} máquinas, {chunks} fragmentos")


if __name__ == "__main__":
    main()
