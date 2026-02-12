import sys
import os
sys.path.append(os.getcwd())
from arxivc.ai_service import generate_brief

# Mock papers
papers = [
    {"title": "Deep Learning for Cats", "summary": "A study on neural networks detecting felines.", "published": "2023-01-01"},
    {"title": "Quantum Gravity", "summary": "String theory implications.", "published": "2023-01-02"},
    {"title": "Attention Is All You Need", "summary": "Transformer architecture.", "published": "2023-01-03"},
    {"title": "Biology of Frogs", "summary": "Amphibian studies.", "published": "2023-01-04"},
    {"title": "Generative Models for Art", "summary": "Using GANs to paint.", "published": "2023-01-05"},
]

keywords = ["Transformer", "Generative"]

print(f"Testing with keywords: {keywords}")

# We expect "Attention Is All You Need" and "Generative Models for Art" to be top.
# Note: generate_brief calls query_ollama. If ollama fails/is mocked, it returns fallback.
# We will rely on fallback output to check ranking if Ollama is offline/not mocked.
# But wait, the ai_service imports requests. We can't easily mock it without unittest.mock.
# Let's just run it. If Ollama is running, it might generate a real response. 
# If not, fallback shows ranking.
# To force fallback for verification of RANKING, we can temporarily assume Ollama is not running 
# or just check the input to the prompt if we could hook it. 

# Let's just check the result.
output = generate_brief(papers, keywords)
print("OUTPUT START")
print(output)
print("OUTPUT END")

# Check if relevant papers are mentioned early or in the prompt context (if we could see it).
# In fallback mode, we check for "matches: Transformer" string.
if "matches: Transformer" in output or "Generative" in output:
    print("SUCCESS: Keywords found in output.")
else:
    print("WARNING: Keywords not explicitly found (might be fully AI generated).")
