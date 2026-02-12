
import asyncio
import uuid
import time
from typing import List, Dict, Set
from . import client, ai_service, citation_service

class ResearchAgent:
    def __init__(self, topic: str, max_depth: int = 2, max_papers: int = 15):
        self.id = str(uuid.uuid4())
        self.topic = topic
        self.max_depth = max_depth
        self.max_papers = max_papers
        
        self.visited: Set[str] = set() # Paper IDs
        self.queue: List[Dict] = [] # (paper_id, depth)
        self.findings: List[str] = []
        self.logs: List[str] = []
        self.status = "idle" # running, completed, error
        self.result = None
        
    def log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        entry = f"[{timestamp}] {msg}"
        self.logs.append(entry)
        print(f"[Agent {self.id[:8]}] {msg}")

    def run(self):
        self.status = "running"
        self.log(f"Starting Deep Research on: '{self.topic}'")
        
        try:
            # 1. Initial Search
            self.log("Phase 1: Initial Search...")
            papers = client.search_archive(self.topic, max_results=5)
            
            for p in papers:
                self.queue.append((p, 0))
                
            self.log(f"Found {len(papers)} seed papers.")
            
            processed_count = 0
            
            while self.queue and processed_count < self.max_papers:
                # BFS Pop
                current_paper, depth = self.queue.pop(0)
                
                # Check normalized ID to avoid cycles
                # Simple normalization (removing http/arxiv)
                pid = current_paper['id']
                if pid in self.visited:
                    continue
                self.visited.add(pid)
                
                # 2. Evaluate Relevance
                self.log(f"Analyzing: {current_paper['title'][:50]}... (Depth {depth})")
                
                # ERROR HANDLING: Ensure summary exists
                summary = current_paper.get('summary', '')
                if not summary:
                     # Try to fetch? Or just skip
                     self.log("Skipping: No summary available.")
                     continue

                is_relevant = ai_service.decide_relevance(self.topic, summary)
                
                if not is_relevant:
                    self.log(f"Skipping: Too irrelevant.")
                    continue
                    
                processed_count += 1
                self.log(f"ACCEPTED. Reading paper...")
                
                # Store finding
                note = f"Paper: {current_paper['title']}\nSummary: {summary}\nRelevance: High"
                self.findings.append(note)
                
                # 3. Expand (if depth allows)
                if depth < self.max_depth:
                    self.log(f"Checking citations for expansion...")
                    # Fetch citations
                    graph = citation_service.get_paper_graph(pid)
                    if not graph: 
                        continue
                        
                    # Add meaningful connections to queue
                    citations = graph.get('citations', [])
                    references = graph.get('references', [])
                    
                    new_candidates = citations[:3] + references[:3]
                    
                    for cand in new_candidates:
                        if cand['id'] not in self.visited:
                            c_obj = {
                                'id': cand['id'],
                                'title': cand.get('title', 'Unknown'),
                                'summary': cand.get('title', '') # Use title as proxy 
                            }
                            self.queue.append((c_obj, depth + 1))
            
            # 4. Final Synthesis
            self.log("Phase 2: Synthesis...")
            if not self.findings:
                self.result = "No relevant papers found to start a report."
            else:
                self.result = ai_service.synthesize_research_report(self.topic, self.findings)
                
                # SAVE TO DISK
                try:
                    import os
                    os.makedirs("reports", exist_ok=True)
                    filename = f"reports/Deep_Research_{self.topic[:30].replace(' ', '_')}_{str(uuid.uuid4())[:8]}.md"
                    with open(filename, "w") as f:
                        f.write(self.result)
                    self.log(f"Report saved to: {filename}")
                except Exception as save_err:
                    self.log(f"Error saving report: {save_err}")
                
            self.log("Mission Complete.")
            self.status = "completed"
            
        except Exception as e:
            self.log(f"CRITICAL ERROR: {e}")
            self.status = "error"
            self.result = f"Error: {str(e)}"

# Global Job Store
JOBS: Dict[str, ResearchAgent] = {}

def start_agent(topic: str) -> str:
    agent = ResearchAgent(topic)
    JOBS[agent.id] = agent
    return agent.id


class SurveyAgent(ResearchAgent):
    """
    Agent that generates a structured survey paper.
    Stages:
    1. Search & Filter
    2. Cluster (Themes)
    3. Draft Sections
    4. Compile
    """
    def run(self):
        self.status = "running"
        self.log(f"Starting Auto-Survey on: '{self.topic}'")
        
        try:
            # 1. Search
            self.log("Phase 1: Broad Search...")
            # Search more papers than usual
            candidates = client.search_archive(self.topic, max_results=30)
            self.log(f"Found {len(candidates)} candidates.")
            
            # Simple dedupe
            papers = {p['id']: p for p in candidates}.values()
            
            # 2. Cluster
            self.log("Phase 2: Thematic Clustering...")
            import json
            clusters_json = ai_service.cluster_papers(list(papers))
            try:
                clusters = json.loads(clusters_json)
                self.log(f"Identified {len(clusters)} themes: {', '.join(clusters.keys())}")
            except:
                self.log("Clustering failed. Fallback to single cluster.")
                clusters = {"General Overview": [p['id'] for p in papers]}
                
            # 3. Draft Sections
            self.log("Phase 3: Drafting Sections...")
            sections = {}
            for theme, pids in clusters.items():
                self.log(f"Drafting section: {theme} ({len(pids)} papers)")
                
                # Get full paper objects
                cluster_papers = [p for p in papers if p['id'] in pids]
                
                if not cluster_papers:
                    continue
                    
                section_text = ai_service.write_survey_section(theme, cluster_papers)
                sections[theme] = section_text
                
            # 4. Compile
            self.log("Phase 4: Compiling Report...")
            report = f"# Survey: {self.topic}\n\n"
            report += "## Abstract\n"
            report += f"This survey reviews {len(papers)} recent papers on **{self.topic}**, organized into {len(clusters)} key themes.\n\n"
            
            report += "## Table of Contents\n"
            for theme in sections.keys():
                report += f"- [{theme}](#{theme.lower().replace(' ', '-')})\n"
            report += "\n---\n\n"
            
            for theme, content in sections.items():
                report += f"## {theme}\n\n"
                report += content + "\n\n"
                
            report += "## References\n"
            for p in papers:
                report += f"- **[{p['id']}]** {p['title']} ({p['published'][:4]})\n"
                
            self.result = report
            
            # Save
            import os
            os.makedirs("reports", exist_ok=True)
            filename = f"reports/Survey_{self.topic[:30].replace(' ', '_')}_{str(uuid.uuid4())[:8]}.md"
            with open(filename, "w") as f:
                f.write(report)
            self.log(f"Survey saved to: {filename}")
            
            self.status = "completed"
            self.log("Survey Generation Complete.")

        except Exception as e:
            self.log(f"CRITICAL ERROR: {e}")
            self.status = "error"
            self.result = f"Error: {str(e)}"
            import traceback
            traceback.print_exc()

def start_survey_agent(topic: str) -> str:
    agent = SurveyAgent(topic)
    JOBS[agent.id] = agent
    return agent.id
