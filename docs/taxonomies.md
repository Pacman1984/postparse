# Taxonomies and classification

A **taxonomy** is a named set of labels that an LLM assigns to items. PostParse
has one generic classification workflow for all taxonomies; there are no
hard-coded classifiers any more. Results are stored per run, so you can change a
taxonomy, re-classify, and still see what an older label set said.

## Defining a taxonomy

Add one `[[classification.taxonomies]]` table per taxonomy to `config.toml`:

```toml
[classification]
max_input_chars = 8000             # composed input per item is cut to this length

[[classification.taxonomies]]
name = "topics"                    # unique name, also stored in the database
mode = "multi"                     # "multi": 0..N labels, "single": exactly one label
max_labels = 3                     # optional, multi only
sources = []                       # optional: ["instagram"] or ["telegram"]; empty = all
instructions = "Posts are mostly German."   # optional, appended to the system prompt
labels = [
    { name = "recipe", description = "Cooking or baking instructions, ingredient lists" },
    { name = "travel", description = "Places, trips, hotels, restaurants or sights" },
    { name = "tech",   description = "Software, programming, gadgets, AI tools" },
]
```

Rules (validated by `postparse config validate` and on load):

* `name` is required and unique; `mode` is `single` or `multi` (default `multi`).
* At least one label; a `single` taxonomy needs at least two. Label names must
  be unique.
* `max_labels` (>= 1) is only allowed for `multi`.
* `sources` may contain `instagram` and `telegram`. A taxonomy restricted to one
  source only classifies items of that source; asking for another source is an
  error.
* `labels` may also be written as a table `{ recipe = "Cooking ...", tech = "..." }`
  or as plain names (`labels = ["recipe", "tech"]`), but descriptions are
  strongly recommended.

**Write good label descriptions.** The system prompt lists every label as
`- name: description`; the description is the only thing the model knows about
a label. Say what belongs to it, ideally with examples, and how it differs from
neighbouring labels.

Backward compatibility: without any `[[classification.taxonomies]]`, a legacy
`[[classification.classes]]` list (`name` + `description`) becomes the multi-label
taxonomy `topics`.

List configured and stored taxonomies with versions and result counts:

```bash
postparse classify taxonomies
postparse classify taxonomies --output json
```

## What the model sees

For each item, `ClassificationService` composes one input from labelled sections:
the caption/message text, the video transcripts, the latest summary, the texts of
fetched links (each link capped at a quarter of the budget) and the legacy v1
expanded text. The whole input is cut to `classification.max_input_chars`
(default 8000).

By default `classify run` **waits for transcripts**: items with a video whose
transcription is still pending are skipped, so they are classified once the
transcript exists. `--no-wait-transcripts` (API: `wait_for_transcripts: false`)
classifies them anyway.

The output is structured (pydantic-ai): one label (`single`) or a list of labels
(`multi`) restricted to the configured names (a JSON-schema `enum`, which
llama.cpp compiles into a grammar), plus a confidence (0..1) and a short
reasoning. Stored result status is `ok`, `no_labels` (a multi-label result with
an empty list) or `error`; items without any text are skipped.

## Versioning and the label-set hash

When `classify run` starts, the taxonomy is created in the database or updated
(`ClassificationRepo.ensure_taxonomy`):

* The **label-set hash** (`label_set_sha256`) is a SHA-256 over the mode and the
  sorted `(name, description)` pairs. Changing a label **name, description or the
  mode** changes the hash, bumps `taxonomies.version` and stores the new labels.
* Reordering labels changes nothing (same hash, no version bump).
* `instructions`, `max_labels` and `sources` are not part of the hash; each run
  records its prompt hash (`classification_runs.prompt_sha256`) instead.
* `taxonomies.created_at` never changes. It is the cut-off of the `default` scope.

A result counts as **done** only when it is `ok` / `no_labels` and its run used
the *current* hash. After a label change, old results stay visible (the view
`v_current_classification` shows the newest successful result) until the items
are classified again.

## Scopes: default, backfill, reprocess

| Scope | CLI | Items selected |
|---|---|---|
| `default` | (none) | not done **and** (collected after the taxonomy was created **or** never classified in any taxonomy) |
| `backfill` | `--backfill` or `--scope backfill` | everything not done for the current label set |
| `reprocess` | `--reprocess` or `--scope reprocess` | everything matching the filters, done or not |

Typical use:

```bash
# Daily: only new items (and items that were never classified at all).
postparse classify run --taxonomy topics

# A new taxonomy, or labels changed: classify the archive in chunks.
postparse classify run -t topics --backfill --limit 200
postparse classify run -t topics --backfill --source instagram --since 2024-01-01

# Re-classify a subset regardless of earlier results (adds a new run).
postparse classify run --taxonomy topics --reprocess --source instagram --with-transcript
```

Filters: `--source`, `--since YYYY-MM-DD`, `--with-transcript`, `--limit`.
`--provider` picks another `[[llm.providers]]` entry.

`postparse stats` shows the pending counts per taxonomy for the `default` and
`backfill` scopes (`--no-pending` skips that computation on large databases).

## Ad-hoc labels (nothing stored)

Classify free text without defining a taxonomy:

```bash
postparse classify text "Spaghetti Carbonara: Guanciale, Eigelb" --labels recipe,travel
postparse classify text "New FastAPI release" --labels recipe,tech --mode single
echo "Some text" | postparse classify text - --taxonomy topics --output json
```

`--labels` builds a throw-away taxonomy (names only); `--taxonomy` uses a
configured or stored one. Nothing is written to the database. The API offers the
same through `POST /api/v1/classify/{taxonomy}` and the ad-hoc endpoints
`/classify/multi` and `/classify/multilabel` (see the
[API reference](api-reference.md#classification)).

## Using the results

```bash
postparse search items --label topics:recipe
postparse search items --label topics            # any classified item of the taxonomy
postparse db export recipes.json --label topics:recipe --from 2024-01-01
```

Repeat `--label` for several labels of the **same** taxonomy (any of them).
The API accepts the same filter as `label=topics:recipe`.

## Migrated v1 classifications

`db migrate-v1` imports v1 results as taxonomy `topics` (multi-label LLM
results) and `recipe_legacy` (single label `recipe` / `not_recipe`, marked
legacy) with runs of status `legacy`. If your configured `topics` labels differ
from the migrated ones, the first `classify run` bumps the version; use
`--backfill` to classify the archive with the new labels.

The deprecated `postparse classify db` maps to `classify run --taxonomy topics`
(`--force` → `--scope reprocess`, default limit 1000).
