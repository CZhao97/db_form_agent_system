
import pandas as pd
import os

def calc_blood_recall():
    # Load Agent Results
    try:
        df_agent = pd.read_csv("evaluation_results_blood.csv")
        # Agent Verdict: "Confirmed" or "Yes"
        
        # Normalize Agent Verdict
        def is_confirmed(val):
            s = str(val).lower()
            return "confirm" in s or "yes" in s
            
        confirmed_count = df_agent[df_agent['agent_verdict'].apply(is_confirmed)].shape[0]
        total_count = df_agent.shape[0]
        
        recall = (confirmed_count / total_count) * 100 if total_count > 0 else 0
        
        print(f"Total Compounds: {total_count}")
        print(f"Agent Confirmed: {confirmed_count}")
        print(f"Recall: {recall:.2f}%")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    calc_blood_recall()
