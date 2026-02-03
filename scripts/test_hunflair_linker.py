from flair.data import Sentence
from flair.nn import Classifier
from flair.models import EntityMentionLinker
import sys

# Absolute path to the no-ab3p model
LINKER_PATH = '/home/chen/.flair/models/biosyn-sapbert-bc5cdr-chemical-no-ab3p/models--hunflair--biosyn-sapbert-bc5cdr-chemical-no-ab3p/snapshots/2929796c7af2316d3ae17447780487e5a86a2e8e/pytorch_model.bin'

try:
    print("Loading NER (hunflair2)...")
    ner = Classifier.load('hunflair2')
    
    print(f"Loading Linker from {LINKER_PATH}...")
    try:
        linker = EntityMentionLinker.load(LINKER_PATH)
        print("Linker loaded successfully!")
    except Exception as e:
        print(f"EntityMentionLinker.load failed: {e}")
        sys.exit(1)

    sentence = Sentence("Carbamazepine is a drug.")
    
    # 1. NER
    ner.predict(sentence)
    
    # 2. Linking
    # Linker expects entities to be present.
    # IMPORTANT: The linker might expect specific label types (e.g., 'ner' or 'Chemical').
    # hunflair2 outputs 'Chemical' labels.
    linker.predict(sentence)
    
    print("Entities found:")
    for entity in sentence.get_spans('ner'):
        print(f" - {entity.text}")
        # Check all labels
        for label in entity.labels:
             print(f"   Label: {label.value} (Score: {label.score})")
        
        # Check specific output format
        # Usually it adds a top label with the ID
except Exception as e:
    print(f"Error: {e}")
