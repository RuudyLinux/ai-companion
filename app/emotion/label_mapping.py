"""
Maps the two source dataset taxonomies onto the 15-label emotion set from the
Emotional Conversation Module spec:
happy, sad, angry, frustrated, stressed, anxious, excited, nervous, lonely,
confused, fearful, calm, curious, surprised, neutral

Neither source dataset has a "stressed" label directly, so that class is
under-represented in training data; classifier.py applies a keyword-based
override as a pragmatic patch for that one label.
"""

OUR_LABELS = [
    "happy", "sad", "angry", "frustrated", "stressed", "anxious", "excited",
    "nervous", "lonely", "confused", "fearful", "calm", "curious", "surprised", "neutral",
]

# GoEmotions (28 labels, index order from data/emotions.txt) -> ours
GOEMOTIONS_TO_OURS = {
    "admiration": "happy",
    "amusement": "happy",
    "anger": "angry",
    "annoyance": "frustrated",
    "approval": "calm",
    "caring": "calm",
    "confusion": "confused",
    "curiosity": "curious",
    "desire": "excited",
    "disappointment": "sad",
    "disapproval": "frustrated",
    "disgust": "angry",
    "embarrassment": "nervous",
    "excitement": "excited",
    "fear": "fearful",
    "gratitude": "happy",
    "grief": "sad",
    "joy": "happy",
    "love": "happy",
    "nervousness": "nervous",
    "optimism": "calm",
    "pride": "happy",
    "realization": "curious",
    "relief": "calm",
    "remorse": "sad",
    "sadness": "sad",
    "surprise": "surprised",
    "neutral": "neutral",
}

# EmpatheticDialogues (32 labels, from emotion-emotion_69k.csv) -> ours
EMPATHETIC_TO_OURS = {
    "afraid": "fearful",
    "angry": "angry",
    "annoyed": "frustrated",
    "anticipating": "excited",
    "anxious": "anxious",
    "apprehensive": "nervous",
    "ashamed": "nervous",
    "caring": "calm",
    "confident": "calm",
    "content": "calm",
    "devastated": "sad",
    "disappointed": "sad",
    "disgusted": "angry",
    "embarrassed": "nervous",
    "excited": "excited",
    "faithful": "calm",
    "furious": "angry",
    "grateful": "happy",
    "guilty": "sad",
    "hopeful": "excited",
    "impressed": "happy",
    "jealous": "angry",
    "joyful": "happy",
    "lonely": "lonely",
    "nostalgic": "sad",
    "prepared": "calm",
    "proud": "happy",
    "sad": "sad",
    "sentimental": "sad",
    "surprised": "surprised",
    "terrified": "fearful",
    "trusting": "calm",
}

# GoEmotions label order in data/emotions.txt — train.tsv label ids are 0-indexed into this list.
GOEMOTIONS_LABEL_ORDER = [
    "admiration", "amusement", "anger", "annoyance", "approval", "caring", "confusion",
    "curiosity", "desire", "disappointment", "disapproval", "disgust", "embarrassment",
    "excitement", "fear", "gratitude", "grief", "joy", "love", "nervousness", "optimism",
    "pride", "realization", "relief", "remorse", "sadness", "surprise", "neutral",
]
