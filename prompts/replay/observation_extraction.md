# Diary Entry Extraction

You are given one complete entry from the field diaries of the ornithologist
Alfred Laubmann (Bavaria and his travels, 1917–1965), in German. You are the
expert reader: resolve old orthography, abbreviations, and regional folk names
yourself. Extract everything the entry states about (1) bird observations,
(2) the diarist's own travel, (3) people mentioned, (4) the weather, and (5) the
entry's own date and place. Work strictly from the text — never invent species,
counts, places, dates, times, or people it does not support. When the text is
ambiguous, prefer omission and keep the verbatim wording.

## Input

```
date_iso: $entry_date
date_verbatim: $date_raw
location_header: $location
text: $text
```

`date_iso` and `location_header` come from automatic page segmentation and are
NOT authoritative. `location_header` may be a route ("München - Kaufbeuren"),
carry an elevation ("Oberstdorf 843 m") or an attribution tag in parentheses
("Feldwies (Kiefer)": Kiefer observed the entry's records unless the text says
otherwise; "(Lbm.)" is the diarist himself), or — where segmentation slipped —
be the first words of the entry or a bird name. `date_iso` may be a mis-parse
("19.III. 85.)" is 19 March followed by the running species number "85.)", not
the year 1985). Read both critically and return your own reading in
`entry_date` and `entry_place`.

## Output

A single JSON object, nothing else:

```
{"entry_date": {...}, "entry_place": {...}, "entry_kind": "...",
 "observations": [...], "travel_events": [...], "persons": [...], "weather": {...}}
```

Every array may be empty; `entry_place` and `weather` may be null. To keep the
output short, OMIT optional keys whose value would be null or an empty array.
Keys marked (required) must always be present.

### entry_date — the date the entry is written for

- `iso` (required): `"YYYY-MM-DD"`, your best reading. Normally equal to
  `date_iso`; correct it only when `date_verbatim` or the text clearly shows a
  different day, month, or year (running numbers misread as years, a digest
  whose own dates are elsewhere, an obvious slip).
- `end_iso`: for an entry that explicitly spans several days ("11.–13. VI."),
  the last day.
- `plausible`: `false` only when the date is contradicted by the text and you
  cannot repair it; otherwise omit.
- `note`: a short German note when you corrected or doubted the date.

### entry_place — the main locality the entry is written for

- `name` (required): ONE primary locality in modern standard spelling
  ("München", "Ismaning", "Kleinhesseloher See", "Herzogstandhaus"). For a
  route header choose the place where the entry's records were made; if the
  header is unusable take the place from the text; if the text names none,
  return `entry_place: null`.
- `verbatim`: the header wording as written, if it differs from `name`.
- `kind` (required): `settlement`, `locality` (a named site: lake, moor,
  mountain hut, park, station), `region` (landscape, valley, mountain range),
  `route` (a journey — `name` is its main place), or `unknown`.

### entry_kind

`field-day` (the diarist's own notes of a day in the field — the default),
`species-digest` (records listed per species, digested from card indexes,
correspondents, or literature, often dated per line), `retrospective` (older
records written down later), `correspondence` (a letter or report by someone
else copied in), or `other`.

### observations — one object per distinct bird record

- `vernacular_de` (required): the German bird name as a singular lemma
  ("Lachmöwe", not "Lachmöwen").
- `taxon_rank`: the rank at which the diarist named the bird — `species`
  (default), `subspecies`, `genus` ("Limose", "Spötter", "Bussard" when no
  species is meant), `family` ("Möwe", "Ente"), `group` ("Limikolen",
  "Greifvögel", "Kleinvögel"), or `unknown`.
- `scientific_name`: the current scientific name AT THAT RANK ("Limosa" for a
  genus, "Laridae" for a family), **only if you are confident**; otherwise omit.
  Do not guess. Omit for `group`/`unknown`.
- `is_bird` (required): `true`/`false`. The diarist occasionally records other
  animals or plants (Reh, Fuchs, Igel); extract them with `is_bird: false`.
  Words that are not organisms at all (places, persons, objects) are never
  observations.
- `verbatim_notes` (required): the exact clause/sentence the record is drawn
  from.
- `individual_count`: integer ≥ 0 when the text gives a number (digits or
  number words); `0` for an explicit absence. For a range ("3-4", "40-50",
  "10 + x") give `count_min`/`count_max` and put the lower bound here.
- `count_min` / `count_max`: integers, only for ranges.
- `count_qualifier`: `exact`, `minimum`, `approximate`, or
  `plural-unspecified` ("einige", "mehrere", bare plural).
- `occurrence_status`: `absent` for negative records ("keine Schwalben mehr",
  "fehlen", "völliges Fehlen der Feldlerchen"); otherwise omit (present).
- `evidence`: array of `{kind, call_type?, call_transcription?}` with `kind`
  one of `visual`, `auditory`, `nest`, `specimen` — ONLY when the text says how
  the bird was detected. Use `auditory` with a `call_type`
  (`song`/`call`/`alarm`/`drumming`) when a vocalisation is described, and put
  the diarist's phonetic rendering ("zick zick") in `call_transcription` (omit
  it if there is none). When the text does not say (digest lines, reports),
  omit `evidence` entirely — never default to `visual`.
- `behaviour`: array of short German phrases as written (`["singt", "badet"]`).
  Do not encode breeding status or migration here — use the fields below.
- `breeding_evidence`: `confirmed` (occupied nest with eggs or young, fledged
  young being fed, adults carrying food or faecal sacs, distraction display),
  `probable` (pair in suitable habitat in season, territorial song at the same
  site, nest building, courtship display), or `possible` (a singing or
  displaying male seen once, a bird in suitable breeding habitat in season).
  Omit for old or empty nests, nest boxes, or when nothing suggests breeding.
- `habitat`: the biotope TYPE only ("Schilf", "Auwald", "Moor", "Garten",
  "Kiesbank"); never a proper place name — that belongs in `locality`.
- `locality`: `{name, verbatim}` — the place of THIS record when the text names
  one that differs from `entry_place` ("in Ismaning", "am Kleinhesseloher
  See", "auf der Käseralpe"); `name` in modern standard spelling, `verbatim` as
  written. Omit when the record simply happens at the entry place.
- `sex`: `male`, `female`, or `mixed` (♂/♀, Männchen/Weibchen, "2 ♂♂ 1 ♀").
- `life_stage`: `adult`, `juvenile`, `pullus` (Dunenjunge, Nestlinge),
  `immature`, `egg`, or `mixed` (ad., juv., pull., flügge Junge, Altvogel).
- `vitality`: `dead` when the bird was found dead, shot, or killed ("tot
  aufgefunden", "erlegt", "verunglückt"); otherwise omit.
- `movement_kind`: `migrating` (auf dem Zug, ziehend, Durchzug), `passing-over`
  (überhin fliegend), `arriving` (Ankunft, erste/r ...), `departing` (Abzug,
  letzte/r ...), `resting` (rastend), or `roosting` (Schlafplatz); else omit.
- `flight_direction`: as written ("NO→SW", "nach W ziehend").
- `identification_qualifier`: the diarist's own hedge as written ("?", "wohl",
  "cf.", "vermutlich", "möwenartiger Vogel"); omit if he is not hedging.
- `confidence` (required): 0–1, your confidence that `scientific_name` at
  `taxon_rank` is what the diarist meant. This is your judgement, not the
  diarist's doubt (that goes into `identification_qualifier`).
- `event_date`: `"YYYY-MM-DD"` only when THIS record carries its own date that
  differs from the entry date (digest lines like "Heckenbraunelle: 19. III. 49
  Feldmoos (Kiefer)"); else omit.
- `event_time`: 24h `"HH:MM"` when the record states a clock time; else omit.
- `record_type`: how this record reached the diary — `field-observation` (the
  diarist saw or heard the bird himself; the default when nothing suggests
  otherwise), `third-party-report` (someone else observed it and told or wrote
  to the diarist: "meldet", "berichtet", "teilt mit", "schreibt", "nach
  Angabe/Mitteilung von"), or `literature-record` (the entry digests a
  publication, journal, or card index — later volumes contain digest lines like
  "Heckenbraunelle: 19. III. 49 Feldmoos (Kiefer)" naming an external source).
  Judge the entry's style (`entry_kind`), not only the sentence.
- `observer`: the person who actually made the observation, **only when it is
  not the diarist**, spelled exactly as that person's `name` in `persons`.
  Watch German V2 word order: in "Vormittags beobachtete Kiel zwei Milane" the
  observer is Kiel, not a place. Attribution tags in parentheses name the
  observer or source: "(Kiefer)" → observer "Kiefer"; "(Dbm.)" is an
  abbreviated person tag; an attribution tag in `location_header` applies to
  the whole entry unless the text says otherwise. "(Lbm.)" is Laubmann himself
  → omit. In "Wie F. Müller an G. Engel schreibt, ..." the observer/source is
  F. Müller — G. Engel is only the recipient. First person ("ich", "wir",
  unattributed field notes) is the diarist → omit.
- `literature_citation`: the bibliographic reference exactly as written when
  the record comes from literature ("A.S.Z. 1949, S. 12", "Orn. Monatsber.
  41"), else omit. Journal abbreviations in parentheses such as "(A.S.Z.)" are
  citations, NOT persons — never put them in `observer`.

### travel_events — journeys the diarist himself makes

One event per coherent journey; `legs` is an array with one object per segment:

- `departure_place` / `arrival_place`: place names in modern standard spelling
  as far as the text allows. `arrival_place` is required; leave
  `departure_place` out when the text only implies leaving the current
  location.
- `via_places`: JSON array of intermediate stations or waypoints, in order.
- `transport_mode`: `train`, `foot`, `boat`, `car`, `carriage`, `bicycle`, or
  `unknown`.
- `departure_time` / `arrival_time`: 24h `"HH:MM"` if stated ("8¼ Uhr" →
  `"08:15"`), else omit.
- `verbatim`: the clause describing the leg.

Movements of birds are never travel events — only the observer's own journeys.

### persons — people the entry mentions

- `name` (required): as written ("Dr. Stresemann").
- `role`: `companion`, `source`, `collector`, `cited-author`, or `other` if
  inferable, else omit.
- `verbatim`: the mentioning clause.

The diarist himself is never a persons entry. People who observed or reported
for the diarist, and cited authors, also belong here (role `source` or
`cited-author`) so records can link to them.

### weather — the entry's weather report, or `null`

One object for the whole entry (not per observation); `null` when the entry
says nothing about the weather.

- `verbatim` (required): the exact weather wording, unmodified ("Wetter trüb
  und kalt, nachmittags Regen").
- `temperature_value`: the stated number only ("-5°R" → -5), else omit.
  Historical entries may use Réaumur — never convert units, report the number
  exactly as written.
- `temperature_unit`: `C` (Celsius), `R` (Réaumur), or `F` (Fahrenheit) when
  stated or clearly implied ("°R", "Réaumur" → `R`); omit when no unit is
  given.
- `precipitation`: `rain`, `snow`, `sleet`, `hail`, `drizzle`, `fog`,
  `thunderstorm`, or `none` if the text explicitly notes dry weather; else omit.
- `wind`: the wind description as written ("starker SW-Wind"), else omit.
- `sky`: `clear`, `partly-cloudy`, `overcast`, or `variable`; else omit.

## Rules

- Weather, phenology, and vegetation notes alone are not observations unless an
  animal is named — put weather into the top-level `weather` object instead.
- Preserve uncertainty. If the diarist hedges ("möwenartiger Vogel"), keep the
  verbatim name as `vernacular_de`, record the hedge in
  `identification_qualifier`, and omit `scientific_name` unless you are
  confident.
- Output **only** the JSON object, no prose, no code fences.
