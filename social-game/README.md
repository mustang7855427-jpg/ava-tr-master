# Wyspy — autorski świat społecznościowy

Wyspy to niezależna gra społecznościowa napisana od podstaw. Korzysta z własnej
oprawy rysowanej w Phaserze i nie zawiera oryginalnych plików, nazw ani zasobów
Awatarii.

## Funkcje

- publiczne pokoje 2D, ruch klawiaturą lub kliknięciem i awatary graczy,
- czat na żywo z ograniczeniem częstotliwości wiadomości,
- portfel monet, codzienna nagroda, sklep, plecak oraz ustawianie i odzyskiwanie
  mebli,
- personalizacja i zapis wyglądu awatara: kolor ubrania, odcień skóry, kolor i
  rodzaj fryzury,
- narzędzia administratora: rangi, wyciszanie i blokowanie, reset haseł,
  przyznawanie monet, ogłoszenia oraz opróżnianie pokojów,
- konta i świat zapisane w SQLite.

## Uruchomienie lokalne

Wymagany jest Node.js 22.12 lub nowszy.

```powershell
cd social-game
npm install
Copy-Item .env.example .env
```

Wygeneruj unikalny klucz konfiguracji administratora i wpisz go w `.env` jako
`ADMIN_SETUP_KEY`. Możesz go wygenerować poleceniem:

```powershell
node -e "console.log(require('node:crypto').randomBytes(32).toString('hex'))"
```

Nie zapisuj tego klucza ani haseł administratora w repozytorium. Następnie:

```powershell
npm run dev
```

Frontend Vite działa pod `http://127.0.0.1:5173`, a API pod portem `3000`.
Po utworzeniu konta w grze, jednorazowe przejęcie roli administratora wykonuje
się przez `POST /api/auth/claim-admin` z polami `setupKey`, `username` i
`password`. Użyj klucza z `.env` i nowego, silnego hasła. Pierwsze zgłoszenie
jest jedyną możliwością utworzenia administratora tym mechanizmem.

## Budowanie i uruchomienie

```powershell
npm run build
npm start
```

Serwer udostępnia zbudowany frontend z katalogu `dist`. Ustawienia można
przekazać przez zmienne środowiskowe lub lokalny, nieśledzony plik `.env`.
Najważniejsze opcje:

- `PORT` — port HTTP (domyślnie `3000`),
- `DATABASE_PATH` — ścieżka do bazy SQLite (domyślnie `./data/world.sqlite`),
- `ADMIN_SETUP_KEY` — losowy sekret do jednorazowego utworzenia administratora,
- `ALLOW_REGISTRATION=false` — wyłącza nowe rejestracje,
- `SESSION_DAYS` — czas życia sesji (od 1 do 30 dni).

## Wdrożenie

Do publicznego wdrożenia w Render służy `render.yaml` w tym katalogu. Utwórz
Blueprint wskazujący na ten plik; konfiguracja uruchamia nową, odrębną usługę
Node.js na bezpłatnym planie i generuje `ADMIN_SETUP_KEY` po stronie hostingu.
Nie podłącza ona ani nie zmienia istniejącej usługi legacy.

**Ważne:** bezpłatny plan nie zapewnia trwałego dysku dla SQLite. Konto, meble i
postępy mogą zniknąć po restarcie lub uśpieniu instancji. To wdrożenie jest
publicznym serwerem demonstracyjnym, nie trwałym środowiskiem produkcyjnym.
Aby utrwalać dane na produkcji, trzeba użyć hostingu z dyskiem trwałym lub
zewnętrznej bazy danych, co może wiązać się z opłatami. Ustaw `DATABASE_PATH`
na ścieżkę trwałego woluminu, zanim potraktujesz serwer jako produkcyjny.
Nie umieszczaj `ADMIN_SETUP_KEY` ani haseł w repozytorium.
