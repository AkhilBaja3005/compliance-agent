from transformers import AutoModelForCausalLM


def load():
    return AutoModelForCausalLM.from_pretrained("voxgen/voice-lm-7b")
