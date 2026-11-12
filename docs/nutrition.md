# Nutrition

The diary subtly flags complete macro values that fall outside the personal daily ranges: protein 2 g/kg current body weight with a 15 % tolerance, fat 20–30 % of the recorded calories, and carbohydrates depending on weight, training duration and intensity. From 90 minutes the range is 5–7 g/kg, from 120 minutes 6–10 g/kg, otherwise 3–5 g/kg. At least ten minutes in zone 4 or higher within a session raise the carbohydrate range by one step. Completed sessions replace the planned sessions they are matched to. If training or intensity data are missing, 3–5 g/kg serves as the starting range for light load; the actual need may be higher. If weight or macro values are missing, the respective comparison is omitted; low values are not flagged on the current day.

Besides calories, carbohydrates, protein and fat, the daily overview also shows consumed sugar and salt in grams. Both values are calculated from the stored product and food data with the amount eaten; later product changes do not change what was eaten. Missing values stay unknown, and known partial sums are labelled "unvollständig" (incomplete). The history shows averages for sugar and salt with the number of fully recorded days. The diary shows each composite meal as one entry; ingredients can be expanded in the card. Stored product and database snapshots keep the origin that was used, even after later product changes. Unknown nutrient values stay unknown and are not shown as zero in cards and daily totals. The entry stays local; synchronization to Intervals.icu happens only after explicit approval.

For energy expenditure, the last Garmin sync is shown compactly as **Sync: date, time**; without a sync time, an available fetch time is shown as **Abgerufen** (fetched). The ingredient sources of composite meals are listed in the expandable ingredient list.

The **Ernährung** (Nutrition) tab shows **Tagebuch** (diary), **Verlauf** (history), **Körper** and **Produkte** (products). **Verlauf** shows either 14 completed days or 12 weeks up to yesterday: the recorded calorie surplus or deficit, the average daily calorie balance, average intake and total Garmin expenditure, and average carbohydrates, protein and fat. Below the values, the chart shows intake and expenditure as separate bars with daily values or weekly averages; exact daily values can be expanded. Each average states the number of days it covers. For intake and expenditure, the weekly bars each state their own data coverage; if the coverage differs, their difference is not a balance. Expenditure stays visible even without nutrition tracking. The balance uses only days with both intake and total expenditure; with gaps it is a partial balance. Macro averages use only complete values per macro. Missing days do not count as zero; how meaningful the figures are depends on fully recorded meals. Recording and corrections go through the Coach by text, voice or photo. A diary meal can also be deleted directly after a confirmation; a receipt offers undo. Other actions in the tab prepare an editable message and do not save or send anything automatically. An existing chat draft is kept. If you give no time, the Coach saves the entry with "Uhrzeit unbekannt" (time unknown) and the meal type; the card then shows only the type instead of an invented time.

With "Definiere mein Standardfrühstück" (define my default breakfast), reusable meals with ingredients, amounts and nutrient values for one portion can be created. The Coach shows the template for confirmation before saving it. A template does not yet count as eaten. "Ich habe eine halbe Portion meines Standardfrühstücks gegessen" (I ate half a portion of my default breakfast) records the intake with correspondingly scaled nutrient values. One-off deviations change only the diary entry; permanent changes change the template and never earlier entries.

The Coach prefers **BLS 4.0** for basic foods and **Open Food Facts** for branded products and barcodes; if **Yazio** is set up, it searches there first when no source is named explicitly (see "Yazio product search"). The backend code calculates calories and macros from the selected food IDs and amounts; database source, reference amount and ingredient amounts are kept in the entry and in meal templates. The tab shows them on diary entries; saved meals have no view there and are reached through the Coach. The current OFF product API is read through its structured nutrient representation; automatically added OFF estimates and statements such as "less than" are not taken over as exact label values. Raw and cooked weight are not interchangeable; grams and milliliters are not converted without a density. Ambiguous products or unknown amounts must be clarified. Without a matching result, packaging values or explicitly labelled AI estimates remain possible. Missing macros and unrecorded days are not shown as complete zero values. If individual entries lack macros, the diary shows the sum of the known values as "unvollständig" (incomplete) and states the number of affected entries; the approval preview and Coach context continue to use only complete daily totals. The synchronization sends calories and the known macros, marks the day as synchronized, and clears unknown macros on Intervals.icu (value -1) so that no earlier value remains there; if a later change supplies the missing macros, the day is synchronized again.

**Access and limits:** BLS is bundled as a local dataset and works without an API key, account or running API queries. Open Food Facts needs no API key for read access; the application identifies itself with a User-Agent. The currently documented IP limits are 15 product queries and 10 search queries per minute. The application limits itself to 14 and 9 queries per minute respectively, stores responses for at most 24 hours in the bounded in-memory cache, and pauses on 429; a 503 is reported as unavailable without a pause. Other applications behind the same public IP share the provider limits. No search on every keystroke. Only search terms/barcodes for foods are sent to Open Food Facts, no meal amounts, photos, profiles or chat histories; the provider sees the server IP. On outage or when the limit is reached, no invented database value is used.

**Data sources:** Max Rubner-Institut (2025): *Bundeslebensmittelschlüssel (BLS), Version 4.0 — Deutsche Nährstoffdatenbank*, Karlsruhe, [DOI 10.25826/Data20251217-134202-0](https://doi.org/10.25826/Data20251217-134202-0), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.de). The bundled derivative contains food name, energy, carbohydrates, protein, fat and data origin per 100 g edible portion; missing values, traces and values below the detection limit stay unknown. Reproducible extraction: `python tools/extract_bls.py <BLS_4_0_2025_DE.zip>` with the [official download](https://www.blsdb.de/download). Open Food Facts: [database under ODbL 1.0, contents under the Database Contents License](https://openfoodfacts.github.io/openfoodfacts-server/api/); community-maintained product values must be checked for product, unit and completeness. BLS data and the OFF cache stay separate. No product data or images are uploaded to Open Food Facts.

Nutrition entries stay local; a transfer of the daily totals to Intervals.icu happens only on explicit request and approval. Templates and source information are part of the privacy export, the encrypted backup and the Nutrition deletion category.

Garmin's daily expenditure (provisional for today) with active calories and basal metabolic rate is shown for the selected diary date, separately from the recorded food intake. Date, source and freshness stay visible; values for today are provisional while Garmin's daily record is still being completed. Missing components stay unknown and are not added up to an invented total. Garmin's own daily-expenditure forecast value cannot be retrieved through the API; for today, the app therefore additionally shows its own estimate, clearly labelled "Prognose Tagesverbrauch (abgeleitet)" (daily expenditure forecast, derived): the basal metabolic rate of the last completed day (at most seven days back) plus the active calories so far, with the calculation shown. It typically deviates from Garmin Connect by a few kcal and is omitted when active calories or a plausible reference day are missing.

The nutrition navigation contains Tagebuch, Verlauf, Körper and Produkte. The Verlauf shows 14 completed days or 12 weeks up to yesterday, with daily values or weekly averages in the chart and an expandable table of daily values. Missing values stay unknown; sums and averages state their data coverage. Body has moved from Analysis into the nutrition area. In the "Produkte" tab, stored products can be marked as favorites with the star; favorites are listed on top and visible, and all other products are collapsed together under "Weitere Produkte" (more products; opened during a search). "Löschen" (delete) removes a product from the list after confirmation; meals already recorded stay unchanged. "Verwenden" (use) asks for the amount and either adds to the Coach message (an existing draft is kept and extended by one line; nothing is sent automatically) or, directly without the Coach, adds to an existing meal of the selected day; without a selected meal, the product is recorded as a new snack. A meal extended this way becomes a composition of its previous values and the product, with the product's nutrient values fixed at the time of the addition. Coach requests remain available through the main navigation.

## Local product database (mirror)

Every Open Food Facts product that the app fetches online is automatically and
permanently stored in the local database. Since schema v27 these entries are
rows of the one product table (`nutrition_products`) with their origin (the
database, for example `open_food_facts` or `yazio`, while own products have the
origin `own`) and the database's fetch date. For an EAN that an own product holds,
the own product wins: its stored foods stay available to lookups but are not
listed separately, and a newly created own product takes only its empty fields
(brand and nutrient values in the same unit) from them, with the origin of each
filled field recorded. Lookups never change an own product. Queries first read the
own products, then this mirror, and query Open Food Facts only if
a match is missing or older than 90 days. If the online fetch is not
possible, the stored version is used with its date ("Stand vom …", as of …).
A re-check takes every value the fresh result has and keeps a stored value
where it has none, so it fills gaps such as salt or fibre and never empties a
known field; stored entries name their missing core fields (`missing_fields`).
When the athlete re-checks an Open Food Facts entry ("Aktualisieren") and core
fields are still empty, the app asks Yazio for the same EAN (only when Yazio is configured, athlete
decision 2026-11-11) and fills only those empty fields, only from a Yazio
product on the same basis; each filled field names `yazio` and its fetch time
under `filled_fields`, and a later Open Food Facts value or a change of basis
ends it. A Yazio failure is named in the status line; lookups and calculations
make no extra Yazio request.
The Coach helps complete products: `list_incomplete_nutrition_products` lists
own products and stored database foods with empty core fields (at most 50), and
`fill_nutrition_product_gaps` writes values it looked up, per the product's own
basis, into named products. Only fields that are empty at write time are
written; a known value is reported as skipped, never replaced. An invalid item
(unknown product, non-core field, negative or implausible value) is rejected
whole. Each written field records its origin (`open_food_facts`, `yazio`, `bls`
or `web`, a web value with its source page) and time under `filled_fields`.
Filling two or more products is a bulk change: the Coach asks first and needs
your yes. The command receipt of the turn lists each product, field, value and origin, and
undo of the turn empties exactly those fields again (change history entity
`food_database_entry` for stored database foods).
For the Coach, matches carry the origin `data_origin` (`live`,
`local_database`, `local_database_stale`). In the "Produkte" tab, the "Datenbank" (database)
section lists the stored entries; "Lokal speichern" (save locally) takes over an
entry as an own product after review, "Aktualisieren" (refresh) re-checks one
entry online now with the same gap-filling rule and leaves it unchanged if the
database cannot be reached, "Aus Datenbank entfernen" (remove from database) deletes only
the mirror entry. The mirror is part of backup, export and data deletion. The upgrade to
schema v27 moves every former mirror row into the product table without loss.

## Yazio product search (optional)

Under **Mehr > Anbindungen** (More > Connections), "Verbindung prüfen" (check connection) explicitly checks the login. The status shows the last check result and its time; after a restart or a change of credentials, a new check is needed. Rejected logins can concern account or app credentials; the exact cause is not always known. On rate limiting or outage, try again later. Loading the status makes no request to Yazio.

With Yazio credentials set up (`YAZIO_*` or **Mehr > Anbindungen >
Zugangsdaten**, i.e. More > Connections > Credentials), product searches without an explicit source use this
order: own stored products, local database (mirror), Yazio,
Open Food Facts, BLS. The next source is queried if the previous one
has no matching result (every search word in the name, known calorie value),
is unreachable, or has reached its limit; a match in an earlier
source prevents all external requests. Barcodes go through the mirror, Yazio
and Open Food Facts. Without Yazio credentials, it stays with own products and
BLS, with Open Food Facts only on explicit request; with Yazio, search terms without a source specification are therefore also sent to Yazio and Open Food Facts. The Coach can also name `yazio`
as an explicit source.

Yazio matches carry the source "Yazio", values per 100 g or 100 ml and, where
Yazio provides them, portion information. Like Open Food Facts matches, they are stored in the
local mirror (schema v14) and can be saved as an own
product after review. There is no diary synchronization and no
write access to Yazio. Only the account (login), search terms,
barcodes and the profile sex, if set, are sent to Yazio; credentials and tokens do not appear in logs, diagnostics, export
or Coach context, and tokens stay in memory. Requests are limited
(10 s timeout, 20 requests per minute, 24 h cache, pause on 429;
after a rejected login, no further login attempts for 15 minutes).

**Known limitations:** The interface is unofficial and undocumented
([community specification](https://yazio-community.github.io/yazio-api-specification/),
[public description](https://saganos.github.io/yazio_public_api/)); it can
change without notice or block usage. It uses the public client pair of the Yazio app,
which is built in, and requires a known app version in the
User-Agent, which you can override with `YAZIO_USER_AGENT`. Nutrient values are read as values per
gram or milliliter (search parameters: region from `YAZIO_COUNTRY`, the profile sex when it is male or female, otherwise no `sex` parameter, without effect on the nutrient values) and multiplied by 100; implausible
values stay unknown. This assumption is tested only with synthetic fixtures,
not with a real account. Check matches before saving.

## Local products and packaging photos

The nutrition library stores confirmed individual products separately from
meal templates and diary entries. A barcode searches this
local product library first and uses Open Food Facts only as a fallback.
When the athlete describes a meal with ingredients and amounts, the Coach matches
each ingredient against the stored products first and uses matching
products by their ID; the text search finds a product if every search word occurs in
name or brand (`%` and `_` count literally; words shorter than
three characters must begin a word, so that "Ei" (egg) does not find "Reisnudeln" (rice noodles); punctuation such as commas or parentheses around a word is ignored). If
this search finds nothing, it re-checks the 100 most recently changed products without
regard to case and umlauts, with plural forms and one typo
("Champignons" finds "Champignon", "zuccini" finds "Zucchini"); here too every
search word must match. Only for ingredients without a matching product does it query BLS
or Open Food Facts. The BLS search likewise tolerates plural forms,
typos and "Soße"/"Sauce"; whole words and word endings rank before
word beginnings, so that "Reis" (rice) returns rice rather than "Erdbeereis" (strawberry ice cream). If no entry contains
all search words, it returns partial matches from the known word parts
("Risottoreis" finds Reis and Risotto) and labels them as such; even then the search also returns matching
stored products, even if the external database is unreachable
or rejects the request. All ingredients of a meal are queried in one search
(at most 20 terms); a failed term leaves the
matches of the others usable. The Coach then saves the meal directly with
all components, without a prior nutrient preview; saving calculates and
states the totals. If a response reaches the step limit, the Coach says what is
done and what is not; "weiter" (continue) resumes the task with the food IDs already
found. A
match from an online source is saved locally only after review and explicit confirmation; BLS, Open Food Facts and packaging values keep their own source labels.
The model knows the source label `fddb_export`, but there is no
FDDB import workflow. A live FDDB integration and the wrapper
[itobey/fddb-exporter](https://github.com/itobey/fddb-exporter) are currently
not integrated: the wrapper exports an existing FDDB diary to
MongoDB/InfluxDB and is not a product-level lookup API. Nutrient values are always stored with
reference amount and unit. Grams and milliliters are not converted into each other without a known
density.

When a barcode matches, the product form appears directly below it. Available values for sugar, fiber and salt are taken over; missing values stay empty. Only saving creates the product locally.

A photo of the nutrition table is size-limited and transmitted only temporarily to the
configured OpenAI Responses-compatible API. The API returns a
structured, editable proposal; image data, provider responses and
unconfirmed values are not stored in the product library. Name,
reference amount and recognized nutrient values must be reviewed before saving.
The handover of a camera photo by Android/Chromium has not yet been verified on a real
Android device.
When an intake is recorded, the server calculates the values from the local
product and stores an immutable nutrient snapshot in the diary;
later product changes do not change earlier entries.
