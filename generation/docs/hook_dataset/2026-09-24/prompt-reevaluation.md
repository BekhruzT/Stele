# Prompt reevaluation — 24 September 2026

The 45 published reference passages remain unchanged. The active prompt is
`reference-editorial-v5.2-prose-first`. The six topics were rerun through the
production hook path. This work improves some candidates and makes rejection
more honest; it does not establish that the pipeline consistently matches the
approved references.

## What was wrong

The old prompt surrounded every reference with analysis and warnings, repeated
its first sentence, and asked the writer to produce source IDs, a justification,
and a factual-risk note alongside each hook. Its brief also selected a scene
before the opening was written. The result repeatedly sounded like a defended
summary of the source packet. The selector received the research and the
writer's defense, so it could infer meaning absent from the spoken words.

Shortening that prompt alone did not solve the problem. Nor did swapping to
Opus or adding approved examples from other topics. The more useful change was
to let the writer return only spoken prose and move evidence annotation to a
separate stage.

## Implemented behavior

- All 45 complete quotations remain in writing and listener prompts. Audit
  commentary, duplicated first sentences and per-example warnings stay in the
  research viewer rather than overwhelming the quoted writing.
- The brief checks evidence sufficiency; it no longer anchors the writer on an
  angle or scene. The writer produces five one- or two-sentence invitations,
  with no self-evaluation or citations in its output schema.
- The listener reviewer receives ONLY candidate wording and the 45 references.
  It cannot see the working title, research, brief, previous reviews or writer
  rationales. It ranks options and checks the meaning actually heard.
- A separate reviewer supplies research IDs and checks factual support and
  whether the story can deliver its promise. Code requires both reviews to pass.
  Repairs use the same separation. Two failed pools block narration.
- The listener prompt retains this user's explicit rejections, including
  unexplained distances, delayed trade correspondence, source-led attribution,
  apparatus-led discovery hooks and technical abstractions without significance.
- The experiment runner can replay completed, byte-identical requests from an
  explicitly named prior run. Changed prompts or inputs call the API. Cached
  calls preserve their origin and record zero new usage.

The four approved production hooks remain locked. No target approved hook or
reference transcript was passed into the final fresh writing calls. Full
transcript bodies were not regenerated in this hook-only task.

## Experiments and limits

Writer-only artifacts are under
`artifacts/youtube-hooks-20260924/prompt-reevaluation/`.

| Trial | Observation |
| --- | --- |
| direct-reference-v1 | Cleaner examples, unchanged research and Astra; often produced a whole introductory paragraph. |
| direct-reference-v2 | Shorter invitation; still chose routine mechanisms and biographical incidents. |
| direct-reference-v2-opus | Same writer prompt with Opus 5.5; did not reliably improve the premise and introduced several overclaims. Not adopted. |
| direct-reference-v3-held-out | Other topics' approved hooks reduced verbosity but did not reliably fix the premise. The target's approved entry was excluded. Not adopted as the production context. |
| direct-reference-v4-copywriter | Prose-only output produced stronger practical stakes and clearer discovery consequences. Basis of the final writer prompt. |
| 20260924-listener-first-v5 | First full production test of separate listener and factual reviews; five passes and one rejection. Several passes remained editorially weak. |
| 20260924-prose-first-v5-1 | Prose-only writer plus a sourced fission context note; the reviewer still accepted known rejected patterns. |
| 20260924-prose-first-v5-2 | Explicit listener preference constraints; four model passes, two rejected pools. Automatic selection still makes poor choices for some topics. |

These are iterative development trials on six known topics, not a controlled or
held-out estimate of general audience appeal. The model remains GPT-6 Astra at
medium reasoning in production. A model pass is not an editorial endorsement.

The last run reused 18 identical calls and made 15 new calls. The raw-request
boundary audit is saved in `final-request-audit.json` beside the experiments.

## Evidence change

Meitner received one appended research note from the U.S. Department of Energy,
[Fission and Fusion: What is the Difference?](https://www.energy.gov/ne/articles/fission-and-fusion-what-difference).
It explicitly connects fission with reactor heat, steam and electricity. The
biographical source packet previously left this familiar consequence largely
unstated. This is an evidence change, not an effect attributed to prompting.
The fetched page, extracted text and provenance are cached in
`artifacts/youtube-hooks-20260924/prompt-reevaluation/context-evidence/`.
The other five research collections are unchanged.

## Review and remaining work

`six-case-review-v5.json` contains the assessment of the actual final wording.
`latest-evaluation.json` selects the run displayed in the HTML review. Four
assistant picks are verbatim generated candidates, with their exact run and
candidate index shown. They are editorial choices, not necessarily the model's
choice and not new user-approved goldens. Musa's strongest new candidate is
from v5.0; the final automatic selection regressed and is shown separately.
Bell and Silk Roads have no recommended new opening.

The next substantive work is on promise selection: Bell needs the successful
theory and the meaning of completeness made accessible before technical tests;
Silk Roads needs evidence of a consequential exchange or a deliberately narrower
video scope. Adding more writing rules does not supply either missing premise.
Automatic selection also needs to distinguish a good first line from a weak
follow-up anecdote. The existing approved hooks should stay in production.

27 offline editorial/replay tests passed. The viewer self-test, Python compilation,
raw-request isolation audit and generated HTML JavaScript syntax check passed.
These checks validate mechanics only. No browser visual verification was done:
the local page had been blocked by browser URL policy earlier in the task.
