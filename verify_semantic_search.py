
import sys
import os
import sqlite3
import numpy as np
sys.path.append(os.getcwd())
from arxivc import storage, embeddings

def main():
    print("Testing Semantic Search...")
    storage.init_db()
    
    # Mock Data
    # We will insert mock embeddings directly to test retrieval logic
    # independent of the model quality (though we use the model to generate them)
    print("Generating mock embeddings...")
    e1 = embeddings.generate_embedding("The theory of general relativity and black holes")
    e2 = embeddings.generate_embedding("Deep learning and neural networks for image recognition")
    
    id1 = "test_relativity"
    id2 = "test_deeplearning"
    
    # Save (will overwrite if exists)
    storage.save_embedding(id1, e1)
    storage.save_embedding(id2, e2)
    
    # Test 1: Search for "Einstein" (should match relativity)
    q1 = "Gravity and spacetime curvature"
    print(f"\nQuery: '{q1}'")
    v1 = embeddings.generate_embedding(q1)
    results1 = storage.search_semantic(v1, limit=5)
    
    print("Results:")
    found_1 = False
    for r in results1:
        print(f" - {r['id']} (score: {r['score']:.4f})")
        if r['id'] == id1 and r['score'] > 0.4:
            found_1 = True
            
    if found_1:
        print("SUCCESS: Found relativity paper for gravity query.")
    else:
        print("FAILURE: Did not find relativity paper.")

    # Test 2: Search for "CNN" (should match deep learning)
    q2 = "Convolutional networks"
    print(f"\nQuery: '{q2}'")
    v2 = embeddings.generate_embedding(q2)
    results2 = storage.search_semantic(v2, limit=5)
    
    print("Results:")
    found_2 = False
    for r in results2:
        print(f" - {r['id']} (score: {r['score']:.4f})")
        if r['id'] == id2 and r['score'] > 0.4:
            found_2 = True
            
    if found_2:
        print("SUCCESS: Found deep learning paper for CNN query.")
    else:
        print("FAILURE: Did not find deep learning paper.")
        
    # Cleanup
    conn = sqlite3.connect(storage.DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM paper_embeddings WHERE paper_id IN (?, ?)", (id1, id2))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
