#!/usr/bin/env python
import os
import sys
from pathlib import Path


def main():
    # Lets the server's .env choose the settings module (DJANGO_SETTINGS_MODULE=config.settings.production).
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent / ".env")
    except ImportError:
        pass
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()