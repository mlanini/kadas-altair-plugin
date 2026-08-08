# KADAS Altair - User Guide

Guida operativa aggiornata per installazione, configurazione API e utilizzo del plugin.

## Indice

1. Installazione
2. Primo utilizzo
3. Connettori e API supportate
4. Smart Tasking
5. Autenticazione e impostazioni
6. Troubleshooting

## Installazione

Scarica il pacchetto plugin e copia la cartella `kadas_altair_plugin` nel profilo KADAS.

```powershell
# Windows (esempio profilo Zivil)
Copy-Item -Recurse kadas_altair_plugin "$env:APPDATA\Kadas\KadasZivil\profiles\default\python\plugins\"
```

Requisiti:
- KADAS Albireo 2.3+
- Connessione internet

## Primo utilizzo

1. Apri **Plugins -> Altair -> Altair EO Data Panel**.
2. Seleziona un connettore dal menu.
3. Apri **Settings** per inserire credenziali/endpoints.
4. Esegui **Authenticate** (quando richiesto).
5. Definisci AOI (Draw Bbox / Map Extent / input manuale).
6. Imposta filtri (data, cloud cover, collection).
7. Clicca **Search** e poi **Load Layer** sui risultati.

## Connettori e API supportate

### Planet

- Catalog API: Data API (`/data/v1/item-types`, `/data/v1/quick-search`)
- Tasking API: `tasking/v2` (`/orders/`, `/pricing/`, `/captures/`)
- Auth: API key (Basic auth)
- Impostazioni principali:
  - `Planet API Base URL`
  - `Tasking Base URL`
  - `Orders Path`
  - `Pricing Path`

Riferimenti:
- https://docs.planet.com/develop/apis/data/
- https://docs.planet.com/develop/apis/tasking/

### Vantor / Maxar

- Catalog API: Discovery v1 (`https://api.maxar.com/discovery/v1`)
- Ricerca imagery consigliata: `/catalogs/imagery/search`
- Tasking API: Tasking v2 (`/tasking/v2/...`, endpoint tenant/account dipendenti)
- Auth:
  - Catalog: `maxar-api-key` e/o Bearer token (opzionali, dipende dal tenant)
  - Tasking: token/API key secondo contratto
- Impostazioni principali:
  - Discovery base/search path + timeout
  - Tasking base/create/list path + timeout

Riferimenti:
- https://developers.maxar.com/docs/discovery/guides/discovery-guide
- https://developers.maxar.com/docs/tasking/

### Jilin-1 Gaofen

- Catalog API: endpoint STAC compatibile tenant-specific
- Tasking API: endpoint configurabile tenant-specific
- Auth: token/API key opzionale (catalog e/o tasking)
- Impostazioni principali:
  - `Catalog Base URL`
  - `Default Collection`
  - `Catalog Token`
  - `Tasking Base URL`, `Create Path`, `List Path`, `Tasking Token`

### JAXA Earth

- Catalog API: STAC/COG pubblico (default)
  - Catalog: `https://data.earth.jaxa.jp/stac/cog/v1/catalog.json`
  - Search: `https://data.earth.jaxa.jp/stac/cog/v1/search`
- Tasking API: opzionale/configurabile (solo se usi broker/partner esterni)
- Auth catalog: non richiesta
- Impostazioni principali:
  - `Catalog URL`
  - `Search URL`
  - campi tasking opzionali (`base/create/list/token`)

### ICEYE, Umbra, Capella, CDSE Sentinel, NASA EarthData

Restano supportati con configurazione API-first nei rispettivi tab Settings.

## Smart Tasking

Il dock **Smart Tasking** usa previsione orbite (SGP4) e ricerca archive per suggerire immagini/passaggi.

Workflow rapido:
1. Apri **Plugins -> Altair -> Smart Tasking**
2. Seleziona satelliti/constellation
3. Definisci AOI e finestra temporale
4. Esegui predizione o archive search
5. Invia prefill al pannello Tasking Order

Nota: il pannello **Tasking Order** resta in modalità DEMO (compose email) e non invia ancora ordini live direttamente da UI.

## Autenticazione e impostazioni

Apri **Plugins -> Altair -> Settings**.

Best practice:
- Salva token/secret nel secure storage del plugin.
- Usa i pulsanti **Test ... Connection** dopo ogni modifica endpoint.
- Mantieni endpoint di default salvo esigenze tenant-specific.

## Troubleshooting

### Nessun risultato

Controlla:
1. AOI valido (`minX < maxX`, `minY < maxY`)
2. Date range coerente
3. Collection corretta
4. Credenziali/endpoint nel tab provider

### Errori di autenticazione

1. Rigenera API key/token
2. Verifica spazi extra in input
3. Verifica proxy KADAS (`Settings -> Options -> Network`)

### Layer non caricati

1. Verifica URL asset nel log
2. Verifica connettività/firewall
3. Verifica supporto GDAL/COG nel runtime KADAS

### Log

Apri **Plugins -> Altair -> View Logs** per dettagli su:
- auth
- request/response API
- errori di rete/proxy

## Risorse

- README: `README.md`
- Architettura: `ARCHITECTURE.md`
- Contributi: `CONTRIBUTING.md`
- Issues: https://github.com/mlanini/kadas-altair/issues

## Licenze Dati E Attribuzioni

Il plugin è software MIT, ma i dati imagery non lo sono: ogni provider applica
la propria licenza/contratto.

Checklist prima della pubblicazione di mappe, report o export:
1. Verifica termini del dataset/contratto del provider.
2. Inserisci attribuzione provider + dataset/collection + ID scena/ordine.
3. Conserva eventuali note copyright/usage richieste dal provider.

Riepilogo operativo per provider:
- ICEYE, Umbra, Capella, Planet, Vantor/Maxar Tasking: licenza commerciale, seguire il contratto cliente.
- Vantor Open Data: seguire i termini pubblicati per evento/dataset e citare Maxar/Vantor Open Data.
- Jilin-1 Gaofen: termini tenant/provider specifici.
- JAXA Earth: dati pubblici con termini JAXA dataset-specifici.
- CDSE Sentinel: policy Copernicus free and open data con attribuzione EU/Copernicus Sentinel quando richiesta.
- swisstopo: citare swisstopo e identificativo dataset/evento.
- NASA EarthData: citare NASA + DAAC + collection identifier.

Formato minimo consigliato di attribuzione:
- Provider: <nome provider>
- Dataset/Collection: <id o nome>
- Scene/Order ID: <id>
- Acquisition Date (UTC): <yyyy-mm-ddThh:mm:ssZ>
