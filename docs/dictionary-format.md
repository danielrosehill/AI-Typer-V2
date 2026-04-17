# Custom Dictionary Format

The custom dictionary is a list of post-processing text substitutions applied
to transcription output after the model returns. It's for words the model
consistently mishears — names, jargon, acronyms, or domain-specific terms —
where putting them in the system prompt would be noisy and unreliable.

Substitutions run after any second-pass review, as the last step before the
text reaches your clipboard / window / cursor.

## Native storage

The app stores entries in `~/.config/ai-typer-v2/dictionary.json` as a JSON
list:

```json
[
  {
    "from": "ghz",
    "to": "GHz",
    "whole_word": true,
    "case_sensitive": false
  },
  {
    "from": "Voxcel",
    "to": "Voxtral",
    "whole_word": true,
    "case_sensitive": false
  }
]
```

### Fields

| Field            | Type    | Default | Meaning                                                                                                   |
|------------------|---------|---------|-----------------------------------------------------------------------------------------------------------|
| `from`           | string  | —       | The (mis-)transcribed text the model tends to produce. Required.                                          |
| `to`             | string  | `""`    | What to replace it with.                                                                                  |
| `whole_word`     | boolean | `true`  | If true, only match on word boundaries (`\b…\b`). Prevents `"ai"` from matching inside `"fair"`.          |
| `case_sensitive` | boolean | `false` | If false, match regardless of case (recommended for most corrections).                                    |

## Interchange format: CSV

There is no universal standard for dictation word-replacement lists — Dragon,
Talon, Windows Speech Recognition, and macOS Dictation all use different
(often proprietary) formats. For portability, this app uses **CSV** as the
import/export format. Any spreadsheet, dictation tool, or script can produce
or consume it.

### Minimal CSV

```csv
from,to
ghz,GHz
Voxcel,Voxtral
kubernetees,Kubernetes
```

### Full CSV

```csv
from,to,whole_word,case_sensitive
ghz,GHz,true,false
Voxcel,Voxtral,true,false
API,API,true,true
```

### Accepted column names

The importer is tolerant of common alternative header names (case-insensitive):

- `from` | `mistaken` | `spoken`
- `to` | `correct` | `written`
- `whole_word` — optional, defaults to `true`
- `case_sensitive` — optional, defaults to `false`

Boolean columns accept `true`/`false`, `yes`/`no`, `1`/`0`, `y`/`n`.

## Importing from other tools

Most dictation apps can export their vocabulary or auto-correction list to
CSV, either directly or via a short script. To import it here:

1. Ensure your CSV has at minimum a `from` column and a `to` column (rename
   the headers if needed).
2. Settings → Dictionary → **Import…**
3. Choose merge (keep existing entries, add new ones) or replace.

If your source tool uses a format this app doesn't read, converting it to the
CSV shape above is usually a few lines of Python or a spreadsheet
find-and-replace.

## Exporting

Settings → Dictionary → **Export…**. Choose CSV for sharing / backup, or JSON
to get the exact native format.

## How matching works

Each entry becomes a regex substitution:

- `from` is escaped (treated as a literal string, not a regex).
- With `whole_word: true`, the pattern is wrapped in `\b…\b`.
- With `case_sensitive: false`, the `re.IGNORECASE` flag is applied.
- Entries are applied in file order.

This means `from` values can contain spaces, punctuation, or multi-word
phrases safely — you don't need to escape anything yourself.
