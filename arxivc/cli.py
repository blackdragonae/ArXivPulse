import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm
from . import client, storage, ranker, downloader

app = typer.Typer()
console = Console()

@app.command()
def fetch(max_results: int = 100):
    """
    Fetch new papers from ArXiv and save them to the local database.
    """
    console.print(f"[bold green]Fetching timestamp...[/bold green] (limit={max_results})")
    
    # Initialize DB if not exists
    storage.init_db()
    
    # Fetch
    try:
        papers = client.fetch_papers(max_results=max_results)
    except Exception as e:
        console.print(f"[bold red]Error fetching papers:[/bold red] {e}")
        return

    # Save
    new_count = storage.save_papers(papers)
    console.print(f"[bold blue]Fetched {len(papers)} papers. {new_count} are new.[/bold blue]")

@app.command("list")
def list_papers(limit: int = 10, unread: bool = True):
    """
    List papers ranked by relevance.
    """
    # Initialize DB if not exists (in case fetch wasn't run)
    storage.init_db()
    
    papers = storage.get_papers_by_status('new')
    if not papers:
        console.print("No new papers found. Run 'fetch' first.")
        return

    ranked = ranker.rank_papers(papers)
    top_papers = ranked[:limit]

    table = Table(title=f"Top {len(top_papers)} Papers")
    table.add_column("Score", style="cyan", no_wrap=True)
    table.add_column("Title", style="magenta")
    table.add_column("Authors", style="green")
    table.add_column("Date", style="yellow")

    for p in top_papers:
        authors = ", ".join(p['authors'][:3]) 
        if len(p['authors']) > 3:
            authors += " et al."
        table.add_row(str(p['score']), p['title'], authors, p['published'][:10])

    console.print(table)

@app.command()
def rate():
    """
    Interactive mode to rate papers.
    """
    storage.init_db()
    papers = storage.get_papers_by_status('new')
    ranked = ranker.rank_papers(papers)
    
    if not ranked:
        console.print("No new papers to rate.")
        return

    console.print(f"found {len(ranked)} papers to rate (sorted by score).")
    
    for p in ranked:
        console.clear()
        console.print(Panel(
            f"[bold]{p['title']}[/bold]\n\n"
            f"[italic]{', '.join(p['authors'])}[/italic]\n"
            f"Published: {p['published']}\n"
            f"Score: {p.get('score', 0)}\n\n"
            f"{p['summary']}",
            title=f"Paper: {p['id']}",
            expand=False
        ))
        
        console.print("\n[dim]Categories: " + ", ".join(p['categories']) + "[/dim]\n")
        
        if Confirm.ask("Are you interested in this paper?"):
            storage.update_interaction(p['id'], 'liked')
            console.print("[green]Saved to favorites![/green]")
        else:
            if Confirm.ask("Dismiss?", default=True):
                storage.update_interaction(p['id'], 'dismissed')
                console.print("[red]Dismissed.[/red]")
            else:
                console.print("[yellow]Skipped.[/yellow]")
        
        if not Confirm.ask("Continue?", default=True):
            break

@app.command("download-favorites")
def download_favorites():
    """
    Downloads PDFs for all papers marked as 'liked'.
    """
    storage.init_db()
    papers = storage.get_papers_by_status('liked')
    if not papers:
        console.print("No favorites found.")
        return
        
    console.print(f"[bold green]Downloading {len(papers)} favorites...[/bold green]")
    for p in papers:
        downloader.download_pdf(p['id'])
    
    console.print("[bold blue]Done.[/bold blue]")

if __name__ == "__main__":
    app()
