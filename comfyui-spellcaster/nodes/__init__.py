"""Spellcaster ComfyUI Custom Nodes

This directory contains the custom node implementations for the Spellcaster
node pack. Individual nodes are registered in the parent __init__.py.

Node modules:
  - loader.py       : SpellcasterLoader (auto-detect architecture, load model stack)
  - prompt.py       : SpellcasterPromptEnhance (LLM-powered prompt enhancement)
  - sampler.py      : SpellcasterSampler (architecture-aware sampling)
  - output.py       : SpellcasterOutput (VAE decode + privacy-aware save)
"""

# Nodes are registered in the parent package __init__.py
