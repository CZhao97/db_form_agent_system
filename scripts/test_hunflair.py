from flair.data import Sentence
from flair.nn import Classifier
import sys

try:
    # Try loading hunflair2 first (if it exists as a model name)
    # The user said "Hunflair2", which is likely the "hunflair" model in newer flair versions or "hunflair-chemical"
    # Let's try 'hunflair' which loads all 5 classes, or 'hunflair-chemical'
    print("Attempting to load 'hunflair-chemical'...")
    tagger = Classifier.load('hunflair-chemical')
    
    sentence = Sentence("Carbamazepine is a drug.")
    tagger.predict(sentence)
    
    print("Entities found:")
    for entity in sentence.get_spans('ner'):
        print(f" - {entity.text}: {entity.get_label('ner').value} (Score: {entity.get_label('ner').score})")
        # Check for normalization/linking info if available
        # In flair, linked entities might be in a different attribute or tag
    
except Exception as e:
    print(f"Error: {e}")
