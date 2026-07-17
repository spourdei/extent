# Extent product language guide

Use this guide when adding or changing user-facing language in Extent. It defines how to write new copy, choose terms, distinguish evidence states, map technical failures, and review implementation.

For approved strings on existing routes, use [`product-messaging.md`](product-messaging.md). For behavior, trust the current implementation and API contracts over either document.

## 1. Product truth

Extent lets a user connect one Google Drive folder, ask questions across supported files, and inspect the exact source text behind each finding.

Extent must make three facts easy to see:

1. What evidence supports a finding.
2. When documents disagree or show a change.
3. When unavailable files prevent a firm answer.

Extent is an evidence navigator. It does not determine which document has legal or business authority. A quote proves that the source contains those words; it does not prove that the source is correct, current, complete, or controlling.

Do not claim capabilities, limits, permissions, security properties, supported formats, or reliability that the current code does not establish.

## 2. Audience and user job

Write for an analyst or operator comparing facts across a document packet. Assume the user:

- Understands folders, files, PDFs, Google Drive, quotes, pages, and lines.
- Does not need to understand ingestion, retrieval, embeddings, workers, queues, manifests, or publication policy.
- Wants the answer first, followed by the evidence and any limit on the answer.
- May be under time pressure.
- Will notice if the interface hides disagreement or turns incomplete coverage into certainty.

The user should be able to answer these questions without reading technical documentation:

- What is Extent doing?
- What did it find?
- Which files did it check?
- What exact words support this result?
- Did any source disagree?
- Were any files unavailable?
- What can I do next?

## 3. Voice

Extent is:

- Clear, not simplistic.
- Warm, not cute.
- Confident, not absolute.
- Concise, not abrupt.
- Honest about uncertainty.

### Voice in practice

| Situation             | Write like this                             | Avoid                                       |
| --------------------- | ------------------------------------------- | ------------------------------------------- |
| Normal task           | Direct and compact                          | Promotional or theatrical language          |
| Permission or consent | Specific and neutral                        | Reassurance without a concrete fact         |
| Progress              | Observable and current                      | Anthropomorphic “thinking” language         |
| Supported result      | Confident about the evidence                | Claims that the answer is correct           |
| Disagreement          | Neutral and symmetrical                     | Choosing a winner without evidence of order |
| Incomplete coverage   | Explicit about the missing files            | “Not found” or folder-wide certainty        |
| Error                 | Calm, useful, recovery-oriented             | Humor, blame, or raw diagnostics            |
| Sample                | Plainly disclosed as prepared and fictional | Language suggesting a live Drive connection |

## 4. Message order

Write interface copy in this order:

1. **Outcome:** What happened or what is true now.
2. **Evidence or limit:** Why Extent says it, or why it cannot say more.
3. **Next action:** What the user can do.
4. **Technical detail:** Only when it helps the user inspect, decide, recover, or contact support.

Good:

> We couldn't confirm this because some files weren't available. Extent searched the files it could read. Review the unavailable files.

Bad:

> Coverage validation failed because the retrieval pipeline encountered capped or inaccessible source states.

## 5. State distinctions that must remain separate

Never collapse the following states into one generic empty or error message.

### 5.1 Supported finding

Use when Extent has a finding tied to exact source text.

Pattern:

- Label: **Evidence found**
- Title: **Finding supported by the files**
- Explanation: **Extent found exact source text for this finding.**
- Action: **View the evidence**

Do not say:

- Verified answer
- Correct answer
- Confirmed fact
- Proven

### 5.2 Sources disagree

Use when two sources support different values and the available evidence does not establish an authoritative order.

Pattern:

- Label: **Sources disagree**
- Title: **These sources give different answers**
- Explanation: **Extent found support for both values and did not choose between them.**
- Comparison heading: **These sources disagree**

Good:

> One source lists USD 120,000. Another lists USD 132,750.

Bad:

> Extent detected a conflict and selected the likely correct value.

Keep both values, quotes, sources, and locators equally inspectable.

### 5.3 Change over time

Use when the documents establish an earlier and later state, revision, or effective sequence.

Pattern:

- Label: **Change found**
- Title: **The files show a change**
- Explanation: **Review the earlier and later values with their exact quotes.**

Do not call every difference a change. If order is unknown, use disagreement language.

### 5.4 Complete search with no supporting evidence

Use only when every admitted and available file was checked.

Pattern:

- Label: **Search complete**
- Title: **We couldn't find evidence for this.**
- Explanation: **Extent checked every available file in this folder and didn't find source text that supports an answer.**

This means Extent did not find supporting evidence. It does not mean the fact is false or that evidence cannot exist elsewhere.

Bad:

- No evidence exists.
- The folder proves this did not happen.
- Answer: no.

### 5.5 Incomplete coverage

Use when one or more relevant files could not be checked.

Pattern:

- Label: **No firm answer**
- Title: **We couldn't confirm this because some files weren't available.**
- Explanation: **Extent searched the files it could read. The unavailable files may still contain relevant evidence.**
- Boundary heading: **Files not checked**
- Action: **Review unavailable files**

Never replace this with “not found.” Name the blocking file when the interface can do so safely.

### 5.6 Relevant passages without a supported finding

Use when Extent found useful text but could not produce a supported finding.

Pattern:

- Label: **Relevant passages found**
- Title: **We found relevant passages, but not enough for a supported finding.**
- Explanation: **Review the passages below or make the question more specific.**

Do not hide the passages. Do not promote them to a finding.

### 5.7 Answer-generation failure with passages retained

Use when source search succeeded but answer generation failed.

Pattern:

- Label: **Answer unavailable**
- Title: **We couldn't finish the answer.**
- Explanation: **The relevant passages Extent found are still available below.**
- Action: **Try again**

Do not imply that file reading failed when it did not.

### 5.8 Clarification needed

Use when the question has more than one plausible interpretation and choosing one would be unsafe.

Pattern:

- Label: **Clarification needed**
- Title: **Extent needs a more specific question**
- Explanation: State the exact missing scope.

Good:

> Which premium do you mean: package, auto, or inland marine?

Bad:

> Your query is ambiguous. Please refine it.

Ask one concrete clarification. Do not provide a speculative answer before the user clarifies.

### 5.9 Exhaustive extraction

Use extraction language when the user asks for all matching values rather than one evidence-backed conclusion.

Pattern:

- Label: **Values extracted** or **Extraction complete**
- Title: **Found 4 matching values**
- Item label: **Extracted value**
- Action: **View the source**
- Inspector title: **Where Extent found it**

For incomplete coverage:

- Label: **Partial extraction**
- Title: **Found 4 matching values in a partial extraction**

Do not call each extracted value a finding. Extraction reports explicit matches; it does not reconcile authority or completeness when files are unavailable.

### 5.10 OCR-derived text

OCR text requires a visible verification cue.

Good:

> 12 pages · OCR text · verify against Drive

Good file failures:

- **OCR couldn't find readable text in this file**
- **Extent couldn't recognize the text in this PDF**
- **OCR took too long and can be retried**

Do not present OCR text as equivalent to native text without qualification. Keep the original Drive link available.

## 6. Terminology

Use one term for one concept. Repetition is better than synonym cycling.

| Concept                          | Preferred user-facing term                   | Keep technical term only when                                                       |
| -------------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------- |
| User-facing supported assertion  | Finding                                      | Writing code, API contracts, or evaluator-only audits that deliberately use `claim` |
| Material supporting a finding    | Evidence                                     | Distinguishing exact support from generated prose                                   |
| File or document behind evidence | Source                                       | Identifying where a finding came from                                               |
| Exact source text                | Exact quote                                  | Showing the precise words used                                                      |
| Stored source segment            | Excerpt or passage                           | Explaining reviewable text; never expose “source block”                             |
| Preparing source content         | Reading your files                           | The technical implementation itself is under discussion                             |
| Finding candidate material       | Looking through your sources                 | Writing internal retrieval code or logs                                             |
| Evidence checks                  | Checking the evidence or checking the quotes | Evaluator-only technical disclosure needs the exact check name                      |
| Different supported answers      | Sources disagree                             | The internal relation value remains `conflict`                                      |
| Ordered difference               | Change found                                 | The internal relation value remains `change`                                        |
| No supported text found          | We couldn't find evidence for this           | Never rewrite as proof of absence                                                   |
| Incomplete search                | Some files weren't available                 | Preserve the specific blocking reason when useful                                   |
| Unsupported format               | Extent can't read this file type yet         | Referring to an API status or schema enum                                           |
| Old capped run                   | Not processed in this earlier workspace run  | Referring to the durable `capped` status internally                                 |
| Timestamp for ready files        | Files ready at                               | The data has a different documented meaning                                         |
| Timestamp for observed source    | Seen by Extent                               | Writing internal provenance code                                                    |
| Ingestion                        | Reading your files or preparing your folder  | Never in ordinary interface copy                                                    |
| Parsing                          | Reading this file                            | Never in ordinary interface copy                                                    |
| Embedding or vector              | Preparing this file for search               | Never in ordinary interface copy                                                    |
| Pipeline                         | Name the current user-visible stage          | Never in ordinary interface copy                                                    |
| Manifest or projection           | Name the folder, files, or result            | Never in ordinary interface copy                                                    |
| Lineage or provenance            | Where this came from                         | Technical audit or code only                                                        |
| Publication                      | Showing a finding                            | Technical audit or code only                                                        |

### Terms worth preserving

Use these technical terms when they improve comprehension:

- Google Drive
- Read-only access
- PDF
- OCR
- File type
- Source
- Evidence
- Exact quote
- Page
- Line
- Source version

## 7. Naming the actor

### Use “Extent” when identity or responsibility matters

Good:

- **Extent checked every available file.**
- **Extent cannot change your files in Drive.**
- **Extent found support for both values.**

### Use “we” sparingly for immediate system outcomes

Good:

- **We couldn't finish the answer.**
- **We couldn't find evidence for this.**

Do not alternate between “Extent” and “we” in one short message unless the distinction adds meaning.

### Use “you” for actions and consequences

Good:

- **You can review the relevant passages below.**
- **Your folder link is still here, so you can try again.**

Do not blame the user.

Bad:

- You entered an invalid folder.
- You failed to connect Google Drive.

Good:

- Paste a Google Drive folder link.
- Google Drive wasn't connected.

## 8. Headings, labels, and supporting text

### Headings

Headings should name the task, outcome, or limit.

Good:

- **Choose what Extent can read.**
- **Reading your files**
- **These sources give different answers**
- **Files not checked**

Avoid headings that are decorative, clever, or incomplete.

Bad:

- Unlock the truth in your documents
- Your evidence journey starts here
- Something went wrong
- Evidence, reimagined

### Status labels

Status labels are short noun phrases or completed outcomes. They should scan independently from the title.

Good:

- Evidence found
- Sources disagree
- No firm answer
- Partial extraction
- Clarification needed

Avoid internal stages and vague sentiment.

Bad:

- Validation passed
- Pipeline complete
- Success
- Warning

### Supporting text

Supporting text should add a reason, boundary, or next step. Do not repeat the heading.

Bad:

> **Reading your files**  
> Extent is reading your files.

Good:

> **Reading your files**  
> Extent is keeping the page or line location for each searchable excerpt.

## 9. Buttons and links

Use short, action-led labels that describe the actual next step.

| Purpose            | Good                         | Avoid                |
| ------------------ | ---------------------------- | -------------------- |
| Connect provider   | Connect Google Drive         | Continue with Google |
| Admit folder       | Check this folder            | Submit               |
| Ask question       | Ask about these files        | Ask Extent           |
| Inspect finding    | View the evidence            | Why this value?      |
| Inspect extraction | View the source              | View the evidence    |
| Open original      | Open in Drive                | Learn more           |
| Retry question     | Try again                    | Retry operation      |
| Retry folder       | Try reading the folder again | Retry ingestion      |
| Change scope       | Choose another folder        | Go back              |
| Inspect gaps       | Review unavailable files     | More details         |

Rules:

- Prefer verb + object.
- Keep destructive actions explicit.
- Do not use **Submit**, **Continue**, **OK**, **Yes**, **Click here**, **Get started**, or **Learn more** when a specific action is available.
- Give repeated controls distinct accessible names when their visible labels are identical.
- Use an ellipsis only when the action opens another step or the operation is currently in progress. Use the single ellipsis character: `…`.

## 10. Forms

### Labels

Labels must work without placeholders.

Good:

- **Google Drive folder link**
- **Question about this folder**

Bad:

- Link
- Question
- Enter value

### Placeholders

Use placeholders for examples, not instructions.

Good:

> What is the total premium for the complete package?

Bad:

> Ask anything

### Helper text

Helper text should explain a boundary the label cannot.

Good:

> The link chooses the folder. Your connected Google account still controls which files Extent can open.

Bad:

> Paste your link above.

### Validation errors

Name the required format and show an example when useful.

Good:

> Paste a Google Drive folder link, such as `https://drive.google.com/drive/folders/...`

Bad:

> Invalid URL.

Preserve the user's input after every failed submission. Clear it only after success when the submitted value remains visible in the resulting interface.

## 11. Loading and progress

Describe observable work. Do not call ordinary processing “thinking.”

Good progression:

- Saving your folder
- Finding files
- Reading your files
- Looking through your sources…
- Checking the evidence

Bad progression:

- Initializing pipeline
- Running ingestion
- Retrieving context
- Thinking deeply
- Validating citations

Rules:

- Use present progressive language for current work.
- Do not promise time estimates without measured evidence.
- Do not say all files are ready until the state proves it.
- Do not claim the whole folder was searched when coverage is incomplete.
- Keep live-region announcements shorter than visible progress detail.

Good visible copy:

> Extent is reading supported files and keeping page or line locations.

Good live-region copy:

> Looking through your sources and checking the evidence.

## 12. Errors and recovery

Use this sequence:

1. State what Extent could not do.
2. Preserve any useful boundary or retained work.
3. Give a real next action.
4. Show a support reference only when one exists.

### Error patterns

| Situation          | Good pattern                                                                                 |
| ------------------ | -------------------------------------------------------------------------------------------- |
| Network            | **Extent couldn't reach the server. Your question is still here, so you can try again.**     |
| Authentication     | **Connect the Google account that can open this workspace, then try again.**                 |
| Permission         | **The connected account can't open this file.**                                              |
| Provider delay     | **Google Drive asked Extent to wait.**                                                       |
| Malformed response | **Extent received an unexpected result. Your question is still here, so you can try again.** |
| Unsupported format | **Extent can't read this file type yet.**                                                    |
| PDF parse          | **Extent couldn't read this PDF.**                                                           |
| Encrypted PDF      | **Password-protected PDF**                                                                   |
| OCR unavailable    | **OCR is not available on this worker.**                                                     |
| Retry exhausted    | **Extent still couldn't read this file after retrying.**                                     |

Avoid:

- Raw HTTP status text
- Provider response bodies
- Exception names
- Endpoint paths
- Queue, worker, parser, embedding, or database language
- “Something went wrong” when the interface knows more
- Apologies that displace useful information
- Humor

Map stable backend error codes to frontend copy. Do not parse unpredictable provider messages to create user-facing text.

## 13. Google Drive access and consent

Permission copy must name the implemented property and its consequence.

Good:

- **Extent asks for read-only Drive access so it can open the folder link you provide.**
- **Extent cannot change your files in Drive.**
- **The folder link sets the boundary. It does not grant access by itself.**

Avoid:

- Your data is completely secure.
- Extent is private.
- Connect safely.
- We only access what you need.

Use **secure**, **private**, **encrypted**, **isolated**, or **deleted** only when the exact implemented property is documented and relevant at that moment.

## 14. Evidence inspector

An evidence inspector should answer, in order:

1. What does the finding or extracted value say?
2. Which source supports it?
3. What are the exact words?
4. Where are those words?
5. When did Extent observe the source?
6. Can the user open the original?
7. Is there another source that disagrees or shows a change?

Preferred labels:

- Why Extent says this
- Where Extent found it
- Exact quote
- From this file
- Page 4
- Lines 18–24
- Source version
- Seen by Extent
- Open in Drive
- These sources disagree
- Earlier evidence
- Later evidence

Avoid:

- Explainability
- Model reasoning
- Provenance graph
- Claim lineage
- Canonicalized output
- Citation verification

Never show chain-of-thought or imply that generated reasoning is evidence. The inspector shows source text and source metadata.

## 15. Sample language

The public sample must remain visibly prepared and fictional.

Required ideas:

- The documents are prepared.
- The documents are fictional.
- Visitors can ask questions without connecting Google Drive.
- The sample is not connected to Google Drive.

Good:

> This public sample uses a prepared fictional renewal packet. Ask questions without signing in or connecting Google Drive.

Avoid:

- Live workspace
- Your folder
- Your Google Drive folder
- Real customer documents

The disclosure must be visible near the sample's primary content. Do not rely on metadata or a footer alone.

## 16. Accessibility language

### Accessible names

Controls must make sense out of context.

Good:

- **View evidence for the annual package premium, USD 132,750**
- **View source for the inland marine premium, USD 4,635**
- **Close evidence**

Bad:

- More
- Open
- Details
- Close, when several unrelated panels are present and context is unclear

### Live regions

- Announce one current status.
- Do not repeat the same message through multiple live regions.
- Announce the outcome, not every internal stage.
- Keep counts grammatical.

Good:

- **1 finding ready.**
- **3 findings ready.**
- **Partial extraction. 4 matching values were found in the available files.**
- **No firm answer. Some files weren't available to check.**

### Meaning without color

State labels must carry the meaning expressed by warning, evidence, or neutral colors. Never rely on color alone to distinguish disagreement, incomplete coverage, or success.

## 17. Grammar and mechanics

- Use sentence case for headings, labels, and buttons.
- Use contractions where they sound natural: **couldn't**, **wasn't**, **can't**.
- Use active voice when the actor matters.
- Prefer **is**, **has**, **found**, **checked**, **read**, **show**, and **open** over abstract noun phrases.
- Use the serial comma only when it prevents ambiguity; do not force three-item lists.
- Avoid exclamation marks in ordinary success, evidence, permission, and error states.
- Avoid rhetorical questions in consent and failure states.
- Avoid semicolons in interface copy.
- Avoid em and en dashes in authored interface copy. Use a period, comma, colon, or parentheses. Preserve dashes inside exact source text and proper names.
- Use numerals for counts: **8 files**, **Page 4**, **Lines 18–24**.
- Use locale-aware formatting for user-visible dates, times, and numbers.
- Do not add a period to a button or short status label.
- Use one full sentence per translatable string when possible.

## 18. Natural rhythm without performance

Natural language is not casual filler. Remove:

- Let's dive in
- Here's the thing
- Great news
- You're all set
- Ready to unlock insights?
- We know how frustrating this is
- Your AI teammate

Avoid formulaic constructions:

- It's not just X, it's Y.
- From X to Y, Extent transforms Z.
- Whether you're doing X, Y, or Z…
- Powerful, seamless, actionable insights.

Prefer concrete statements:

Bad:

> Extent empowers teams to unlock actionable insights from complex document ecosystems.

Good:

> Ask a question across one folder and inspect the exact quote behind each finding.

## 19. Words that require scrutiny

Do not ban words mechanically. Reject them when they hide a fact, overstate a property, or substitute promotion for explanation.

Usually remove from interface copy:

- AI-powered
- Actionable insights
- Effortless
- Intelligent
- Leverage
- Magic
- Powerful
- Revolutionary
- Robust
- Seamless
- Transformative
- Unlock
- Instant
- Real time
- Always
- Never
- Any file
- Ask anything
- Verified

Accept a word only when the current implementation proves the specific meaning and the user needs it to decide or recover.

## 20. Protect exact and contractual text

Do not rewrite:

- Exact document quotes
- Source file names
- User questions stored as evidence history
- Values extracted from sources
- Page or line locators
- Google product names
- Stable API field names
- Enum values
- Error codes
- Test IDs
- Analytics identifiers
- Environment variables
- Fixture content representing source documents

Change the surrounding label or mapping instead.

Good:

```ts
const labels: Record<CoverageGap, string> = {
  inaccessible: "The connected account could not open at least one file.",
  unsupported: "Extent can't read at least one file type in this folder yet.",
};
```

Bad:

```ts
if (providerMessage.includes("permission")) {
  return providerMessage;
}
```

## 21. Responsive and localization constraints

- Keep primary buttons short enough for 390 px layouts and 200% zoom.
- Do not shorten a clear label into jargon to make it fit. Adjust layout first.
- Assume translated text may expand by 30%.
- Keep variables out of the middle of fragmented sentences when possible.
- Use grammatical singular and plural forms.
- Avoid idioms, puns, and culture-specific metaphors.
- Keep numbers and nouns together in accessible announcements.
- Do not use placeholders as labels; placeholders disappear and may truncate.

Good:

```ts
`${count} ${count === 1 ? "finding" : "findings"} ready.`;
```

Avoid assembling a sentence from many independently translated fragments.

## 22. Implementation rules

### Keep copy local when

- It appears once.
- Its meaning depends on one component's local state.
- Centralization would obscure the state logic.

### Centralize copy when

- The same user-facing state appears in several surfaces.
- Several backend codes map to one intentional recovery message.
- A terminology change must remain synchronized.

### Derive copy from typed state when

- Completeness changes the meaning of “not found.”
- A relation distinguishes fact, change, disagreement, or review needed.
- Counts affect grammar.
- Extraction and ordinary findings use different vocabulary.
- OCR requires a verification notice.

Do not create a giant global string object. Keep the smallest structure that prevents inconsistency.

### Backend messages

- Prefer stable code-to-copy mappings.
- Use a generic safe fallback for unknown codes.
- Never expose provider payloads.
- Do not infer meaning from unpredictable free-form strings.
- Keep internal identifiers unchanged when changing visible labels.

## 23. Test expectations

Add or update focused tests when copy carries product truth, recovery behavior, or an accessible name.

Test at least these distinctions when affected:

- Complete search with no evidence
- Incomplete coverage
- Source disagreement
- Ordered change
- Relevant passages without a finding
- Unsupported file type
- OCR-derived text and OCR failure
- Generic server failure and retry
- Clarification request
- Complete and partial extraction
- Prepared sample disclosure
- Progress live-region announcement
- Preserved input after failure
- Cleared input after success, when applicable
- Changed button or dialog accessible names

Do not weaken a semantic assertion into a generic substring check merely because copy changed. Update the expected product truth.

## 24. Review procedure

Before merging product-language changes:

1. Identify the exact state and whether coverage is complete.
2. Confirm the copy does not exceed current behavior.
3. Compare terminology with this guide and `product-messaging.md`.
4. Search the frontend for old and conflicting terms.
5. Verify exact quotes and fixture evidence are unchanged.
6. Verify backend codes and API contracts are unchanged unless the task explicitly changes them.
7. Read the screen in this order: label, heading, explanation, action.
8. Remove repeated information.
9. Read the final copy aloud. Remove stiffness, slogans, filler, and accidental cleverness.
10. Check 390 px, 200% zoom, keyboard navigation, focus behavior, and live-region output.
11. Run formatting, lint, strict type checks, focused tests, and the production build.

### Final copy checklist

- [ ] The user can tell what happened.
- [ ] The user can tell what Extent checked.
- [ ] The user can tell whether files were unavailable.
- [ ] Disagreement and change are not conflated.
- [ ] “Not found” does not become “does not exist.”
- [ ] A supported finding is not called correct or verified.
- [ ] The next action is specific and real.
- [ ] No internal pipeline term is exposed without a user need.
- [ ] Exact evidence and locators are unchanged.
- [ ] The sample remains prepared and fictional.
- [ ] Buttons make sense out of context.
- [ ] Live-region text is short and truthful.
- [ ] Copy fits narrow and zoomed layouts.
- [ ] Error input is preserved when recovery requires editing or retrying.

## 25. Pattern library

Use these as structures, not as automatic replacements.

### Connect

> **Choose what Extent can read.**  
> Extent asks for read-only Drive access so it can open the folder link you provide.

### Folder helper

> The link chooses the folder. Your connected Google account still controls which files Extent can open.

### File preparation

> **Reading your files**  
> Extent is reading supported files and keeping page or line locations.

### Complete supported answer

> **Finding supported by the files**  
> Extent found exact source text for this finding.

### Disagreement

> **These sources give different answers**  
> Extent found support for both values and did not choose between them.

### Change

> **The files show a change**  
> Review the earlier and later values with their exact quotes.

### Complete no-evidence result

> **We couldn't find evidence for this.**  
> Extent checked every available file in this folder and didn't find source text that supports an answer.

### Incomplete result

> **We couldn't confirm this because some files weren't available.**  
> Extent searched the files it could read. The unavailable files may still contain relevant evidence.

### Passages only

> **We found relevant passages, but not enough for a supported finding.**  
> Review the passages below or make the question more specific.

### Clarification

> **Extent needs a more specific question**  
> Which premium do you mean: package, auto, or inland marine?

### Complete extraction

> **Found 4 matching values**  
> Review each value with its exact matching passage and source location.

### Partial extraction

> **Found 4 matching values in a partial extraction**  
> Some files weren't available, so this list may not include every matching value in the folder.

### Question failure

> **Extent couldn't finish this question.**  
> Your text is still here, so you can try again.

### File failure

> **Extent couldn't read this PDF.**  
> Try reading the folder again. If the file still fails, open it in Drive and check that it contains readable text.

### Sample disclosure

> This public sample uses a prepared fictional renewal packet. Ask questions without signing in or connecting Google Drive.
