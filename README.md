# SIGNAL/20 — automatski agregator cyber security vesti

Sajt koji svakog sata sam povlači najnovije vesti sa 20 cyber security
portala (RSS), uklanja očigledne duplikate i objavljuje ih na GitHub Pages-u.
Ne treba ti sopstveni server — sve radi GitHub-ova besplatna infrastruktura
(Actions + Pages).

## Podešavanje (jednom, ~10 minuta)

1. **Napravi novi GitHub repozitorijum** (javni — GitHub Pages je besplatan
   samo za javne repoe na ličnom nalogu). Npr. `signal20`.

2. **Otpakuj ovaj zip i ubaci sve fajlove u repo** tako da struktura izgleda:
   ```
   signal20/
     fetch_news.py
     template.html
     requirements.txt
     README.md
     .github/workflows/update.yml
   ```
   Push-uj ih na `main` granu.

3. **Dozvoli workflow-u da piše u repo:**
   Settings → Actions → General → dole u "Workflow permissions" izaberi
   **"Read and write permissions"** → Save.

4. **Pokreni workflow prvi put ručno:**
   Tab **Actions** → izaberi "Ažuriranje vesti" → **Run workflow** → Run.
   Sačekaj da se završi (obično 20-40 sekundi) — ovo će kreirati `docs/`
   folder sa `index.html` i `news.json`.

5. **Uključi GitHub Pages:**
   Settings → Pages → Source: **"Deploy from a branch"** → Branch: **main**,
   folder **/docs** → Save.

6. Za par minuta sajt je živ na:
   `https://<tvoj-github-username>.github.io/<ime-repoa>/`

Od tada se sajt sam osvežava svakog sata (podesivo u
`.github/workflows/update.yml`, linija sa `cron:`).

## Kako radi

- `fetch_news.py` povlači RSS feed sa svakog od 20 portala, čisti HTML iz
  naslova/opisa, i pravi listu vesti.
- **Deduplikacija** poredi naslove po smislu (ne slovo-po-slovo) i, kad su
  dve vesti sa različitih portala dovoljno slične i objavljene u roku od
  4 dana, zadržava samo onu sa portala **višeg ranga** (BleepingComputer=1
  je najviši rang, CISA=20 najniži — menjaš u `SOURCES` listi u vrhu
  skripte).
- Rezultat se ubacuje u `template.html` (isti dizajn kao i ranije — dark
  mode, filter po izvoru, pretraga) i snima kao `docs/index.html`.
- GitHub Actions to radi automatski, po rasporedu iz `update.yml`.

## Realna ograničenja koja treba da znaš

- **Vesti ostaju na jeziku izvora** (uglavnom engleski) — automatski prevod
  bi zahtevao dodatni API i trošak, pa nije uključen. UI (meniji, dugmad)
  je na srpskom.
- **Deduplikacija nije savršena.** Kad dva portala napišu potpuno
  drugačije formulisan naslov o istoj vesti (npr. jedan pomene naziv
  napadačke grupe, drugi ne), skripta ih ponekad neće prepoznati kao
  duplikat — namerno je podešena da radije propusti poneki duplikat nego
  da pogrešno sakrije dve različite vesti. Prag osetljivosti je
  `TOKEN_OVERLAP_THRESHOLD` na vrhu `fetch_news.py`; smanji ga (npr. na
  `0.30`) za agresivniju deduplikaciju, po cenu većeg rizika od lažnih
  poklapanja.
- **RSS adrese se s vremena na vreme menjaju.** Svaki izvor u `SOURCES`
  ima listu `feeds` (jedan ili više kandidata); ako portal promeni RSS
  putanju, skripta će to ispisati u logu Actions taba ("nijedan RSS izvor
  nije dao rezultate") — tad samo dodaš novu adresu u listu za taj izvor.
  Nekoliko portala (CISA, SC Media) povremeno menja/ukida RSS, pa je
  moguće da će povremeno "iskočiti" iz feed-a dok se adresa ne ažurira.

## Prilagođavanja

- **Učestalost ažuriranja:** promeni `cron: "0 * * * *"` u
  `.github/workflows/update.yml` (npr. `*/30 * * * *` za svakih 30 min).
- **Broj vesti po izvoru / ukupno:** `MAX_PER_SOURCE` i `MAX_TOTAL` na
  vrhu `fetch_news.py`.
- **Dizajn:** sav CSS/HTML je u `template.html`, isti fajl koji je ranije
  napravljen kao artefakt — slobodno menjaj boje, fontove, raspored.
