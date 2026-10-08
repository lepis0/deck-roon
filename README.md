# Deck for Roon

Viikon levysuositukset Rooniin. Kerran viikossa Claude Code lukee Last.fm-historiasi ja
valitsee 20 albumia, joita et ole vielä kuullut. Jokaisella on lyhyt perustelu siitä,
miksi levy sopii juuri sinulle. Levyt kuunnellaan Roonissa TIDALin kautta.

Idea ja kuratointiohje on lainattu [jarilehtinen/deckistä](https://github.com/jarilehtinen/deck),
joka on Spotify-soitin macOS:lle. Tässä versiossa ei ole omaa soitinta, eikä se ole
sidottu Maciin: se on Docker-kontti, joka toimii palvelimella.

## Mitä saat

- **Web-sivu** (`http://<unraid-ip>:8795`): viikon albumit kansikuvineen ja perusteluineen.
  - **▶ Soita / + Jonoon**: albumi soimaan valitussa Roon-zonessa. Deck hakee albumin
    Roonin omalla haulla ja käyttää samaa Play Album → Play Now / Queue -polkua kuin
    Roonin oma sovellus.
  - **★ Hyllyyn**: lisää albumin TIDAL-suosikkeihin, jolloin se ilmestyy Roonin
    kirjastoon. Seuraava lista oppii siitä, mistä pidit.
  - **✕ Ei minulle**: poistaa albumin listalta, ja seuraava lista välttää samanlaisia.
  - **Aiemmat** ja **Hylly**: aiemmat listat ja hyllyyn nostetut levyt.
- **TIDAL-soittolista** "Deck · viikko 41/2026", joka sisältää viikon kaikkien albumien
  kappaleet. Roon synkronoi sen, joten viikon listan näkee myös Roonin omasta
  sovelluksesta. Edellisen viikon soittolista poistetaan, ellei asetuksissa ole
  `tidal_keep_playlists = true`.

## Miten se toimii

```
 maanantaisin            Unraid-host                       deck-kontti (:8795)
 User Scripts ──▶ bin/deck-curate ──▶ claude -p ──▶ bin/deck ──▶ deck taste            ◀── Last.fm
                                       (prompt.md)              deck curate submit   ──▶ TIDAL-haku
                                                                       │
                                                       curated.json ◀──┘──▶ TIDAL-soittolista
 selain ──▶ web-sivu ──▶ Roon extension API (haku → albumi → Play Now/Queue)
                     └─▶ TIDAL API (suosikit)
```

- `deck taste` tulostaa makuprofiilin: Last.fm:n top-artistit (kaikki ajat, 3 vuotta,
  12 kk), top-albumit, jokaisen albumin, jota olet soittanut vähintään 3 kertaa,
  hyllysi, otoksen TIDAL-suosikeistasi ja aiemmat listat sekä niistä annetun palautteen.
- `deck curate submit [--dry-run]` tarkistaa Clauden ehdokkaat TIDALista ja hylkää
  albumit, jotka jo tunnet (kuunneltu, hyllyssä, TIDAL-suosikeissa, ehdotettu aiemmin).
  Ilman `--dry-run`-valitsinta se kirjoittaa listan ja tekee soittolistan.
- Claude saa käyttää vain näitä kahta komentoa, kirjoittaa ehdokastiedostoja
  työhakemistoonsa ja tehdä verkkohakuja. Ohje on tiedostossa
  [`curate/prompt.md`](curate/prompt.md), ja sitä voi muokata vapaasti.

## Käyttöönotto

### 1. Kontti ja repo

GitHub Actions rakentaa jokaisesta `main`-haaran commitista imagen
`ghcr.io/lepis0/deck-roon:latest` (ja `sha-…`-tagin, versiotagista `v1.2.3` myös
`1.2.3` ja `1.2`).

**Unraid:**
1. Kopioi template palvelimelle:
   ```sh
   curl -fsSL -o /boot/config/plugins/dockerMan/templates-user/my-deck.xml \
     https://raw.githubusercontent.com/lepis0/deck-roon/main/unraid/deck-roon.xml
   ```
2. **Docker → Add Container → Template: deck → Apply.** Kontti käyttää host-verkkoa,
   jotta Roon löytää laajennuksen.
3. Päivitykset: Docker-sivu näyttää **update ready**, kun GitHub on julkaissut uuden
   imagen. **Apply update** hakee sen. Automaattisesti päivitykset hoituvat
   CA Auto Update -lisäosalla.

**Viikkoajon skriptit** (`bin/deck`, `bin/deck-curate`, `curate/prompt.md`) ajetaan
hostilla, joten repo kloonataan myös palvelimelle. Appdatan alla repo pysyy
cache-levyllä, eikä viikkoajo herätä arrayn levyjä:

```sh
git clone https://github.com/lepis0/deck-roon.git /mnt/user/appdata/deck-roon
```

Päivitä ne komennolla `git -C /mnt/user/appdata/deck-roon pull`.

Repon paikka on vapaa. `bin/deck-curate` lukee datakansion kontin `/data`-liitoksesta,
joten templaten Data-polun voi vaihtaa. Jos kontin nimi on muu kuin `deck`, kerro se
muuttujalla `DECK_CONTAINER`.

Ilman Unraidia: `docker compose up -d` (`docker-compose.yml`).

### 2. Roon

Roon → **Settings → Extensions** → **Deck – viikon levyt** → **Enable**. Tämä tehdään
vain kerran. Sivun Roon-merkki muuttuu vihreäksi ja zonet tulevat valikkoon.

### 3. Last.fm

Luo API-avain osoitteessa [last.fm/api/account/create](https://www.last.fm/api/account/create)
(sovelluksen nimeksi käy mikä tahansa, callback-kenttä voi jäädä tyhjäksi). Kirjoita
avain ja käyttäjänimesi tiedostoon `/mnt/user/appdata/deck/config.toml`:

```toml
lastfm_api_key = "…"
lastfm_user = "…"
```

Tarkistus: `bin/deck taste | head -c 500`

### 4. TIDAL

1. Kirjaudu osoitteessa [developer.tidal.com](https://developer.tidal.com) ja luo
   sovellus (Dashboard → Create app).
2. Lisää sovelluksen asetuksiin **Redirect URI** `http://<unraid-ip>:8795/tidal/callback`
   ja ota käyttöön scopet `collection.read collection.write playlists.read
   playlists.write search.read user.read`, jos dashboard kysyy niitä.
3. Kopioi **Client ID** ja **Client Secret** tiedostoon `config.toml`
   (`tidal_client_id`, `tidal_client_secret`). Jos käytit eri Redirect URI:a, päivitä
   myös `tidal_redirect_uri`. Asetukset luetaan konttia käynnistettäessä:
   `docker restart deck`.
4. Avaa sivu ja valitse **Kirjaudu TIDALiin**. Jos selain ei palaa sivulle kirjautumisen
   jälkeen, kopioi osoiteriviltä koko osoite ja liitä se kirjautumisikkunaan.

Albumihaku toimii pelkillä sovellustunnuksilla. Kirjautumista tarvitaan soittolistaan
ja suosikkeihin.

### 5. Ensimmäinen lista

```sh
/mnt/user/appdata/deck-roon/bin/deck-curate
```

Ajo kestää muutamia minuutteja. Loki menee tiedostoon `/mnt/user/appdata/deck/curate.log`.
Ajon voi toistaa milloin tahansa, jolloin lista korvautuu uudella.

### 6. Viikoittain

Unraid → **Settings → User Scripts** → **Add new script**, esimerkiksi nimellä `deck-curate`:

```sh
#!/bin/bash
/mnt/user/appdata/deck-roon/bin/deck-curate
```

Valitse ajastukseksi **Custom** ja `0 9 * * 1` (maanantaisin klo 9).

`bin/deck-curate` käyttää hostin `claude`-komentoa ja asetushakemistoa
`CLAUDE_CONFIG_DIR` (oletuksena `/mnt/user/appdata/claude-code/.claude`). Mallin voi
valita ympäristömuuttujalla `DECK_CLAUDE_MODEL`.

## Komennot

`bin/deck` ajaa komennon kontissa:

| Komento | Mitä tekee |
|---|---|
| `deck taste` | Tulostaa makuprofiilin JSONina |
| `deck curate submit [--dry-run] < ehdokkaat.json` | Tarkistaa ehdokkaat ja kirjoittaa listan |
| `deck playlist` | Tekee viikon TIDAL-soittolistan uudelleen |
| `deck tidal login` / `deck tidal finish <osoite>` | TIDAL-kirjautuminen komentoriviltä |

## Tiedostot (`/mnt/user/appdata/deck`, kontissa `/data`)

| Tiedosto | Sisältö |
|---|---|
| `config.toml` | Asetukset |
| `curated.json` | Tämän viikon lista |
| `history.json` | Kaikki ehdotetut albumit ja palautteesi (`rejected`) |
| `shelf.json` | Hyllyyn nostetut albumit |
| `tidal-token.json`, `roon-token.txt` | Kirjautumiset (vain omistajan luettavissa) |
| `curate.log` | Viikkoajojen loki |
| `curate-work/` | Clauden ehdokastiedostot viimeisimmästä ajosta |
| `cache/` | Last.fm-albumit (päivä), TIDAL-haut (päivä), TIDALista puuttuneet (puoli vuotta) |

## Rajoitukset

- Roonin extension-rajapinnalla ei voi luoda soittolistoja tai tageja eikä soittaa
  albumia TIDAL-tunnisteella. Siksi soitto kulkee Roonin oman haun kautta, ja
  soittolista ja kirjasto TIDALin kautta.
- Jos Roonin haku ei löydä albumia, sivu kertoo sen, ja albumin saa auki
  TIDAL ↗ -linkistä.
- TIDAL-haku tehdään maakoodilla `country = "FI"`, joten listalle päätyy vain
  Suomessa saatavilla olevia albumeja.

## Kehitys

```sh
pip install -r requirements.txt
python -m pytest -q tests
# tai kontissa:
docker build -t deck:dev . && docker run --rm -v "$PWD/tests:/app/tests:ro" deck:dev python -m pytest -q tests
```
