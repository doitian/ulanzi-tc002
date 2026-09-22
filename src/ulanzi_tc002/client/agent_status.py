def summarize_counts(counts):
    kind = next((kind for kind in ("waiting", "running", "done") if counts[kind]), "idle")
    return kind, counts[kind], counts
