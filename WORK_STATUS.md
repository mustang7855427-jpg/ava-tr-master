# Status projektu

## Aktualny status wdrożenia Render

- Kod obsługuje rozdzielenie źródeł: `/files/` i `config_fb_tr/` są
  wykluczone przez `.gitignore`; Render ma pobrać zasoby z `GAME_ASSETS_URL`.
  `render_start.py` pobiera wskazane w `versions.json` archiwum konfiguracji
  serwera i bezpiecznie je rozpakowuje przed uruchomieniem backendu.
- Nie wykonano publikacji ani wdrożenia. Repozytorium GitHub nie zawiera kodu,
  Git nie jest dostępny w tym środowisku, a `GAME_ASSETS_URL` nie wskazuje
  jeszcze zewnętrznego magazynu z wymaganymi zasobami.
- Do uruchomienia potrzebny jest HTTPS-owy magazyn z prawem do publicznego
  udostępniania zasobów, zawierający `versions.json`, strukturę `files/`
  i archiwum konfiguracji wskazane w manifeście. Samo pominięcie plików
  w GitHubie nie przenosi ich ani nie rozwiązuje kwestii licencji.

## Co zostało przygotowane

- Instrukcja lokalnego uruchomienia na Windows 64-bit bez WSL.
- Lokalny menedżer serwera uruchamiany przez `Uruchom_serwer.bat`. Wymaga
  działającego Redis; skrypt startowy przygotowuje `.venv-app` i instaluje
  zależności Python przy uruchomieniu.
- Domyślne ustawienia pozostają lokalne. Menedżer odrzuca konfigurację
  nasłuchiwania poza localhost.
- Publiczne nasłuchiwanie gry pozostaje zablokowane: klient i serwer
  korzystają z protokołu deklarowanego jako nieszyfrowany.
- Rejestracja jest włączona dla lokalnego testu; odbywa się przez POST i ma
  lokalny limit prób. Nowe tokeny haseł są generowane kryptograficznie.
- Dodano lokalne narzędzie `utils/grant_admin.py`, które może nadać
  istniejącemu kontu rolę ADMIN (5) po potwierdzeniu UID.

## Czego projekt jeszcze nie zapewnia

- Oryginalny klient gry ładuje pliki SWF. Dodano aplikację okienkową Windows
  opartą na WebView2 i integrację Ruffle. Pełny pakiet Ruffle Web Selfhosted
  0.7.1 skopiowano do `files\ruffle\` z załączników (główny JS, oba pliki
  WASM wskazane przez JS, dwa skrypty core, README i licencje). Kompatybilność
  klienta gry z Ruffle nadal wymaga sprawdzenia w uruchomionej aplikacji.
- Serwer nie jest gotowy dla graczy z internetu. HTTPS dla strony WWW nie
  szyfruje binarnego połączenia gry.
- Nie utworzono konta administratora, nie uruchomiono Redis ani serwerów.
- Składnię zmienionych plików sprawdzono w Pylance. Pełne testy działania
  z Redis nie zostały wykonane.

## Jak przejrzeć i zachować zmiany

1. W VS Code przejrzyj zmienione pliki w panelu **Source Control** albo
   otwórz je bezpośrednio: `README.md`, `web.py`, `server.py`, `web.ini`,
   `server_manager.pyw`, `Uruchom_serwer.bat` i pliki narzędzi w `utils`.
2. Nie akceptuj zmian w ciemno. Sprawdź, czy ustawienia `web_bind_host` i
   `game_bind_host` nadal mają wartość `127.0.0.1`. Nie włączaj publicznego
   dostępu ani nie otwieraj portów routera/zapory.
3. Zapisz pliki w VS Code. Nie trzeba wykonywać `git commit`; ten folder nie
   jest skonfigurowany jako repozytorium Git.

## Test lokalny w Windows

1. Zainstaluj 64-bitowy Python oraz lokalną usługę kompatybilną z Redis.
2. W PowerShell przejdź do folderu projektu i zainstaluj wymagane pakiety:

   ```powershell
   cd C:\Users\kryst\Desktop\ava-tr-master
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements-server.txt
   ```

3. Uruchom usługę Redis w aplikacji **Usługi** systemu Windows.
4. Uruchom `Uruchom_serwer.bat`. W menedżerze wybierz **Uruchom serwer**.
   Użyj **Otwórz logi**, jeśli któryś proces się zakończy albo nie wystartuje.
5. Otwórz lokalnie `http://127.0.0.1:8080`. Ta próba sprawdza tylko serwer
   WWW i lokalny serwer; nie potwierdza działania klienta bez Flash ani
   połączeń graczy przez internet.
6. Zatrzymaj serwery przyciskiem **Zatrzymaj serwer**, a potem zatrzymaj
   usługę Redis. Wykonaj kopię danych Redis przed testami, które mogą
   zmodyfikować konto lub stan gry.

Jeśli Python, Redis lub zależności nie są zainstalowane, test nie będzie
kompletny. Nie udostępniaj portów `8080`, `8123` ani `6379` w trakcie testu.

## Bieżący stan uruchomienia i logowania

- Python 3.15.2 i launcher `py` są dostępne.
- Pełne `requirements.txt` nie zainstalowało się z powodu budowania
  `pydantic-core` dla pakietu bota. Utworzono `.venv-app` i instalacja
  `requirements-server.txt` zakończyła się powodzeniem.
- Kompilacja plików Python i importy zależności serwera przeszły.
- Menedżer został uruchomiony (proces działa). Nie utworzono skrótu na
  pulpicie; automatyczny zapis tam został zablokowany przez sandbox.
- Wcześniejszy test wykazał, że Redis nie odpowiadał na `127.0.0.1:6379`.
  Następnie użytkowniczka wykonała `Test-NetConnection` i otrzymała
  `TcpTestSucceeded : True`. To potwierdza połączenie TCP, ale nie sprawdza,
  czy usługa odpowiada prawidłowo na polecenie Redis PING.
- Launcher został uruchomiony; instalacja zależności serwera już była
  aktualna i zakończyła się powodzeniem. Brak `logs\web.log` i
  `logs\game.log` wskazywał, że menedżer nie rozpoczął próby uruchomienia.
  Menedżer zmieniono tak, by po otwarciu automatycznie próbował uruchomić
  serwery; jeśli próba zawiedzie, wyświetli komunikat, a użytkowniczka może
  ponowić ją przyciskiem **Uruchom serwer**.
- Po uruchomieniu menedżera logi wykazały niezgodne API:
  `EncryptedCookieStorage` nie przyjmuje `cookie_secure`, a zainstalowany
  `bitstring` 5 nie zawiera `ConstBitStream`. Poprawiono argument na `secure`
  i przypięto `bitstring<5` w obu plikach wymagań. `.venv-app` ma teraz
  `bitstring 4.4.0`; importy obu wymaganych API i kompilacja `web.py`,
  `server.py` oraz `client.py` przeszły. Działanie serwerów i odpowiedź HTTP
  wymagają jeszcze ponownej próby uruchomienia.
- Log WWW wykazał, że serwer Redis na porcie 6379 nie obsługuje `HELLO`
  wysyłanego domyślnie przez redis-py 8. Ustawiono `protocol=2` w klientach
  Redis WWW i gry. Opcja jest dostępna w zainstalowanej wersji redis-py,
  a kompilacja obu modułów przeszła. Należy zatrzymać i ponownie uruchomić
  oba serwery, aby załadowały poprawiony kod; sukces HTTP/logowania nie jest
  jeszcze potwierdzony.
- Użytkowniczka zgłasza czarny ekran po pasku ładowania w Chrome. `game.log`
  zawiera wcześniejsze wyjątki ze startu, a później informuje, że serwer
  przyjmuje połączenia; wpisy licznika w dostępnych logach pokazują 0 graczy.
  To nie potwierdza połączenia klienta gry. Projekt używa klienta SWF; nie
  potwierdzono działającej alternatywy HTML5 ani pełnej zgodności z Ruffle.
  Zalecono nie instalować starego Flash Playera ani niezaufanych wtyczek.
- Użytkowniczka wybrała osobne okno aplikacji zamiast Chrome/Explorera.
  Dodano `game_window.pyw` (pywebview/WebView2), automatyczne otwieranie okna
  z menedżera, Ruffle JavaScript API w zalogowanej stronie i zależność
  `pywebview`. Biblioteka pywebview 6.2.1 jest zainstalowana, import oraz
  renderowanie szablonu sprawdzono. Pełny pakiet Ruffle Web Selfhosted 0.7.1
  został następnie skopiowany z dostarczonych załączników do `files\ruffle\`.
  Pozostaje uruchomić aktualny launcher i sprawdzić aplikację na urządzeniu.
- Przy ostatniej próbie tworzenia konta log WWW pokazał `WinError 10048`:
  port `127.0.0.1:8080` był już zajęty przez wcześniejszy proces WWW, więc
  nowy proces serwera nie wystartował. Dodano do menedżera kontrolę portów
  8080 i 8123, która blokuje uruchomienie duplikatu i pokazuje jasny błąd.
  Zatrzymaj poprzednią kopię z jej menedżera, a potem uruchom aktualną.
- Użytkowniczka otrzymała komunikat o limicie rejestracji. Poprawiono kolejność
  w `web.py`: licznik próby jest zwiększany dopiero po utworzeniu konta, więc
  błędy Redis/serwera nie zużywają limitu. Działający proces WWW trzeba
  zrestartować, aby załadował tę poprawkę; próby już zapisane w pamięci
  bieżącego procesu nadal pozostają do wygaśnięcia (1 godzina).
- Pełny pakiet Ruffle Web Selfhosted 0.7.1 skopiowano z załączników do
  `files\ruffle\`. Sprawdzono wersję pakietu, obecność obu plików WASM
  wskazanych przez `ruffle.js` i poprawne nagłówki WebAssembly. Składnia
  `game_window.pyw`, `server_manager.pyw`, `web.py` i `server.py` przeszła
  `py_compile`.
- Zgłoszenie czarnego ekranu skłoniło do usunięcia zależności serwowania
  plików od bieżącego katalogu procesu: `web.py` teraz ustala `ROOT` względem
  własnego pliku i mapuje `/files` na bezwzględną ścieżkę `ROOT/files`;
  szablony są również ładowane z `ROOT/templates`, a konfiguracja z
  `ROOT/web.ini`. Skrypt Ruffle i pliki gry mają jawne ścieżki URL od root
  strony, a `publicPath` wskazuje bezwzględny URL katalogu Ruffle. MIME
  rozszerzenia `.wasm` ustawiono jawnie na `application/wasm` przed importem
  aiohttp, aby jego rejestr typów MIME widział tę konfigurację. Weryfikacja
  rzeczywistego `aiohttp.web_fileresponse.CONTENT_TYPES` potwierdziła
  `application/wasm` dla obu plików WASM; kontrola kompletności zasobów i
  `py_compile web.py` również przeszły. Serwer
  sprawdza teraz obecność `ruffle.js`, skryptów core i plików WASM przed
  pokazaniem opcji startu. Zmiana wymaga restartu WWW; uruchomienia gry w
  oknie i zniknięcia czarnego ekranu nadal nie potwierdzono.
- Ponownie uruchomiono `Uruchom_serwer.bat`; instalacja zależności zakończyła
  się powodzeniem. Nowa instancja WWW nie mogła się uruchomić, bo `web.log`
  zgłasza `WinError 10048` dla portu 8080. `game.log` ma nowsze wpisy o
  działającym, wcześniejszym serwerze gry. Nie zakończono żadnego procesu
  automatycznie. Kontrola Redis z sandboxa jest ograniczona błędem
  `WinError 10013`, więc nie potwierdza stanu usługi na komputerze użytkowniczki.
- Po kolejnych konfliktach portów dodano `psutil` i bezpieczne sprzątanie
  przy starcie: menedżer rozpoznaje listenera tylko wtedy, gdy proces ma
  katalog roboczy projektu i uruchamia dokładnie `web.py` na porcie WWW lub
  `server.py` na porcie gry. Zatrzymuje tylko takie stare procesy. Obcy
  Python/Node/inna aplikacja, nieznany PID albo brak uprawnień powodują jasny
  błąd bez zabijania procesu. `psutil` zainstalowano; testy z atrapami
  potwierdziły zatrzymywanie starego procesu projektu i ochronę obcego
  listenera. Składnia plików Python przeszła kompilację. Próba startu
  launchera została wykonana po instalacji zależności; skrypt zakończył
  instalację/sprawdzenie pakietów i uruchomił menedżer. Z tego środowiska nie
  udało się potwierdzić, czy lokalne procesy WWW/gry rzeczywiście zaczęły
  nasłuchiwać ani czy test Redis przechodzi.
- Próba testu strony HTTP nie zakończyła się w limicie czasu i została
  przerwana. Nie potwierdzono, że strona logowania odpowiada.
- Python 3.15.2 został ponownie potwierdzony. `Uruchom_serwer.bat`
  przygotowuje `.venv-app` i instaluje zależności serwera z
  `requirements-server.txt`; ta instalacja zakończyła się powodzeniem.
- Po kliknięciu **Uruchom serwer** można zamknąć VS Code; procesy startują
  osobno. Menedżer umożliwia teraz zamknięcie swojego okna przy pozostawieniu
  serwerów w tle: w pytaniu **Czy zatrzymać serwery?** wybierz **Nie**.
  **Tak** zatrzymuje serwery, a **Anuluj** pozostawia menedżer otwarty.
- `web.ini` ma włączoną rejestrację na potrzeby testu lokalnego, a nasłuch
  WWW i gry nadal wskazuje wyłącznie `127.0.0.1`.
- Użytkowniczka usunęła skrót Ruffle z pulpitu. Po tej czynności kontrola
  wykazała, że proces menedżera już nie działa, a Redis nadal nie odpowiada.
  Możemy kontynuować konfigurację krok po kroku, ale logowanie wymaga
  działającej usługi Redis.

## Szacowany czas i skrót na pulpicie

- Zależności serwera są już zainstalowane; ponowne uruchomienie
  `Uruchom_serwer.bat` powinno zająć zwykle około 1–3 minut, zależnie od
  szybkości komputera.
- Nie da się wiarygodnie podać czasu instalacji Redis, bo pakiet nie został
  zainstalowany; Windows odmówił uruchomienia `winget.exe`.
- Po uruchomieniu Redis test lokalny i utworzenie konta powinny zająć około
  2–5 minut, jeśli nie pojawią się błędy.
- Skrót można utworzyć w Eksploratorze plików: otwórz
  `C:\Users\kryst\Desktop\ava-tr-master`, kliknij prawym przyciskiem
  `Uruchom_serwer.bat` i wybierz **Pokaż więcej opcji > Wyślij do >
  Pulpit (utwórz skrót)**. W tej sesji automatyczne utworzenie skrótu nie
  zostało potwierdzone.

## Prompt do instalacji Redis na Windows

Redis nie jest obecnie dostępny na tym laptopie: ostatni test połączenia
z `127.0.0.1:6379` nie powiódł się. Próba sprawdzenia `winget` zakończyła się
odmową dostępu do pliku wykonywalnego, więc instalacja nie została wykonana.
Samo przygotowanie aplikacji nie instaluje usługi Redis.

Aby poprosić Copilota o bezpieczną próbę instalacji, wklej:

> Sprawdź, czy Redis lub Memurai jest zainstalowany i czy usługa działa
> lokalnie. Jeśli nie, spróbuj zainstalować zgodną z Redis usługę Windows
> z oficjalnego, zweryfikowanego źródła, korzystając z dostępnego menedżera
> pakietów. Przed instalacją pokaż nazwę pakietu i poproś o systemowe
> potwierdzenie, jeśli jest wymagane. Nie omijaj odmowy dostępu, polityk
> sandboxa ani zabezpieczeń Windows. Po instalacji uruchom usługę, sprawdź
> `127.0.0.1:6379` i potwierdź, że port Redis jest dostępny wyłącznie
> lokalnie. Jeśli instalacja jest zablokowana albo wymaga działania, którego
> nie możesz wykonać, zatrzymaj się i podaj dokładny komunikat oraz oficjalną
> stronę dostawcy do ręcznego pobrania. Nie wystawiaj portu Redis do internetu.

Po potwierdzeniu działania Redis uruchom `Uruchom_serwer.bat`, wybierz
**Uruchom serwer**, a następnie otwórz lokalną stronę logowania.

Aby poprosić asystenta o dalsze uruchomienie, użyj:

> Uruchom lokalny test logowania na Windows. Najpierw sprawdź, czy Python
> projektu i wymagane pakiety działają oraz czy Redis odpowiada na
> `127.0.0.1:6379`. Nie zmieniaj ustawień sieciowych ani nie otwieraj portów.
> Jeśli któryś wymóg nie działa, podaj konkretny błąd i zatrzymaj się.
> Jeśli Redis i zależności są gotowe, uruchom menedżer, sprawdź stronę
> `http://127.0.0.1:8080` i pokaż mi, jak utworzyć konto testowe i zalogować
> się; nie wypisuj hasła do logów ani nie zapisuj go w pliku.

## Bezpieczny następny krok

Nie proś o wystawienie Flash ani nieszyfrowanego portu gry publicznie.
Zamiast tego można wysłać asystentowi taki prompt:

> Oceń, czy ten projekt może zostać legalnie i bezpiecznie przeniesiony z
> klienta Flash/SWF na nowy klient niewymagający Flash. Nie pobieraj ani nie
> odtwarzaj cudzych zastrzeżonych plików gry. Najpierw przygotuj zakres
> techniczny i listę potrzebnych własnych lub licencjonowanych zasobów.
> Nie włączaj publicznego nasłuchiwania. Wskaż, jakie zmiany protokołu,
> uwierzytelniania, szyfrowania i testy bezpieczeństwa byłyby konieczne,
> zanim gracze mogliby łączyć się przez internet.

`update.json` jest manifestem zasobów gry, a nie plikiem statusu projektu.

## Dostęp dla graczy z internetu

Nie otwieraj portu gry `8123` ani Redis `6379` w routerze lub zaporze.
Obecny klient i serwer deklarują nieszyfrowany protokół gry, więc
przekierowanie portu naraziłoby połączenia graczy. Ustawienie adresu IP,
HTTPS dla strony WWW ani kliknięcie **Uruchom serwer** nie rozwiązuje tego
problemu. Publiczny dostęp pozostaje wyłączony, dopóki protokół gry nie
zostanie bezpiecznie zmieniony po obu stronach i sprawdzony.

Jeśli chcesz kontynuować przygotowania, wyślij asystentowi:

> Przygotuj plan bezpiecznego udostępnienia tej gry graczom z internetu.
> Najpierw zbadaj protokół klienta i serwera oraz wymagania sieciowe.
> Wypisz brakujące zabezpieczenia i testy. Nie zmieniaj ustawień na publiczne,
> nie otwieraj portów routera ani zapory i nie wyłączaj blokady publicznego
> nasłuchiwania, dopóki szyfrowanie i uwierzytelnianie zgodne z klientem nie
> zostaną zaimplementowane i zweryfikowane.

Nawet po przygotowaniu bezpiecznego serwera działającego na laptopie gracze
połączą się tylko wtedy, gdy komputer będzie włączony i nie będzie uśpiony.

## Ruffle — diagnoza czarnego ekranu

- Test w przeglądarce potwierdził, że Ruffle 0.7.1 wczytywał
  `pnz-city-container.swf` (1 klatka), ale wcześniejszy kod błędnie traktował
  zdarzenie `loadeddata` tego preloadera jako pełne uruchomienie interfejsu.
  Ten fałszywy komunikat 100% został usunięty.
- Manifest `versions.json` wskazuje zahashowane nazwy zasobów UI; główne
  pliki interfejsu i polska konfiguracja istnieją pod tymi nazwami. Test
  HTTP zwrócił 200 dla wersji manifestu, preloadera, klienta SWF, zasobów UI,
  konfiguracji ZIP oraz WASM Ruffle.
- Ruffle Web działa w sandboxie przeglądarki i nie łączy się bezpośrednio
  z surowym TCP gry. Dodano lokalny most WebSocket→TCP do `127.0.0.1:8123`,
  konfigurację `socketProxy` oraz blokadę żądań spoza loopbacku i spoza
  bieżącego Origin. Pasek pokazuje postęp kontroli zasobów i potwierdzonego
  połączenia, nie sam fakt załadowania preloadera.
- Po kliknięciu **Uruchom grę** test przeglądarkowy otrzymał
  `ERR_CONNECTION_REFUSED` dla `versions.json`; serwer WWW był wówczas
  niedostępny. Po uruchomieniu `Uruchom_serwer.bat` ponowny test potwierdził
  odpowiedź 200 dla głównych plików klienta oraz otwarcie WebSocket, który
  łączy się z lokalnym portem gry. Składnia `web.py` i obu skryptów JavaScript
  została sprawdzona. Pełne uruchomienie interfejsu/postaci nie jest jeszcze
  potwierdzone: wymaga zalogowania do gry i obserwacji, czy klient Avatarii
  przechodzi z ekranu preloadera do interfejsu.
- Użytkowniczka potwierdziła status „Serwer gry jest połączony, ale interfejs
  nie wystartował”; log serwera gry nadal pokazywał 0 zalogowanych graczy.
  Dodano bezpieczne diagnostyczne logi dla odrzuconego/nieoczekiwanego
  pierwszego pakietu, błędu dekodowania i wyniku logowania — bez zapisywania
  tokenu. Status HTTP mostu raportuje teraz liczbę połączeń oraz liczbę bajtów
  wysłanych przez klienta; UI wyświetla osobne komunikaty, gdy klient otworzy
  socket, ale nie wyśle logowania, albo gdy serwer zamknie połączenie.
  Zmiany wymagają ponownego uruchomienia WWW i serwera gry. Sam pasek 82%
  oznacza, że wczytał się ekran preloadera, nie że interfejs Avatarii jest
  gotowy.

## Panel właściciela i moderacja

- Dodano `/admin` dostępny po zalogowaniu konta właściciela. W trybie lokalnym
  wybrany administrator może jednorazowo przypisać siebie pod `/admin/claim`;
  ta trasa wymaga roli 5, połączenia loopback, tokenu CSRF i potwierdzenia.
  W Render właściciela ustawia wyłącznie `OWNER_UID`.
- Panel pokazuje graczy z Redisowego zestawu online, pozwala ustawiać poziom
  przez XP, wysyłać ogłoszenia i ostrzeżenia oraz nakładać/zdejmować bany i
  wyciszenia. Dodano także blokadę IP ostatniego połączenia gracza. Adres
  jest identyfikowany przez HMAC, a ban zamyka aktywne połączenie. Za proxy
  funkcja pozostaje wyłączona, dopóki `TRUSTED_PROXY_CIDRS` nie zawiera
  potwierdzonych zakresów dostawcy. Blokada może objąć wiele osób ze wspólnej
  sieci.
- Strona `/` ma responsywny wygląd Tortuga, a `/regulamin` opisuje serwer
  Avatarion. Zalogowany gracz ma obok klienta panel przełączania `[A]` lub
  `[AM]`; preferencja wpływa na rangę i znacznik nicku wysyłany w danych
  awatara, ale nie zmienia uprawnień serwerowych.
- `0` minut oznacza karę bezterminową. Ostrzeżenia i ogłoszenia wymagają
  działającego odbiorcy serwera gry.
- Serwer gry utrzymuje online-listę w Redisie, odbiera polecenia panelu przez
  Pub/Sub i sprawdza bany aktywnych graczy. Bany i wyciszenia są trwałe;
  poprawiono również błędny klucz odczytu bana i dodano `!unmute` oraz
  `!players`.
- Zmieniono obliczanie poziomu z pętli na równoważny wzór całkowitoliczbowy,
  aby ręczne ustawianie wysokich poziomów nie blokowało serwera. Testy granic
  XP zgodziły się ze starą formułą dla zakresu 0–99 999 oraz poziomów 1, 2,
  10 i 168.
- Dodano `PORADNIK_AVATARII.md` oraz odnośnik z README. W poradniku oznaczono
  wartości energii i pokoi jako niepotwierdzone dla tego forka. Nie
  potwierdzono dostępności gry dla internetu ani pełnego działania klienta
  Ruffle.
- Pylance nie zgłosił błędów składni w `web.py`, `server.py`, `client.py` ani
  `modules/component.py`. Importy, render szablonu oraz testy logiki panelu
  na atrapach Redis przeszły (claim, rola, XP, czasowe bany/wyciszenia,
  zdejmowanie kar i CSRF); osobny test logiki moderacji gry też przeszedł
  (trwałe wyciszenie, ban, wykrycie duplikatu i unban). Pełny test z działającą
  usługą Redis oraz zalogowanym klientem gry nie został wykonany.
- Przy wznowieniu pracy kompilacja czterech modułów Python oraz render
  szablonu panelu z listą online i escapowaniem nazwy gracza przeszły.
  Próba `PING` do Redis na `127.0.0.1:6379` została zablokowana przez sandbox
  systemowym błędem dostępu do gniazda (Error 13); serwery nie zostały
  uruchomione ani Redis/dane kont nie zostały zmienione.

## Stabilność uruchamiania serwera

- Odczytane końcówki logów wskazywały wcześniejsze próby startu zakończone
  konfliktem portu WWW `8080`. Wpisy o `ConstBitStream`, `cookie_secure` i
  Redis `HELLO` pochodzą ze starszych uruchomień; zależności i ustawienia
  klienta Redis w projekcie zostały już zmienione, ale trzeba ponownie
  uruchomić aktualny kod, aby nie korzystać ze starych procesów.
- Menedżer teraz czeka na otwarcie portów WWW i gry, wykrywa proces, który
  zakończył się podczas startu, i pokazuje komunikat z właściwym logiem.
  Okno gry nie powinno otworzyć się po nieudanym starcie usług.
- WWW i serwer gry sprawdzają PING Redis przy starcie. Klucz sesji WWW jest
  przechowywany lokalnie w Redisie, aby zwykłe ponowne uruchomienie serwera
  nie unieważniało ciasteczka sesji za każdym razem.
- Kompilacja `web.py`, `server.py`, `client.py`, `modules/component.py` i
  `server_manager.pyw` przeszła; Pylance nie zgłosił diagnostyk dla `web.py`
  ani `server_manager.pyw`. Nie można było przetestować działających usług:
  próba połączenia z Redis została zablokowana przez sandbox (Error 13).
- Ostatnie wpisy w `web.log` pokazują konflikt portu `8080` oraz ostrzeżenia
  z wcześniejszego kodu mostu; po ostatnim wpisie serwer WWW kończył się
  błędem wiązania portu. `game.log` pokazuje serwer gry uruchomiony, ale 0
  zalogowanych graczy. Po poprawkach wymagane jest zatrzymanie starego procesu
  i ponowny start przez aktualny `Uruchom_serwer.bat`; pełne uruchomienie
  klienta nie jest potwierdzone.
- W `client.py` zapis TCP używa teraz `sendall()`, aby zagwarantować wysłanie
  całej ramki. Błędy dekodowania lub obsługi pakietu kończą połączenie klienta
  i uruchamiają sprzątanie sesji. Testy z atrapą gniazda sprawdziły kompletny
  zapis oraz zamknięcie uszkodzonego połączenia; wszystkie 24 moduły gry
  zaimportowały się pomyślnie, a diagnostyka Pylance dla klienta, serwera
  gry i WWW nie wykazała błędów.
