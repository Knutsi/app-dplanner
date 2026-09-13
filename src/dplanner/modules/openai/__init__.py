"""OpenAI as a vendor module: one account, one key in the keychain, and every provider
kind DPlanner runs on it — the LLM provider, the settings page and the *Add API key…*
wizard. The transcription providers in ``dictation.py`` run on the same key.

The package shares its name with the vendor's SDK on purpose — it *is* the OpenAI module
— and the two never meet: ``import openai`` inside it is the SDK, because absolute imports
resolve from the top, and this package is only ever ``dplanner.modules.openai``. The stored
id stays ``llm_openai``: the keychain entry and the settings under it are a contract with
every machine that already has them.
"""
