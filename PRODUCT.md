# Product notes

## Working direction

Extent is a web workspace for asking questions across one connected Google Drive folder.

The user chooses the folder. Drive access stays read-only, and the connected account still
determines which files can be opened.

## Core loop

1. Connect Google Drive and provide a folder link.
2. Wait while Extent discovers and prepares supported files.
3. Ask a question across the prepared material.
4. Read a short answer and inspect the exact excerpts behind it.

Answers should cite source text and a useful location, such as a PDF page or text line.
Evidence needs to remain inspectable after the answer is produced.

Do not present an unsupported claim as fact. If the available excerpts do not support a
material statement, suppress it or explain the limit. A citation by itself does not prove
that a value is current or controlling.

## Preparation

Folder preparation may take time. Show what is still being read, what is ready, and what
failed. A partially prepared folder should not look complete.

The first useful release can focus on one folder per workspace and bounded answers. It does
not need a general-purpose chat surface.

## Open questions

- How should conflicts between plausible source values appear?
- What counts as enough coverage to say that no answer exists?
- Which file types can preserve stable evidence locations in the first release?
- When should a broad question ask for clarification instead of searching?
- How much prior question context should affect a follow-up?

Keep these decisions close to retrieval and publication behavior. The interface should say
what the system actually checked, not what a fluent answer implies.
