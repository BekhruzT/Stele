> Superseded progress: the prompt simplification, separate listener/fact checks,
> and live six-topic reruns below have now been carried out. Read the
> [prompt reevaluation](prompt-reevaluation.md) and `six-case-review-v5.json` for
> actual results and remaining failures. The original plan is retained below.

# What the experiment changes next

The dataset and six-case experiment are complete. Hook quality is not solved.
My editorial assessment would not replace an approved reference with any of the
new selected hooks. Both selectors passed all six, which exposes their inability
to distinguish an accurate opening from this user's desired opening.

1. **Separate the video's promise from the first scene.** The promise should say
   what the discovery or event means to a general listener. Exile, correspondence,
   an apparatus, or a clock trial can then introduce the story. A model currently
   chooses an interesting scene and justifies it as the promise afterward.
2. **Distill, rather than imitate, the source passages.** These 45 quotations
   average roughly 85 words. Many earn interest only after setup. Supplying them
   all produces useful patterns but also teaches the model to summarize scenes
   and introduce detours. A next controlled trial should keep all references
   available while distinguishing concise first-line exemplars from longer
   passages whose construction alone is useful.
3. **Fix selection before another body regeneration.** Assess the promise and
   listener reference point independently of factual correctness. Keep the exact
   rejected examples in calibration, and use unseen cases and blind comparisons
   before claiming generalization. A different evaluator model is worth testing,
   but changing the model is not itself evidence of improvement.
4. **Repair the Silk Roads research.** The existing letters support a narrow
   account of trade and uncertainty, not the broad consequence the current title
   invites. Add a documented connected outcome, with dates and source evidence,
   before asking for a grander claim.
5. **Keep the four approved hooks.** Harrison still needs a consequence-first
   opening. The current science and Musa references remain the better editorial
   target. No full transcript rewrite is warranted by these hook trials.

For a fair follow-up, predefine the rubric and hold the topic evidence, model,
and output format constant. Compare the old prompt, examples alone, and the
calibrated prompt on a broader set of topics. The two trials here changed both
instructions and examples; they do not isolate the value of the corpus.
