from pathlib import Path

DATA_DIR = Path("./data")
FILES_DIR = DATA_DIR / "files"


def ensure_dirs() -> None:
    FILES_DIR.mkdir(parents=True, exist_ok=True)


def save_bytes(key: str, data: bytes) -> str:
    """
    key: например "results/task_1.txt"
    Сохраняем в ./data/files/results/task_1.txt
    """
    ensure_dirs()
    safe_key = key.strip("/").replace("\\", "/")
    path = FILES_DIR / safe_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return safe_key


def read_bytes(key: str) -> bytes:
    ensure_dirs()
    safe_key = key.strip("/").replace("\\", "/")
    path = FILES_DIR / safe_key
    return path.read_bytes()
