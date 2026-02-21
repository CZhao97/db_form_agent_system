
import pandas as pd
import matplotlib.pyplot as plt
import argparse
import os

def generate_plot(csv_path):
    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}")
        return

    try:
        df = pd.read_csv(csv_path)
        if df.empty or "normalized_prediction" not in df.columns:
            print("DataFrame empty or missing 'normalized_prediction'")
            return

        plt.figure(figsize=(10, 6))
        counts = df['normalized_prediction'].value_counts()
        counts.plot(kind='bar', color='#4CAF50') # Green color for 'fresh' results
        plt.title(f'Distribution of Normalized Predictions (N={len(df)})')
        plt.xlabel('Prediction')
        plt.ylabel('Count')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        
        output_path = os.path.splitext(csv_path)[0] + '_interim.png'
        plt.savefig(output_path)
        print(f"Plot saved to {output_path}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    generate_plot("evaluation_results_recovered_sample_500.csv")
