# Written instructions and independent workspace panels

## Describe the activity in your own words

Under **What should players do?**, choose **Describe it in my own words…**.
The preset menu remains available, and switching back to a preset does not apply
text left in the hidden instruction field.

Examples:

- `Make 3 hard multiple-choice puzzles. Players should solve a set of clues.`
- `Create a crossword about plants and animals.`
- `Unscramble a word. Include topics: space, ocean.`
- `Choose the best next question. Use typed answers.`
- `Build a logic grid.` Then enter groups and rules in the displayed grid controls.
- `Design a clue puzzle for me.` Then choose topics and level; BrainBloom supplies the groups
  and clues automatically.
- `Find the impossible clue.`
- `Choose the most likely explanation.`
- `Plan the best next move.`
- `Discover a number rule.`

The **How I understand this** panel shows the interpreted activity and settings.
If the text changes topics, answer format, count or level, generation waits for
**Apply these settings**. Applying updates the visible form. The system then checks
topic meanings, capacity and activity compatibility as usual. Editing a form field
that conflicts with an explicit written instruction requires resolving that conflict.

`About ...` or `Topics: ...` specifies a topic list. `Include topics: ...`,
`Include words: ...` or `Use keywords: ...` adds to existing topics. Topic clauses
end at a full stop, semicolon or line break. All selected topics are retained under
the existing per-topic meaning and coverage rules.

## What this understands

The implementation is a deterministic, versioned phrase grammar:

- The existing activity names and selected common alternatives, such as
  “rearrange letters”, “weigh the evidence” and “find the next number”.
- A puzzle count from 1 to 20, including English number words in supported phrases.
- Easy/simple/beginner, medium/moderate, hard/challenging/advanced.
- Multiple-choice, true/false, typed answers, crossword, riddle and Wonder formats.
- Explicit topic lists introduced by the phrases above.

It is **not unrestricted natural-language understanding or a trained language model**.
Every content word outside recognised phrases and grammatical filler must be
accounted for. Negation, conflicting activities/settings, unsupported constraints,
unrecognised topics and incomplete instructions block generation with feedback.

Examples needing clarification:

- `Unscramble words without vowels.`
- `Place TIGER before LION.`
- `Always make the answer TIGER.`
- `Create a timed crossword for five year olds.`

These constraints are not implemented by silently mapping to the nearest preset.
For ordering constraints, choose **Create a custom logic grid** and enter supported
rules such as `Tiger is before Lion` in **Your rules**, rather than the general activity
instruction field. See [custom grids](brainbloom-workshop-flow.md#custom-rules-and-logic-grids).
A topic clause also cannot conceal requirements such as `about animals without
vowels`; extra requirements must be separate sentences so the parser can check them.
For unusual topic phrases, the existing Topics field remains available directly.

The text limit is 1,000 characters. No code is executed from the text. No model,
external endpoint, training run or API key is used.

## Engine and export behaviour

`Brief` accepts `activity: "custom"` and `instructions: "..."` through
`POST /api/prepare`. The response includes an `instruction` report:

- `clarify`: unsupported words or conflicting instructions; no generation request.
- `apply`: recognised instructions change form values; `changes` lists those values.
- `supported`: settings agree; normal topic/activity checks still need to pass.

Example request:

```json
{
  "activity": "custom",
  "instructions": "Make 3 hard multiple-choice puzzles. Players should solve a set of clues.",
  "subject": "space, ocean",
  "category": "logic",
  "qtype": "multiple-choice",
  "difficulty": "medium",
  "count": 1
}
```

This returns changes for count and difficulty. The client applies them and prepares
again before submitting the validated engine request to `/api/generate`.

The original instruction text is saved in the exported `request.instructions`.
Each proof includes the versioned `instruction_interpretation`. Generation and
replay check the text against the actual engine family, variation, topic list,
count, level and format. Sending a conflicting raw `/api/generate` request does
not bypass this check. Existing bundles without instructions remain replayable.

## Scrolling and navigation

On desktop, the viewport contains two independently scrolling panes:

- **Setup:** fields scroll inside the panel; Generate and Make another version
  remain in the fixed bottom action bar.
- **Drafts:** cards scroll inside the panel; title, status and Download remain visible.

Starting generation brings the drafts panel into view and announces progress.
When results arrive, the draft scroll position resets to the top and the status
receives focus without moving the setup scroll position. Errors after generation
starts are also visible in the draft status area.

At widths up to 760px, Setup/Drafts tabs show one full-width panel at a time.
Generation switches to Drafts automatically. Returning to Setup preserves fields,
instructions and its scroll position. Tabs support arrow keys and Home/End; the
panels have accessible labels and keyboard-focusable scroll roots.

The short-viewport layout hides the decorative intro to leave room for controls.
The app uses dynamic viewport height for mobile browsers and contains overscroll
within each content pane.

## Verification

`tests/test_brainbloom_instructions.py` covers supported examples, activity names,
conflicts, unsupported constraints, explicit apply, included/replaced topics,
direct-request checks and export replay. Existing workshop tests remain in place.

The jsdom interaction test (`tests/brainbloom_flow.cjs`) exercises the actual UI code
against the local server. It checks instruction editing/application, generated
exports, separate scroll roots, automatic result visibility, preserved setup state,
small-screen tab behaviour and keyboard navigation. This is a DOM/interaction test,
not a substitute for pixel-level testing in every browser.
