#!/usr/bin/env python3
"""
UCF Room Scraper

Usage:
    python main.py refresh                  Scrape UCF and write data/schedule.json
    python main.py refresh --workers 4      Use 4 parallel browsers
    python main.py refresh --subjects MAS   Re-scrape specific subjects (merges into existing data)
"""

import logging
import sys

import click
from rich.console import Console

from config import DATA_FILE, DEFAULT_TERM

console = Console()


@click.command(context_settings={"help_option_names": ["--help", "-h"]})
@click.argument("command", default="refresh")
@click.option("--term",                   default=DEFAULT_TERM, show_default=True)
@click.option("--headless/--no-headless", default=True)
@click.option("--subjects",               default=None, metavar="A,B,C", help="Comma-separated subject codes")
@click.option("--workers", "-w",          default=1, type=int, show_default=True)
def cli(command, term, headless, subjects, workers):
    if command != "refresh":
        console.print(f"[red]Unknown command '{command}'.[/red] Only [bold]refresh[/bold] is supported.")
        sys.exit(1)

    from scraper import scrape

    subject_list = [s.strip().upper() for s in subjects.split(",")] if subjects else None
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

    console.print(f"[bold]Scraping UCF — term [cyan]{term}[/cyan][/bold]")
    if subject_list:
        console.print(f"Subjects: {', '.join(subject_list)}")
    else:
        console.print("[dim]All subjects — this takes a while[/dim]")
    if workers > 1:
        console.print(f"[dim]{workers} parallel browsers[/dim]")

    try:
        result = scrape(term=term, headless=headless, subjects=subject_list, workers=workers)
        console.print(f"\n[green]Done![/green] {len(result['rooms'])} rooms → [dim]{DATA_FILE}[/dim]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()
