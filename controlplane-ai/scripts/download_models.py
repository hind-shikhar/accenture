from transformers import pipeline

print("Downloading protectai/deberta-v3-base-prompt-injection...")
pipeline("text-classification", model="protectai/deberta-v3-base-prompt-injection")

print("Downloading martin-ha/toxic-comment-model...")
pipeline("text-classification", model="martin-ha/toxic-comment-model")

print("All models downloaded and cached successfully!")
