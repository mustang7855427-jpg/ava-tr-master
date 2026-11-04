# Tortuga — serwer Avatarion (lokalnie i testowy Render)

Lokalny tryb programistyczny działa na Twoim komputerze. Opcjonalny publiczny
deployment na Renderze jest skonfigurowany wyłącznie z syntetycznymi assetami
testowymi; nie zawiera pełnej gry.

Strona główna serwera jest dostępna pod `/`, regulamin pod `/regulamin`,
a panel właściciela pod `/admin`. Zalogowany gracz ma obok klienta gry panel
ustawień plakietki `[A]` (administrator) lub `[AM]` (moderator). Ustawienie
zapisuje się na koncie i wpływa na informację o randze wysyłaną dla awatara;
nie zmienia uprawnień nadawanych przez serwer.

### Logowanie, sesje i płatności

Logowanie do istniejącego konta sprawdza token konta po stronie serwera.
Po poprawnym logowaniu aplikacja tworzy nową, szyfrowaną sesję cookie
z ograniczeniem czasu do 12 godzin, flagą `HttpOnly` i `SameSite=Lax`;
flaga `Secure` jest włączana przy HTTPS. Nieudane próby są ograniczane
do 10 na źródłowy adres w 15-minutowym oknie. W Redis zapisywany jest
wyłącznie skrót HMAC adresu źródłowego, nie sam adres.

Lokalne logi WWW i gry są zapisywane w `logs/` w UTF-8 i rotowane po 5 MiB,
z zachowaniem czterech kopii. Wdrożenie Render zapisuje logi na standardowe
wyjście platformy. Logi nie powinny zawierać haseł, tokenów ani danych
płatniczych.

`POST /webhooks/payments` weryfikuje ogólny podpis HMAC-SHA256 i zapisuje
potwierdzone zdarzenia w Redis. Konfiguracja wymaga zmiennych
`TORTUNGA_PAYMENT_WEBHOOK_SECRET` oraz `TORTUNGA_PAYMENT_MERCHANT_ID`.
Nadawca podpisuje tekst `timestamp + "." + surowe_bajty_JSON` i przekazuje
czas w `X-Tortunga-Timestamp` oraz nagłówek
`X-Tortunga-Signature: sha256=<hex>`. Podpis jest odrzucany po 5 minutach.
Zdarzenie musi zawierać `event_id`, `event_type` równy `payment.completed`,
`merchant_id`, `payment_id`, `payment_status` równy `COMPLETED`, `order_id`,
dodatnią całkowitą `amount_minor` i wielkimi literami zapisany kod waluty
`currency`. Klucze Redis zapobiegają ponownemu zapisaniu tego samego zdarzenia
i tej samej płatności; wpisy nie wygasają.

To własny, ogólny format HMAC, a nie adapter PayPal ani weryfikacja podpisów
PayPal. Produkcyjny nadawca musi podpisywać dokładnie opisane bajty; w
przeciwnym razie należy dodać weryfikację właściwą dla konkretnego dostawcy.
Webhook jedynie zapisuje potwierdzenie — nie przyznaje waluty, przedmiotów
ani uprawnień. `/localCallback` pozostaje wyłączony i zwraca HTTP 410.
Trwałość zapisów zależy od konfiguracji persystencji Redis.
Zweryfikowane i powtórzone zdarzenia są dodatkowo zapisywane jako
rekordy JSON Lines w `logs/payments.log`, bez surowego żądania ani danych
karty; log jest rotowany po 5 MiB z 12 kopiami.

`Start_Tortunga_Local.ps1` sprawdza lokalny Redis, dostępność portów
`127.0.0.1:8080` i `127.0.0.1:8123`, uruchamia WWW i grę wyłącznie na
localhost, a następnie sprawdza `/healthz` oraz rejestrację endpointu
webhooka. Kontrola webhooka wykonuje tylko GET i nie wysyła testowej
płatności. Użyj `.\Start_Tortunga_Local.ps1 -Stop`, aby zatrzymać wyłącznie
procesy uruchomione przez ten skrypt. Ten lokalny skrypt nie tworzy publicznego
wejścia z internetu ani tunelu do komputera.

Do lokalnego testu HTTPS można podać parę certyfikatu i klucza PEM:

```powershell
.\Start_Tortunga_Local.ps1 `
  -TlsCertificatePath C:\certs\localhost.crt `
  -TlsPrivateKeyPath C:\certs\localhost.key
```

Certyfikat musi obejmować nazwę `localhost`; lokalny certyfikat testowy nie
jest automatycznie zaufany i nie stanowi publicznego certyfikatu TLS.
HTTPS na localhost nie udostępnia serwera ani webhooka w Internecie.

## Wdrożenie w Render

W repozytorium znajdują się `render.yaml`, `render_start.py` i
`requirements-render.txt` dla wdrożenia Blueprint. Publiczna jest tylko usługa
WWW Render (HTTPS/WSS). Serwer gry TCP działa w tym samym kontenerze, ale
nasłuchuje wyłącznie na `127.0.0.1:8123`; Redis Key Value nie jest wystawiony
publicznie. `render_start.py` uruchamia serwer gry przed WWW i kończy usługę,
jeśli którykolwiek proces przestanie działać. Przekazuje procesom
`RENDER_DEPLOYMENT=true`, domyślnie wystawia WWW przez `0.0.0.0`, a TLS kończy
Render.

Blueprint używa darmowych planów Render dla WWW i Key Value, więc nadaje się
do testów, nie do trwałej gry produkcyjnej. Darmowa usługa WWW usypia się po
15 minutach bez ruchu i zwykle potrzebuje około minuty, aby ponownie wystartować.
Darmowy Key Value nie zapisuje danych na dysk; restart może usunąć konta,
postęp gry i sesje. Render ogranicza też miesięczne godziny i transfer.
Dlatego darmowy hosting **nie zapewni niezawodnego działania 24/7 ani trwałych
kont graczy**. Nie ma bezpiecznego sposobu obejścia tych limitów darmowymi
pingami. Używaj tej konfiguracji wyłącznie do testów i nie przechowuj w niej
danych, których utrata byłaby problemem.

Przed wdrożeniem:

1. Repozytorium GitHub zawiera kod i syntetyczne zasoby demonstracyjne
   w `demo-assets/`. Katalogi lokalne `files/` i `config_fb_tr/` oraz pliki
   SWF nadal pozostają wykluczone; nie publikuj tam oryginalnych zasobów gry.
2. W Render wybierz **New > Blueprint**, połącz repozytorium i wskaż
   `render.yaml`. Sprawdź, czy obie usługi pokazują plan **Free**; nie
   zatwierdzaj żadnej płatnej zmiany planu. Blueprint ustawia adres HTTPS
   zasobów testowych w `demo-assets/` oraz oddzielny pakiet Ruffle z CDN npm.
   **To jest tylko test startu backendu. Zastępcze zasoby nie zawierają
   klienta gry, interfejsu ani rozgrywki Avatarii.**
3. Pierwsze konto utwórz przez formularz rejestracji gry. Darmowy Redis jest
   pusty przy nowym wdrożeniu i może utracić wszystkie konta oraz postęp przy
   restarcie. Nie ustawiaj `OWNER_UID`, dopóki konto nie istnieje w Redis.
4. Aplikacja automatycznie używa publicznego URL usługi udostępnionego przez
   Render (`RENDER_EXTERNAL_URL`) do adresów zasobów SWF i połączenia WSS.
   Dla własnej domeny dodaj ją do usługi w Render i ustaw `PUBLIC_BASE_URL`
   na jej dokładny adres HTTPS. Menedżer Render przekazuje wybrany adres do
   serwera WWW; po zmianie domeny wykonaj redeploy.
5. Logowanie Google jest opcjonalne: bez `GOOGLE_CLIENT_ID` i
   `GOOGLE_CLIENT_SECRET` zwykłe konta nadal działają bez mailowej rejestracji.
   Jeśli je skonfigurujesz, dodaj w Google Cloud Console callback
   `https://twoja-domena/auth/google/callback`, zastępując host domeną
   ustawioną jako `PUBLIC_BASE_URL`, i wpisz sekrety tylko do zmiennych
   środowiskowych usługi WWW w Render.
6. Po deployu sprawdź health check WWW i logi obu procesów. Przetestuj
   rejestrację, logowanie gry i WSS przed zaproszeniem graczy. Publiczny panel
   Ownera wymaga zalogowania na skonfigurowane konto właściciela.

Blueprint nie przenosi lokalnego `files/` na Render: syntetyczne pliki testowe
są pobierane z `GAME_ASSETS_URL`. Zastąpienie ich zasobami gry wymaga źródła,
które możesz legalnie publicznie udostępniać. Render udostępnia publicznie
tylko HTTPS/WSS; surowy
port gry pozostaje lokalny wewnątrz kontenera, a Redis jest osiągalny tylko
przez prywatną sieć Render.

### Panel i blokady adresów IP

Panel właściciela jest dostępny pod `/admin` po zalogowaniu konta właściciela.
Blokada IP używa ostatniego adresu połączenia gracza z grą, zamyka jego
aktywne połączenie i odrzuca następne. Adres jest przechowywany wyłącznie
jako HMAC powiązany z tajnym kluczem sesji; surowy adres nie trafia do Redis.
Ostatni skrót połączenia jest przechowywany przez 90 dni; identyfikator
aktywnej blokady pozostaje do jej wygaśnięcia lub zdjęcia.
Przy blokadzie IP pamiętaj, że wielu graczy może korzystać z jednego
wspólnego adresu (np. domowego lub operatora komórkowego).

Za reverse proxy blokady IP są celowo wyłączone, dopóki zmienna
`TRUSTED_PROXY_CIDRS` nie zawiera rzeczywistych zakresów sieci zaufanego
proxy. Ustaw ją w środowisku serwera po uzyskaniu zakresów od dostawcy.
Nie wpisuj `0.0.0.0/0` ani zakresu, który obejmuje nieznanych klientów:
umożliwiłoby to podszywanie się pod cudze adresy w nagłówku
`X-Forwarded-For`. Po podaniu zakresów połączenie z nieznanego proxy zostanie
odrzucone zamiast przypisać wszystkim graczom adres proxy. Przy bezpośrednim,
poprawnie zabezpieczonym połączeniu adres jest pobierany z gniazda klienta.

### Wdrożenie Blueprint

Repozytorium `mustang7855427-jpg/avataria-serwer` zawiera już konfigurację
Blueprint. W Render wybierz **New > Blueprint**, połącz to repozytorium,
wybierz gałąź `main` i przejrzyj plan obu usług przed wdrożeniem. Konfiguracja
ustawia oba zasoby na Free; nie zatwierdzaj zmian planu na płatne. Puste
zmienne `OWNER_UID` i Google OAuth można pozostawić nieuzupełnione. Po
zakończeniu wdrożenia otwórz publiczny URL usługi WWW z panelu Render.

## Status konfiguracji lokalnej

Adres `127.0.0.1` to adres zwrotny komputera (localhost). Oznacza, że strona
gry działa pod `http://127.0.0.1:8080`, a serwer gry przyjmuje lokalne
połączenia na porcie `8123`. To potwierdza konfigurację lokalną — nie oznacza
awarii ani publicznego adresu internetowego. Samo wpisanie adresu nie uruchamia
serwera: strona odpowie dopiero po uruchomieniu usługi Redis oraz serwerów WWW
(`web.py`) i gry (`server.py`) zgodnie z poniższą instrukcją. Inne osoby nie
połączą się z tym serwerem przez internet.

Gra korzysta z polskiej konfiguracji i bezpłatnych zakupów. Oryginalny klient
jest plikiem SWF. Aplikacja Windows może uruchomić go przez emulator Ruffle;
nie wymaga dodatku do Chrome ani starego Adobe Flash Playera.

## Windows 64-bit: uruchomienie lokalne

Ta instrukcja uruchamia serwer natywnie w Windows, bez WSL i Linuxa.
Zainstaluj 64-bitową wersję Pythona i Windowsową usługę zgodną z Redis
(na przykład Memurai). Redis musi działać lokalnie przed uruchomieniem
serwerów; nie udostępniaj portu Redis `6379` w internecie.

Otwórz katalog repozytorium w VS Code i uruchom zintegrowany terminal
PowerShell w katalogu projektu. Utwórz środowisko i zainstaluj zależności
potrzebne do serwera:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-server.txt
```

Zadania **Python: compile server modules** i
**PowerShell: parse local startup script** w palecie **Terminal: Run Task**
sprawdzają składnię modułów serwera oraz skryptu startowego.
Zadanie **Python: test payment webhook** uruchamia lokalne testy webhooka
z atrapą Redis; nie łączy się z bramką ani z produkcyjną bazą danych.

Zainstaluj lokalną usługę zgodną z Redis dla Windows, np. Memurai. Jeśli
została już zainstalowana, możesz włączyć jej automatyczny start:

1. Otwórz menu Start, wpisz `Usługi` i uruchom aplikację **Usługi**.
2. Odszukaj usługę Memurai lub Redis. Jeśli jej nie ma, Redis nie jest
   zainstalowany — samo ustawienie autostartu nie zainstaluje usługi.
3. Otwórz właściwości usługi, ustaw **Typ uruchomienia: Automatyczny**,
   wybierz **Zastosuj**, a następnie **Uruchom**.
4. W PowerShell sprawdź, czy Redis odpowiada:

   ```powershell
   Test-NetConnection 127.0.0.1 -Port 6379
   ```

   Oczekiwany wynik to `TcpTestSucceeded : True`. Nie wystawiaj portu `6379`
   do internetu.

   Sprawdź też adres nasłuchu. Redis powinien nasłuchiwać wyłącznie na
   `127.0.0.1:6379`, a nie na `0.0.0.0:6379` ani `:::6379`. W tej instalacji
   usługa Redis 3.0 nie ma hasła ani trybu ochronnego, a jej konfiguracja
   znajduje się w `C:\Program Files\Redis\redis.windows-service.conf`.
   Otwórz ten plik jako administrator, dodaj `bind 127.0.0.1` obok ustawienia
   `port 6379`, zapisz i uruchom ponownie usługę Redis z aplikacji **Usługi**.
   Potwierdź nasłuch poleceniem `netstat -ano -p tcp | findstr :6379`:
   powinien pokazywać `127.0.0.1:6379`, nie adresy wieloznaczne.

Jeśli wynik to `False`, serwer Redis nie odpowiada. Otwórz ponownie **Usługi**
i sprawdź, czy Memurai lub Redis jest zainstalowany i ma stan **Uruchomiono**.
Jeśli usługi nie ma, zainstaluj zgodną usługę Redis dla Windows z oficjalnego
źródła, a potem uruchom ją i ponownie wykonaj test portu. Nie próbuj uruchamiać
gry ani otwierać portu `6379`, dopóki test nie zwraca `True`.

Następnie dwukrotnie kliknij `Uruchom_serwer.bat`. Skrypt utworzy
odizolowane środowisko `.venv-app`, zainstaluje lub sprawdzi pakiety projektu
i otworzy menedżer, który po chwili sam spróbuje uruchomić serwery oraz
osobne okno gry.
Instaluje tylko zależności serwera z
`requirements-server.txt` (bez pakietów bota). Przy pierwszym uruchomieniu
wymagany jest internet do pobrania pakietów Python. Aplikacja uruchamia
lokalne serwery WWW i gry, pozwala je zatrzymać, otworzyć stronę i zajrzeć do
logów. Redis musi odpowiadać przed startem. Jeśli automatyczna próba się nie
powiedzie, menedżer pokaże komunikat; można wtedy poprawić problem i kliknąć
**Uruchom serwer** ręcznie. W razie błędu sprawdź `web.log` oraz `game.log`
przez przycisk **Otwórz logi**.

#### Błąd `ERR_CONNECTION_REFUSED`

Jeśli przeglądarka pokazuje `ERR_CONNECTION_REFUSED` dla
`http://127.0.0.1:8080`, serwer WWW nie nasłuchuje. Uruchom
`Uruchom_serwer.bat` i poczekaj na automatyczną próbę startu w menedżerze.
Odśwież stronę dopiero, gdy status pokaże uruchomione serwery. Jeśli nie
wystartują, sprawdź komunikat menedżera i logi przez **Otwórz logi**.
Jeżeli log `web.log` zgłasza nieznany argument `cookie_secure`, a `game.log`
zgłasza brak `ConstBitStream`, uruchom ponownie launcher, aby zastosować
zgodne poprawki kodu i zależności. Po instalacji pakietów menedżer spróbuje
uruchomić serwery ponownie.
Jeżeli log WWW zawiera `unknown command 'HELLO'`, pozostaw klient Redis
ustawiony na RESP2 (ustawienie `protocol=2` w aplikacji) i uruchom ponownie
serwery. Wymaga to ponownego uruchomienia WWW oraz gry, nie tylko odświeżenia
strony w przeglądarce.
Przy starcie menedżer sprawdza porty `web_port` i `8123`. Automatycznie
zatrzymuje wyłącznie procesy `web.py`/`server.py` uruchomione z tego folderu
projektu. Nie zabija obcych procesów Python, Node ani innych aplikacji.
Jeśli port zajmuje inny proces albo Windows nie pozwala sprawdzić jego
właściciela, menedżer pokaże PID/nazwę lub błąd uprawnień i bezpiecznie
przerwie start. Wtedy zamknij wskazaną aplikację ręcznie.

#### Okno gry Ruffle

Pakiet Ruffle Web Selfhosted 0.7.1 jest umieszczony w `files\ruffle\`.
Serwer sprawdza skrypt, skrypty core i pliki WebAssembly, a `/files` mapuje
do folderu projektu niezależnie od bieżącego katalogu procesu. Jeśli ponownie
skopiujesz pakiet, zachowaj nazwy plików z oficjalnej paczki oraz oba pliki
licencji. Pliki `.wasm` są serwowane jako `application/wasm`, wymagany typ
MIME dla WebAssembly.

Klient gry łączy się z serwerem przez TCP. Ponieważ Ruffle działa wewnątrz
WebView2, lokalny serwer WWW przekazuje to połączenie przez WebSocket wyłącznie
do `127.0.0.1:8123`; nie otwiera dodatkowego portu dla internetu. Pasek
postępu pokazuje weryfikację zasobów i nawiązanie połączenia, ale nie zgłasza
100% tylko dlatego, że pokazał się ekran preloadera. Pełne załadowanie jest
potwierdzane dopiero po uwierzytelnieniu klienta przez serwer gry i zmianie
identyfikatora jego aktywnego połączenia względem stanu sprzed startu. Status
połączenia WebSocket i wysłanych danych jest liczony dla zalogowanego UID, a
nie globalnie dla wszystkich graczy.

`Uruchom_serwer.bat` uruchamia menedżer i osobne okno aplikacji gry.
Okno używa Microsoft Edge WebView2 jako wbudowanego silnika, ale nie otwiera
zwykłego okna Chrome ani Explorera. Zaloguj się w oknie gry i wybierz
**Uruchom grę**. Nie instaluj starego Adobe Flash Playera ani wtyczek z
nieznanych stron. Ruffle może nie obsługiwać wszystkich funkcji tego klienta;
czarny ekran lub błąd oznacza, że zgodność gry nie jest potwierdzona.

Kliknięcie **Uruchom serwer** (czyli wybranie uruchomienia lokalnego) pozwala
uruchomić stronę i serwer gry na tym komputerze. Nie włącza dostępu dla
graczy z internetu: adres `127.0.0.1` jest dostępny tylko na komputerze-host.
Inni gracze nie będą mogli dołączyć, a aplikacja nie ma ukrytej opcji, która
to odblokowuje. Publiczny dostęp pozostaje wyłączony do czasu przygotowania i
sprawdzenia bezpiecznego szyfrowania zgodnego z klientem gry.

Możesz też uruchomić procesy ręcznie w osobnych terminalach PowerShell:

```powershell
.\.venv\Scripts\python.exe web.py
```

```powershell
.\.venv\Scripts\python.exe server.py
```

Po uruchomieniu serwerów zaloguj się w osobnym oknie gry. Rejestracja jest
włączona dla lokalnego testu: wybierz **Utwórz konto**. Nowe konto zaloguje się
automatycznie, więc nie musisz przepisywać ani kopiować hasła. Po wylogowaniu
lub ponownym uruchomieniu WWW będzie potrzebne ponowne utworzenie konta albo
zapisane wcześniej dane logowania; zachowaj je prywatnie i nie wysyłaj w czacie.
Aplikacja nie otwiera Chrome ani Explorera.

### Granie po zamknięciu VS Code

Uruchom `Uruchom_serwer.bat`, a następnie w menedżerze kliknij
**Uruchom serwer**. Menedżer i serwery są osobnymi procesami Windows,
niezależnymi od VS Code. Możesz zamknąć VS Code i pozostawić serwery działające.

Możesz też zamknąć okno menedżera: gdy pojawi się pytanie **Czy zatrzymać
serwery?**, wybierz **Nie**, aby zamknąć samo okno i pozostawić serwery w tle.
Wybierz **Tak**, aby zatrzymać serwery i zamknąć menedżer, albo **Anuluj**, by
wrócić do menedżera. Po zamknięciu menedżera nie będzie można nim monitorować
ani zatrzymać procesów; w razie potrzeby można je zakończyć w Menedżerze zadań.

Wyłączenie lub uśpienie laptopa przerwie działanie serwerów. Redis musi być
uruchomiony przed startem gry.

### Zatrzymanie i ponowne uruchomienie

Przed wyłączeniem Windows zatrzymaj serwery przyciskiem **Zatrzymaj serwer**
(albo zatrzymaj ręcznie oba procesy klawiszami `Ctrl+C`), a potem zatrzymaj
usługę Redis w aplikacji **Usługi**. Przy następnym uruchomieniu
komputera włącz Redis i uruchom ponownie `web.py` oraz `server.py`.
Przed planowanym wyłączeniem wykonaj kopię danych Redis i upewnij się, że
trwałość danych jest włączona w używanej usłudze Redis.

Gdy laptop jest wyłączony albo uśpiony, serwer na nim nie działa i nikt nie
może się połączyć. Jeśli gra ma być dostępna także wtedy, gdy wyłączysz
laptop, serwer musi działać na innym, stale włączonym komputerze lub hostingu.

### Dostęp dla graczy przez internet

Publiczny serwer gry **nie jest obecnie obsługiwany bezpiecznie**. Klient gry
i serwer nie szyfrują binarnego protokołu (`encrypted="false"`), dlatego
serwer odmówi startu, jeśli `game_bind_host` nie jest adresem loopback.
Nie zmieniaj tego zabezpieczenia ani nie wystawiaj portu `8123` do internetu.
Do publicznego hostowania potrzebna jest zgodna implementacja szyfrowania po
stronie klienta i serwera oraz jej niezależny audyt.

Serwer WWW może działać poza localhostem wyłącznie po skonfigurowaniu TLS.
Ustaw w `web.ini` `tls_cert` i `tls_key` na ścieżki certyfikatu i klucza
prywatnego oraz `web_address` na adres `https://`. Nie udostępniaj klucza
prywatnego. To zabezpiecza tylko WWW, nie binarny protokół gry. Rejestracja
jest włączona w bieżącej konfiguracji lokalnej; formularz tworzy konta przez
POST i ogranicza rejestrację z jednego adresu do 3 prób na godzinę. Limit
nalicza się po pomyślnym utworzeniu konta, jest lokalny dla procesu i nie
zastępuje ochrony przed nadużyciami. Wyłącz
rejestrację (`allow_reg = false`) przed jakąkolwiek konfiguracją publicznego
WWW. Portu Redis `6379` nigdy nie wystawiaj do internetu.

## Bezpłatna paczka gry

Po zmianie źródłowej polskiej paczki gry możesz ponownie wyzerować jej ceny
i odświeżyć sumę wersji:

```sh
python utils/prepare_free_polish_config.py
```

### Źródło pełnych zasobów

Skrypt `update.py` nie korzysta już z wbudowanego adresu zewnętrznego serwera.
Przed uruchomieniem ustaw `GAME_ASSETS_URL` na adres HTTPS własnego magazynu,
który zawiera pełny manifest `versions.json` i zasoby gry, do których masz
prawo dostępu. Demonstracyjne `demo-assets/` nie zawiera pełnego pakietu.

```powershell
$env:GAME_ASSETS_URL = "https://twoj-serwer.example/zasoby"
.\.venv-app\Scripts\python.exe update.py
```

## Rejestracja i administracja

Rejestrację można włączyć ustawiając `allow_reg = true` w `web.ini`.
Utworzone konto otrzyma identyfikator i kryptograficznie losowy token hasła.

### Logowanie kontem Google

Opcjonalne logowanie Google tworzy konto gry przy pierwszym logowaniu i
rozpoznaje je później po niezmiennym identyfikatorze Google. Konto Google jest
powiązane z kontem gry tylko przez zweryfikowany identyfikator `sub`, nie przez
sam adres e-mail. Aplikacja nie przechowuje adresu e-mail ani hasła Google.
Istniejącego konta gry nie łączy automatycznie po adresie e-mail: zaloguj się
najpierw zwykłym loginem i hasłem, a potem użyj **Połącz konto Google**.

Utwórz klienta OAuth typu **Aplikacja internetowa** w Google Cloud Console.
Dodaj dokładny adres przekierowania dla domeny ustawionej jako
`PUBLIC_BASE_URL`: `https://twoja-domena/auth/google/callback`. Dla testów
lokalnych callback może mieć adres
`http://127.0.0.1:8080/auth/google/callback`.
Ustaw zmienne środowiskowe Windows `GOOGLE_CLIENT_ID` i
`GOOGLE_CLIENT_SECRET` i uruchom ponownie serwer WWW. Nie ustawiaj
`GOOGLE_OAUTH_REDIRECT_URI`, jeśli aplikacja ma sama wybrać callback na
podstawie `PUBLIC_BASE_URL` lub `RENDER_EXTERNAL_URL`. Przycisk
Google pokaże się tylko wtedy, gdy oba dane klienta są skonfigurowane.
Logowanie używa OAuth state, nonce, PKCE S256 oraz weryfikuje podpis i
najważniejsze roszczenia ID tokenu. Aplikacja używa zweryfikowanego adresu
e-mail zwróconego przez Google do sprawdzenia tożsamości, ale nie wymaga od
gracza osobnej rejestracji mailowej ani nie przechowuje tego adresu.
Nie wklejaj sekretu klienta Google do czatu ani repozytorium.

W PowerShell ustaw wartości otrzymane w Google Cloud Console (polecenia
zapisują je w profilu użytkownika Windows; otwórz nowy terminal po zmianie):

```powershell
[Environment]::SetEnvironmentVariable("GOOGLE_CLIENT_ID", "<client-id>", "User")
[Environment]::SetEnvironmentVariable("GOOGLE_CLIENT_SECRET", "<client-secret>", "User")
```

### Własna domena publiczna w Render

Dodaj własną domenę w ustawieniach usługi WWW w Render i skonfiguruj rekordy
DNS zgodnie z instrukcją Render. W środowisku tej usługi ustaw
`PUBLIC_BASE_URL` na dokładny origin, np. `https://gra.twoja-domena.pl`
(bez ścieżki końcowej). Jeśli `PUBLIC_BASE_URL` nie jest ustawione, aplikacja
używa `RENDER_EXTERNAL_URL`, które Render udostępnia automatycznie. Menedżer
`render_start.py` sprawdza adres HTTPS i przekazuje go serwerowi WWW, który
wylicza z niego adres WSS gry. Nie jest potrzebny lokalny tunel ani
wystawianie portów gry `8123` i Redis `6379` do internetu. Przy zmianie
domeny zaktualizuj też dozwolony callback OAuth Google, jeśli logowanie Google
jest włączone, i wykonaj redeploy.

Po zalogowaniu otwórz **Panel właściciela** albo `http://127.0.0.1:8080/admin`.
Panel jest dostępny wyłącznie dla skonfigurowanego UID właściciela z rangą co
najmniej 5; nie można przejąć uprawnień przez pierwsze logowanie lub rejestrację.
W trybie lokalnym przygotuj konto administratora narzędziem
`utils/grant_admin.py`, zaloguj się z tego samego komputera i otwórz
`/admin/claim`. Wpisz wymagane potwierdzenie, aby jednorazowo przypisać
właściciela. W Render ustaw `OWNER_UID` na istniejący UID; nie używaj
lokalnego przypisania właściciela w publicznym wdrożeniu.

Właściciel może sprawdzać graczy online, ustawiać poziomy, wysyłać ogłoszenia
oraz zarządzać banami kont, banami IP, wyciszeniami i ostrzeżeniami. Kary są
zapisywane w Redisie i mogą być bezterminowe (`0` minut). Poza Renderem
panel wymaga połączenia lokalnego; w Render jest dostępny po HTTPS wyłącznie
po zalogowaniu skonfigurowanego właściciela.

W sekcji **Role i moderatorzy** właściciel może przypisać graczowi rangę
stażysty moderatora (1), moderatora (2), starszego moderatora (3) lub kuratora
(4), a także odebrać dodatkowe uprawnienia, wybierając rangę gracza (0).
Administrator (5) jest zarezerwowany dla właściciela i nie można go nadać
innemu kontu z panelu. Rangi są sprawdzane przez serwer gry przy akcjach
moderacyjnych; nie wymagają ponownego logowania. Panel nie zmienia właściciela
ani własnej rangi administratora.

## Bezpieczeństwo bota Telegram

Komendy `/konto`, `/zmien_haslo` i `/resetuj_konto` działają wyłącznie
w prywatnej rozmowie z botem; w grupie bot odmawia działania. Token bota nie
jest przechowywany w pliku projektu. Ponieważ poprzedni token znajdował się
w lokalnym pliku konfiguracyjnym, unieważnij go w BotFather i wygeneruj nowy
przed ponownym uruchomieniem bota. Nie wklejaj tokenu do czatu ani repozytorium.

Zapisz nowy token jako zmienną środowiskową użytkownika Windows o nazwie
`TELEGRAM_BOT_TOKEN` (Ustawienia systemu → Informacje → Zaawansowane ustawienia
systemu → Zmienne środowiskowe). Jeśli bot nie ma jeszcze zainstalowanych
zależności, zainstaluj je w środowisku `.venv`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

Otwórz nowy PowerShell i uruchom:

```powershell
.\.venv\Scripts\python.exe .\utils\bot_telegram.py
```

Bot łączy się z Redis wyłącznie przez `127.0.0.1:6379`. Nie udostępniaj portu
Redis ani tokenu bota w internecie.

Szczegółowe kroki rozgrywki, panelu i ograniczeń tej wersji opisuje
[poradnik Avatarii](./PORADNIK_AVATARII.md).
