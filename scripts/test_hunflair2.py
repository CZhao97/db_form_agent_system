from flair.data import Sentence
from flair.nn import Classifier

try:
    print("Attempting to load 'hunflair2'...")
    # The log suggested specifically 'hunflair2'
    tagger = Classifier.load('hunflair2')
    
    sentence = Sentence("Carbamazepine is a drug.")
    tagger.predict(sentence)
    
    print("Entities found:")
    for entity in sentence.get_spans('ner'):
        print(f" - {entity.text}: {entity.get_label('ner').value}")
        # Check for other labels or attributes that might hold the ID
        print(f"   Labels: {entity.labels}")
        if hasattr(entity, 'get_tag'):
             print(f"   Tags: {entity.get_tag('ner')}")

    # Also check if there's a specific 'linker' model or if hunflair2 includes it.
    
except Exception as e:
    print(f"Error: {e}")
