
import os
import re
from datetime import datetime
from typing import Dict, Any, Optional, List

def sanitize_filename(title: str) -> str:
    """Sanitizes the title for use as a filename."""
    # Remove special chars, keep alphanumeric, spaces, dashes
    s = re.sub(r'[^\w\s-]', '', title)
    return s.strip()[:100]  # Limit length

def export_paper_to_markdown(
    paper: Dict[str, Any],
    vault_path: str,
    chat_history: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """
    Exports a paper to a Markdown file in the specified vault path.
    Returns the absolute path of the created file.
    """
    if not os.path.exists(vault_path):
        os.makedirs(vault_path, exist_ok=True)

    filename = f"{sanitize_filename(paper.get('title', 'Untitled'))}.md"
    file_path = os.path.join(vault_path, filename)

    # Format Authors
    authors = paper.get('authors', [])
    if isinstance(authors, list):
        authors_str = ", ".join([f'"{a}"' for a in authors])
    else:
        authors_str = str(authors)

    # Format Tags
    categories = paper.get('categories', [])
    tags = ["arxiv", "paper"] + categories
    tags_str = ", ".join([t for t in tags])

    # Date
    date_str = paper.get('published', '')[:10]

    # Frontmatter
    content = f"""---
title: "{paper.get('title', 'Untitled')}"
authors: [{authors_str}]
published: {date_str}
url: {paper.get('pdf_url', '')}
tags: [{tags_str}]
status: to-read
created: {datetime.now().strftime("%Y-%m-%d %H:%M")}
---

# {paper.get('title', 'Untitled')}

## Summary
{paper.get('summary', 'No summary available.')}

"""

    if chat_history:
        content += f"\n## AI Notes\n{chat_history}\n"
    if notes:
        content += f"\n## Notes\n{notes}\n"
    
    # Write file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
        
    return file_path

def generate_bibtex(papers: List[Dict[str, Any]]) -> str:
    """Generates a BibTeX string for a list of papers."""
    bib_entries = []
    
    for p in papers:
        # Extract ID (e.g. http://arxiv.org/abs/2106.09685v2 -> 2106.09685)
        # Handle various ID formats
        if p['id'].startswith('http'):
            pid = p['id'].split('/')[-1].replace('v', '')
        else:
            pid = p['id']
            
        # Authors
        authors_list = p.get('authors', [])
        if isinstance(authors_list, str): authors_list = [authors_list]
        authors = " and ".join(authors_list)
        
        # Year
        year = p.get('published', '')[:4]
        
        # Categories
        cats = p.get('categories', [])
        if isinstance(cats, str): cats = [cats]
        primary_class = cats[0] if cats else 'cs.LG'
        
        entry = f"""@misc{{arxiv:{pid},
    title={{{p.get('title', 'Untitled')}}},
    author={{{authors}}},
    year={{{year}}},
    eprint={{{pid}}},
    archivePrefix={{arXiv}},
    primaryClass={{{primary_class}}},
    url={{{p.get('pdf_url', '')}}}
}}"""
        bib_entries.append(entry)
        
    return "\\n\\n".join(bib_entries)
