"""Entrypoint: migrate then run bot."""
import subprocess
import sys

if __name__ == "__main__":
    print("Running migrations...")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    print("Starting bot...")
    subprocess.run([sys.executable, "-m", "src.main"], check=True)
