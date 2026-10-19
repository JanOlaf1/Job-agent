# Job Agent

Oma työnhakuagentti: myynti, teknologian ja liiketoiminnan yhdistelmä sekä junior-IT.
Työalue on Uusimaa tai Suomesta tehtävä etätyö. Tuntematon sijainti jää tarkistettavaksi.

Lähteet → ilmoituksen lukeminen → pisteytys → CSV-historia → raportti → haluttaessa sähköposti.

## Tiedostot

- `src/main.py`: ajon vaiheet ja komentorivi.
- `main.py` projektin juuressa: tarkoituksellinen käynnistin komennolle `python main.py`;
  ei omaa sovelluslogiikkaa. Varsinainen ohjelma pysyy `src`-paketissa.
- `config/profile.json`: henkilökohtainen profiili, hakusanat ja lähetysrajat. Tiedot siirrettiin olemassa olevasta profiilista; CV-tiedostoa ei ollut repossa.
- `src/config.py`: roolien synonyymit ja lähteiden tekniset rajat.
- `src/job_search.py`: julkiset hakukortit, koko ilmoitus ja lähteiden tila.
- `src/scoring.py`: työn sopivuus ja perustelut.
- `src/tracker.py`: CSV:n turvallinen luku/tallennus ja uuden työn tunnistus.
- `src/reporting.py`: raportti ja yhteiset ilmoituskortit.
- `src/send_email.py`: viestin muotoilu ja SMTP, ei uutuuden laskentaa.
- `src/study_search.py`: Opintopolun julkinen rajapinta ja erillinen koulutuspisteytys.
- `job_tracker.csv`: kaikki työpaikat, myös heikot. `job_archive.csv`, jos olemassa, huomioidaan historiassa eikä sitä tyhjennetä.
- `jobs.md`: ajon uudet paikat ja aiempi tarkistettava historia.
- `source_health.json`: ajon yhteinen tulos ja lähteiden tila.
- `study_tracker.csv`: erillinen koulutushistoria; syntyy ensimmäisessä tallentavassa ajossa.
- `studies.md`: koulutusten historia, toteutustapa, laajuus ja hakuajat.
- `pending_email.json`: vain lähettämättä jäänyt viesti; seuraava sähköpostiajo yrittää uudelleen.
- `relevant_jobs.csv` ja `seen_jobs.json`: vanhat säilytetyt tiedostot; uusi ohjelma ei lue eikä kirjoita niitä.

## Pisteet ja uutuus

Rooli 0–30, kokemus 0–20, teknologia 0–10, kaupallisuus 0–15,
IT + asiakastyö 0–10, junior-taso 0–5, sijainti 0–10. Yhteensä enintään 100.
Synonyymit eivät monista ulottuvuuden pisteitä. Senioriteetti, kehittäjäkokemusvaatimukset,
väärä ammatti ja väärä työalue vähentävät pisteitä. Ohjelmointitausta on opintoja/projekteja.
STRONG ≥65, REVIEW ≥40, LOW ≥25, muuten REJECTED. Vanhan trackerin 42 pisteen
account manager -roolit ja 44 pisteen rajatapaukset pysyvät näkyvissä. Vanhoja pisteitä
ei arvata uudelleen ilman ilmoitusta; nykyinen pisteytys päivittyy löydettäessä uudelleen.

Uusi tarkoittaa: samaa URL:ia tai lähdekohtaista tunnistetta ei ole trackerissa/arkistossa.
Eri lähteiden ilmoitus yhdistetään vain täsmälleen samalla nimikkeellä, yrityksellä ja sijainnilla.
Saman lähteen erilliset ilmoitukset säilyvät erillisinä. Tracker päättää uutuuden kerran;
raportti ja sähköposti käyttävät samaa tulosta. UUSI-tila ei tarkoita että ilmoitus lähetetään uudelleen.
Sähköpostiin tulevat lähettämättömät paikat, joilla on kelvollinen linkki ja vähintään
`min_relevance_score` pistettä (oletus 60). REVIEW-luokitus alkaa yhä 40 pisteestä;
40–59 pisteen paikat näkyvät historiassa, mutta eivät oletuksena sähköpostissa.
Tunnettu 404/410-linkki, päättynyt hakuaika ja omat OHITA/HAETTU-tilat estävät lähetyksen.
Pitkän koosteen rungossa on enintään 20 työpaikkaa ja 5 koulutusta; kaikki valitut uudet
tulokset ovat silloin `new_results.md`-liitteessä. Laskurit kertovat koko löydetyn joukon.

Muokkaa CSV:ssä `status`, `applied_date`, `notes`. Tilat: UUSI, TARKISTETTU,
HAETTU, OHITA, HAASTATTELU, TARJOUS. Merkitse hakiessa HAETTU ja hakupäivä;
OHITA merkitsee itse ohittamaasi paikkaa. Automaattinen ajo ei muuta näitä kenttiä.
Historiaa ei automaattisesti poisteta/arkistoida. Vanha skeema luetaan sellaisenaan,
uudet sarakkeet lisätään tallennuksessa. Edellinen CSV kopioidaan `.csv.bak`-tiedostoon.
Virheellinen CSV pysäyttää ajon eikä muutu tyhjäksi trackeriksi.

## Paikallinen käyttö

Python 3.11+, komennot projektin juuresta:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m src.main --fixture tests/fixtures/run.json
python -m src.main
python -m src.main --dry-run
python -m src.main --commit
python -m src.main --commit --send-email
```

Ensisijainen käynnistys on `python -m src.main`. Myös `python main.py` toimii.
Älä aja `python src/main.py`: suhteelliset importit edellyttävät pakettikäynnistystä;
tämä komento näyttää nyt suoraan oikean käynnistysohjeen.
Puuttuvista riippuvuuksista näytetään asennuskomento. Odottamattoman ajovirheen koko
traceback tallentuu raporttikansion `error.log`-tiedostoon (oletuksena `preview/error.log`).
Verkkoyhteyden tai lähteen estyminen näkyy `source_health.json`:ssa; FAILED-ajon paluukoodi on 1.

Oletus on turvallinen live-esikatselu: ei sähköpostia eikä historian muutoksia.
Fixture-komento käyttää keksittyjä esimerkkejä ilman verkkoyhteyttä; testit estävät verkkokutsut.
Testit tarkistavat myös URL:n koko ketjun hakukortista CSV-tallennuksen kautta raporttiin
ja sähköpostiin sekä tilanteen, jossa kaikki kolme uutta työpaikkaa ovat REVIEW-tasoa.
Tulos on `preview/jobs.md`, `preview/email_preview.txt`, `preview/email_preview.html`,
`preview/studies.md` ja `preview/source_health.json`. Avaa HTML-esikatselu selaimessa.
Sähköposti sisältää HTML-kortit klikattavine linkkeineen sekä tekstiversion, jossa URL näkyy kokonaan.
Viestin alussa näkyvät uudet työpaikat ja uudet/muuttuneet koulutukset erikseen.
Osittainen tai epäonnistunut haku erotetaan onnistuneesta nollatuloksesta myös otsikossa.
Uusi tarkoittaa tässä sopivaa ilmoitusta, jota ei vielä ole merkitty lähetetyksi;
se on voinut löytyä aiemmalla ajolla. Tämän ajon hakutulosten määrä ja lähetysrajan
täyttävien paikkojen määrä kertovat haun kattavuudesta, eivät uusien viestien määrästä.
Sopivuuspisteet kuvaavat vastaavuutta profiiliin. Historiassa oleva paikka ei ole
automaattisesti vahvistetusti avoinna. Lähteiden ongelmat näkyvät viestin lopussa.
`--commit` tallentaa historian ja raportit juureen. `--send-email` lähettää oikean viestin.
`--data-dir` ja `--output-dir` voivat osoittaa erilliseen kokeilukansioon.
`--max-job-details 4` rajaa live-esikatselun työilmoitusten lisätietopyynnöt neljään;
lukemattomat kortit merkitään epävarmoiksi ja haku PARTIAL-tilaan. Rajaa ei voi käyttää `--commit`:in kanssa.
Jobly pyytää 10 sekunnin välin pyyntöihin, joten täysi ajo voi kestää useita minuutteja.
Repossa ennestään olevat raportit ovat historiaa; ne korvataan vasta tallentavassa ajossa.
Esikatselu ei kuluta lähetysjonoa. Tallennus ilman lähettämistä jättää uudet löydöt
`notification_status=pending`-tilaan: ne voidaan lähettää myöhemmin, jos ne ylittävät lähetysrajan.
SMTP:n hyväksymän lähetyksen jälkeen merkitään `sent_at` ja `notification_status=sent`.
Vanhoja rivejä, joilla ei ole notification_status-kenttää, ei lähetetä uudelleen.
SMTP-virheessä historia säilyy ja lähetysjono jää odottamaan. SMTP ei takaa täsmälleen
yhtä toimitusta: yhteyden katketessa hyväksymisen jälkeen uudelleenyritys voi toistaa viestin.
Sama riski on, jos GitHubin lähetyskuittauksen push epäonnistuu lähettämisen jälkeen.
Uusintayritys käyttää samaa Message-ID:tä, mutta vastaanottajan duplikaattisuodatusta ei voi luvata.

SMTP-asetukset `.env`-tiedostoon tai GitHub Secrets -arvoiksi: `SMTP_USER`,
`SMTP_PASSWORD`, `EMAIL_TO`. Valinnaiset ympäristömuuttujat `SMTP_HOST` (smtp.gmail.com),
`SMTP_PORT` (465, TLS). Gmailissa käytä sovellussalasanaa. Älä lisää `.env`:iä Gitiin.
Voit kopioida `.env.example`:n `.env`:ksi, jos omaa `.env`:iä ei vielä ole.
Ohjelma lukee nimenomaan projektin juuressa olevan `.env`:n, myös muualta käynnistettäessä.
Sähköpostiasetukset tarkistetaan ennen hakua ja historian tallennusta, jos lähetys on valittu.
Pelkkä haku/esikatselu ei tarvitse sähköpostitunnuksia eikä julkisten lähteiden API-avainta.

Muokkaa `config/profile.json`:ia. `target_roles`/`secondary_roles` kuvaavat haettavia nimikkeitä,
`skills` opinto-/projektiosaamista, `experience_keywords` aiemmin kirjattua kokemusta,
`locations` hyväksyttyjä paikkoja ja `exclude_keywords` vältettäviä nimikkeitä.
`training_interests` ohjaa koulutushakuja. `skill_watchlist` sisältää seurattavia osaamisalueita,
ei väitettä omasta osaamisesta. `languages` ja `strong_skills` ovat tyhjiä, koska näitä ei
voitu vahvistaa aiemmasta profiilista. Tyhjää kielilistaa ei tulkita kielitaidon puutteeksi.
`interests`, `industries`, `education` ja `remote_preferences` dokumentoivat taustan/toiveet;
niistä ei anneta automaattisia lisäpisteitä. Roolien synonyymit ovat `src/config.py`:ssä.
Vanha kuljettajatyö on vain historiaa. Henkilökohtainen profiili ei sisällä tunnuksia.

Lähetysasetukset profiilissa: `min_relevance_score=60`, `min_training_score=65`,
`send_empty_digest=false`, `training_digest_limit=5`. Ympäristömuuttujat
`MIN_RELEVANCE_SCORE`, `MIN_TRAINING_SCORE` ja `SEND_EMPTY_DIGEST` ohittavat profiilin arvot.
Ilman uusia sopivia työpaikkoja tai koulutuksia sähköpostia ei lähetetä. Ajon virheet
jäävät silti Actions-lokiin ja raporttiin. Työmarkkinahavainnot perustuvat vain kyseisen
haun deduplikoituihin relevantteihin ilmoituksiin: maininta ei tarkoita pakollista vaatimusta.

## Lähteiden rajat

Duunitori, LinkedIn, Jobly ja Academic Work ovat julkisen HTML:n varassa.
Laura on mukana viidentenä työpaikkalähteenä. Sen julkinen hakusivu lataa ilmoitukset
JavaScriptillä: sovitin käyttää saman sivun `ajax-filters.js`- ja `uranus-tag-filter.js`-
tiedostoissa näkyvää selaimen hakupyyntöä. Pyyntö ja suodattimet tarkistettiin oikeasta
palvelusta 19.10.2026. Kyseessä ei ole luvattu vakaa API; rakenteen muutos näkyy virheenä.
Laura-haut kattavat IT & tietoliikenne- sekä Myynti & hankinta -osaamisalueet:
Uusimaa/pääkaupunkiseutu sekä erillinen koko Suomen haku sanalla `etä`.
Etä-sana ei takaa etätyöoikeutta: ilmoituksen sijainti ja sisältö pisteytetään edelleen.
Myynti & hankinta sisältää myös epäsopivia vähittäiskaupan paikkoja; ne säilyvät
löytöinä, mutta nykyiset poissulut ja lähetysraja estävät niiden suosittelua.
Laurasta luetaan enintään 10 × 30 tulosta per haku (`LAURA_MAX_PAGES`, `LAURA_PAGE_SIZE`).
Jobly seuraa sivun omaa seuraavan sivun linkkiä enintään 5 sivua per haku
(`JOBLY_MAX_PAGES`); sivunumeroita tai uusia hakureittejä ei arvata.
Sivurajan ylittyminen merkitään PARTIAL-tilaksi ja jo löydetyt ilmoitukset säilyvät.
Toistuva sivu tai virheellinen vastaus ei ole onnistunut nollatulos. Hakujen päällekkäiset
URL:t luetaan vain kerran. Uudet lähteet voivat pidentää tallentavaa ajoa useilla minuuteilla.
Profiilin `secondary_roles` sisältää myös 12 suomenkielistä hakutermiä, esimerkiksi
asiakkuuspäällikkö, sovellusasiantuntija, käyttöönottoasiantuntija ja IT-tuki.
Ilmoituksen JobPosting JSON-LD on ensisijainen. Tarkkoja otsikkohakusanoja ei vaadita ennen lukemista.
Robots-sääntöjä noudatetaan; 403/429 tai esto pysäyttää kyseisen lähteen pyynnöt.
JavaScript-tyhjä sivu ei ole onnistunut nollatulos. HEALTHY = luettavia tuloksia,
EMPTY = tunnistettu tyhjä haku, BLOCKED = estetty, PARTIAL = osa epäonnistui,
FAILED = haku epäonnistui. SUCCESS/DEGRADED/FAILED kertoo koko ajon laadun.
Hakutulosten ensimmäiset julkiset sivut eivät takaa täydellistä kattavuutta.
Jobly käyttää JobPosting-tietoja; Academic Workin adapteri lukee myös nimetyt HTML-osiot.
Linkit muutetaan absoluuttisiksi, tracking-parametrit poistetaan ja ilmoituksen tunnistavat
parametrit säilytetään. Jo tehty detail-GET tarkistaa osoitteen ilman erillistä HEAD-kuormaa.
Redirectin lopullinen osoite, alkuperäinen `source_url` ja sivun `canonical_url` säilyvät.
Etusivu-/hakusivucanonicalia ei käytetä. `VERIFIED_GET` tarkoittaa luettua osoitetta,
`PAGE_DECLARED` sivun ilmoittamaa mutta erikseen tarkistamatonta canonical-linkkiä.
HTTP-esto ei yksin tarkoita rikkinäistä linkkiä. Kaikkien linkkien ikuista toimivuutta ei voi taata.

25.9.2026 tarkistetut vaihtoehdot: [Oikotie Työpaikat on suljettu](https://tyopaikat.oikotie.fi/).
[Työmarkkinatorin API](https://tyomarkkinatori.fi/ohjeet-ja-tuki/rajapinnat/tyopaikkailmoitusten-rajapinnat)
vaatii organisaatiokohtaisen käyttöönoton ja tunnukset, joten sitä ei esitetä tässä avoimena toimivana lähteenä.
Vanhoja heikosti toimineita Indeed/JS-sivustojen sovittimia ei säilytetty näennäisinä onnistumisina.

## Koulutukset

Haku kattaa koko Suomen: IT, myynti/liiketoiminta ja yhteiskunta-/valtiotieteet.
`STUDY_TERMS` ja `STUDY_SUBJECTS` ovat `config.py`:ssä. Paikkakunta ei hylkää koulutusta.
Verkko-, hybridi-, monimuoto- ja iltatoteutukset korostetaan; puuttuva tieto on UNKNOWN.
Maisteri/YAMK, korkeakoulututkinto, avoin korkeakoulutus, kurssi, opintokokonaisuus,
erikoistuminen ja täydennyskoulutus merkitään erikseen. Laajuus näkyy lähteen ilmoittamana.
Hakukelpoisuutta ei luvata: soveltuva tutkinto, esitiedot ja YAMK-työkokemus tarkistetaan linkistä.

Pisteet: aihe 40, IT/liiketalous-taustan yhteys 20 (yhteiskuntatieteissä kiinnostus 10),
joustavuus 15, taso 5–15, avoin haku 10. Päättynyt haku −20; tohtorikoulutus hylätään
nykyisen BBA-taustan suorana jatkona. Luokkarajat ovat samat kuin töissä.
Kurssin pistemäärä kertoo sopivuudesta, ei samanarvoisuudesta maisteritutkinnon kanssa.

Opintopolun toteutus-OID on pysyvä tunniste. Koulutus tulee yhteiseen sähköpostiin vain uutena
tai hakuajan/hakutilan muuttuessa. Kaikki hakujaksot ja tarkka määräaika säilytetään;
aktiivisen hakukierroksen määräaika näytetään ensisijaisesti. Lisätietohaun virhe ei poista
aiempaa määräaikaa. Omat status/notes-kentät säilyvät kuten työpaikoissa.

Käytössä on dokumentoitu **ulkoinen** `/external/search/toteutukset-koulutuksittain`
sekä `/external/toteutus/{oid}`. Sivuston sisäisiä hakureittejä ei käytetä.
Lähteet tarkistettu 24.9.2026: [OPH:n rajapintadokumentaatio](https://wiki.eduuni.fi/pages/viewpage.action?pageId=567372026),
[ulkoinen rajapinta ja parametrit](https://github.com/Opetushallitus/konfo-backend/blob/master/src/konfo_backend/external/api.clj),
[vastausskeema](https://github.com/Opetushallitus/konfo-backend/blob/master/src/konfo_backend/external/schema/search.clj).
Rajapinta ei tarvitse kirjautumista. Pyynnöt tahdistetaan; estoja ei kierretä.
Haku lukee enintään 3 × 20 koulutusta/hakusana ja 100 toteutuksen lisätiedot/ajo.
Rajojen ylittyminen näkyy PARTIAL-tilana. Lisätietojen lukuvuoro kiertää tallennettujen
lukuaikojen mukaan, jotta sama ensimmäinen joukko ei vie kaikkia pyyntöjä joka ajossa.
Hakusivuraja voi jättää alempia tuloksia löytymättä; rajat ovat muokattavissa configissa.
Opintopolku ei sisällä kaikkia korkeakoulujen erillisiä täydennyskoulutuksia.
Sähköpostiin valitaan vain koulutukset, joiden lisätiedot on luettu, haku on OPEN/UPCOMING
ja pistemäärä ylittää koulutusrajan. Pelkät hakukortit sekä sulkeutuneet tai tuntemattomat
hakuajat jäävät raporttiin. Puuttuvia hintoja ja aloituspäiviä ei arvata.

## GitHub Actions

Automaattinen ajo **05:17 ja 14:17 UTC**: Suomessa kesällä **08:17 ja 17:17**,
talvella **07:17 ja 16:17**. Käytössä on tavallinen UTC-cron; ajankohta ei ole minuutilleen taattu.
`workflow_dispatch` säilyy: Actions → Daily Job Agent → Run workflow.
Concurrency estää tämän työnkulun päällekkäiset ajot. Älä aja kahta paikallista tallentavaa ajoa yhtä aikaa.
Työnkulku testaa ensin ja käyttää `--commit --prepare-email`:ia. Historia ja ei-salainen
`pending_email.json` commitoidaan ja pushataan **ennen** `--deliver-pending`-lähetystä.
Epäonnistunut push estää lähetyksen. SMTP-virheessä jo tallennettu jono säilyy seuraavaan ajoon.
Onnistuneen lähetyksen jälkeen aikaleimat ja jonon poisto tallennetaan toisessa commitissa.
Jonossa ennestään oleva kooste käsitellään ensin; uusia hakuja jatketaan seuraavalla ajolla.
Raportit löytyvät Actions-artifactista. Salli Actionsille repositoryn contents: write;
suojattu oletushaara voi estää datan pushin, jolloin tiedostot pitää palauttaa artifactista.
Lisää yllä kuvatut kolme SMTP-salaisuutta repositoryn Actions Secrets -asetuksiin.
Valinnaiset Actions Variables: `SMTP_HOST`, `SMTP_PORT`, `MIN_RELEVANCE_SCORE`,
`MIN_TRAINING_SCORE`, `SEND_EMPTY_DIGEST`. SMTP käyttää implisiittistä TLS:ää (oletus 465),
ei portin 587 STARTTLS-yhteyttä. Työnkulun asetukset löytyvät `.github/workflows/job-agent.yml`:stä.

Käyttöönotto: vie muutokset GitHubin oletushaaraan, salli Actions ja `contents: write`,
aseta Secrets ja valitse **Actions → Daily Job Agent → Run workflow**. Ajastukset toimivat
oletushaarassa. Paikallinen testi ei todista GitHubin oikeuksien tai SMTP-tunnusten toimivuutta.
