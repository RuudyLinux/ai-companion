"""
Trains a local (no-API, no-cloud) text emotion classifier from the bundled datasets:
- GoEmotions (28-label, ~43K Reddit comments) -> data/train.tsv
- EmpatheticDialogues-style 32-label set -> emotion-emotion_69k.csv

Both are mapped onto the 15-label taxonomy from the Emotional Conversation Module
spec (see label_mapping.py), combined, and used to train a TF-IDF + Logistic
Regression classifier. Runs on CPU in well under a minute.

Usage: venv\\Scripts\\python.exe emotion\\train_classifier.py
"""

import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from emotion.label_mapping import GOEMOTIONS_TO_OURS, EMPATHETIC_TO_OURS, GOEMOTIONS_LABEL_ORDER

DATASET_ROOT = Path(r"D:/#practicals/AI companion/Dataset")
GOEMOTIONS_TRAIN_TSV = DATASET_ROOT / "GoEmotions" / "data" / "train.tsv"
EMPATHETIC_CSV = DATASET_ROOT / "emotion-emotion_69k.csv"
MODEL_OUT = Path(__file__).resolve().parent.parent / "models_store" / "emotion_classifier.joblib"


def load_goemotions() -> pd.DataFrame:
    df = pd.read_csv(GOEMOTIONS_TRAIN_TSV, sep="\t", header=None, names=["text", "labels", "rater_id"])
    # multi-label rows: take only the first label id, mapped through the fixed label order
    first_label_id = df["labels"].str.split(",").str[0].astype(int)
    label_name = first_label_id.map(lambda i: GOEMOTIONS_LABEL_ORDER[i])
    mapped = label_name.map(GOEMOTIONS_TO_OURS)
    out = pd.DataFrame({"text": df["text"], "emotion": mapped}).dropna()
    return out


def load_empathetic() -> pd.DataFrame:
    df = pd.read_csv(EMPATHETIC_CSV)
    df = df[["Situation", "emotion"]].dropna().drop_duplicates()
    mapped = df["emotion"].str.strip().str.lower().map(EMPATHETIC_TO_OURS)
    out = pd.DataFrame({"text": df["Situation"], "emotion": mapped}).dropna()
    return out


def main():
    print("Loading GoEmotions...")
    go = load_goemotions()
    print(f"  {len(go)} labeled rows")

    print("Loading EmpatheticDialogues-style set...")
    emp = load_empathetic()
    print(f"  {len(emp)} labeled rows")

    data = pd.concat([go, emp], ignore_index=True)
    data = data[data["text"].str.strip().str.len() > 0]
    print(f"\nCombined: {len(data)} rows")
    print(data["emotion"].value_counts())

    X_train, X_test, y_train, y_test = train_test_split(
        data["text"], data["emotion"], test_size=0.1, random_state=42, stratify=data["emotion"]
    )

    vectorizer = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=2)
    X_train_vec = vectorizer.fit_transform(X_train)
    X_test_vec = vectorizer.transform(X_test)

    model = LogisticRegression(max_iter=1000, class_weight="balanced", n_jobs=-1)
    model.fit(X_train_vec, y_train)

    preds = model.predict(X_test_vec)
    print(f"\nTest accuracy: {accuracy_score(y_test, preds):.3f}")
    print(classification_report(y_test, preds, zero_division=0))

    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"vectorizer": vectorizer, "model": model}, MODEL_OUT)
    print(f"\nSaved model to {MODEL_OUT}")


if __name__ == "__main__":
    main()
