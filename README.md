# Door Window Knowledge Base

This repository is a versioned backup of the local door-and-window presales knowledge base.

- Entries: 10
- Main data: `knowledge_base.json`
- Human-readable entries: `entries/`
- Images and screenshots: `assets/`
- Tables: `tables/`
- Pending learning queue: `learning_queue.json`
- Conversation sessions: `conversations.json`
- Floating app state: `floating_state.json`
- Interaction logs: `interactions.jsonl`
- Distillation dataset: `interactions_distill.jsonl`
- Version manifest: `version.json`

Update flow:

1. Edit or import data in the local trainer.
2. Run `PYTHONPATH=src python3 kb_github_backup.py export`.
3. Review `git status` in this folder.
4. Push to GitHub after confirming the remote repository.
