import os
import re
import time
import sqlite3
import requests
from bs4 import BeautifulSoup

# Define targets representing WA State Local Government structure
TARGET_URLS = [
    {
        "url": "https://mrsc.org/explore-topics/government-organization",
        "title": "Government Organization Overview",
        "section": "Government Organization"
    },
    {
        "url": "https://mrsc.org/explore-topics/government-organization/special-districts/what-is-a-special-purpose-district",
        "title": "What Is a Special Purpose District?",
        "section": "Special Purpose Districts"
    },
    {
        "url": "https://mrsc.org/explore-topics/government-organization/cities/city-forms-of-government",
        "title": "City and Town Forms of Government",
        "section": "Cities and Towns"
    },
    {
        "url": "https://mrsc.org/explore-topics/government-organization/counties/county-forms-of-government",
        "title": "County Forms of Government",
        "section": "Counties"
    }
]

DB_DIR = "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper"
DB_PATH = os.path.join(DB_DIR, "mrsc_knowledge.db")

def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS mrsc_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            title TEXT,
            section TEXT,
            content_markdown TEXT,
            last_scraped TEXT
        )
    """)
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")

def html_to_markdown(soup_body):
    """Simple parser to convert BS4 elements to Markdown."""
    markdown_lines = []
    
    # Process elements in order
    for elem in soup_body.descendants:
        if elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            level = int(elem.name[1])
            text = elem.get_text().strip()
            if text:
                markdown_lines.append(f"\n{'#' * level} {text}\n")
        elif elem.name == 'p':
            # Check if this paragraph is already inside another parsed block
            if elem.parent.name in ['li', 'td', 'th']:
                continue
            text = ""
            for child in elem.children:
                if child.name == 'a':
                    href = child.get('href', '')
                    if href.startswith('/'):
                        href = f"https://mrsc.org{href}"
                    text += f" [{child.get_text().strip()}]({href}) "
                else:
                    text += child.get_text()
            text = re.sub(r'\s+', ' ', text).strip()
            if text:
                markdown_lines.append(f"{text}\n")
        elif elem.name == 'li':
            text = elem.get_text().strip()
            if text:
                markdown_lines.append(f"* {text}")
        elif elem.name == 'table':
            # Parse table to markdown table
            rows = elem.find_all('tr')
            if not rows:
                continue
            table_lines = []
            
            for i, r in enumerate(rows):
                cols = r.find_all(['td', 'th'])
                col_texts = [re.sub(r'\s+', ' ', c.get_text().strip()) for c in cols]
                table_lines.append(f"| {' | '.join(col_texts)} |")
                
                # Add separator after header row
                if i == 0:
                    seps = ['---' for _ in col_texts]
                    table_lines.append(f"| {' | '.join(seps)} |")
            
            markdown_lines.append("\n" + "\n".join(table_lines) + "\n")
            
    # Clean up excess newlines
    md = "\n".join(markdown_lines)
    md = re.sub(r'\n{3,}', '\n\n', md)
    return md.strip()

def crawl_and_index():
    init_db()
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cur = conn.cursor()
    
    for target in TARGET_URLS:
        url = target["url"]
        print(f"Crawling {url}...")
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                
                # Find the main content body of the MRSC article
                content_div = soup.find(class_="content-body") or soup.find(class_="content-container")
                if not content_div:
                    content_div = soup.find("body")
                    
                title = target["title"]
                page_title_el = soup.find(class_="main-page-title")
                if page_title_el:
                    title = page_title_el.get_text().strip()
                    
                markdown_content = html_to_markdown(content_div)
                
                cur.execute("""
                    INSERT INTO mrsc_knowledge (url, title, section, content_markdown, last_scraped)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET
                        title=excluded.title,
                        section=excluded.section,
                        content_markdown=excluded.content_markdown,
                        last_scraped=excluded.last_scraped
                """, (url, title, target["section"], markdown_content, time.strftime("%Y-%m-%dT%H:%M:%SZ")))
                conn.commit()
                print(f"Successfully indexed: {title} ({len(markdown_content)} characters)")
            else:
                print(f"Failed to crawl {url}: HTTP {r.status_code}")
        except Exception as e:
            print(f"Error crawling {url}: {e}")
            
        time.sleep(1)
        
    conn.close()
    print("Crawling and indexing complete.")

if __name__ == "__main__":
    crawl_and_index()
