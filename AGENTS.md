# Project agent instructions

## Living project checklist

The authoritative implementation-status checklist is
[`docs/SDR_AGENT_PROJECT_CHECKLIST.md`](docs/SDR_AGENT_PROJECT_CHECKLIST.md).

All agents working in this repository must follow these rules:

1. Read the relevant checklist section before planning or changing a subsystem.
2. Update the checklist in the same change whenever a listed item is completed,
   invalidated, split into smaller work, or given a materially different scope.
3. Mark an item `- [x]` only after its stated completion condition has been
   implemented and verified. Code, design, mocks, or tests alone do not prove a
   live/deployed item unless the checklist wording explicitly says they do.
4. Keep an item `- [ ]` while any part of its wording remains incomplete. Split
   partially completed work into precise completed and incomplete child items
   instead of using an ambiguous partial-status symbol.
5. For hardware and deployment work, require live target validation before
   checking the item. Record the validation document, artifact hash, release,
   or test evidence when practical.
6. Do not mark future capability true in configuration merely to satisfy a
   checklist item. Runtime capability must come from the responsible Adapter or
   hardware probe and fail closed when unavailable.
7. Preserve completed historical items unless evidence shows a regression. If a
   regression occurs, uncheck the item and add a short note pointing to the
   failure evidence or follow-up task.
8. Before finishing a project change, review `git diff` and confirm the
   checklist accurately describes the resulting repository and deployed state.

Nested `AGENTS.md` files may add subsystem-specific instructions. The nearest
file to the changed code takes precedence when instructions differ.
