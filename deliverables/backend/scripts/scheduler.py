"""In-process scheduler loop for a single box: `python -m scripts.scheduler`."""

from app.services.scheduler import loop

if __name__ == "__main__":
    loop()
