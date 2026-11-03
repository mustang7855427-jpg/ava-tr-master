# Avataria — poradnik od początku

Ten poradnik dotyczy lokalnej wersji projektu uruchamianej z tego folderu.
Nie jest to oficjalny poradnik wydawcy, a działanie części starego klienta
SWF zależy od zgodności z Ruffle.

## 1. Uruchomienie na Windows

1. Zainstaluj 64-bitowego Pythona oraz lokalną usługę Redis zgodną z aplikacją
   (np. Memurai). Redis powinien nasłuchiwać wyłącznie na `127.0.0.1:6379`.
2. Uruchom usługę Redis i w folderze projektu otwórz `Uruchom_serwer.bat`.
3. Poczekaj, aż menedżer pokaże uruchomione serwery. W razie problemu otwórz
   logi `web.log` i `game.log`.
4. Otwórz grę przez menedżer albo przejdź w przeglądarce do
   `http://127.0.0.1:8080`.
5. Wybierz **Utwórz konto** albo zaloguj się danymi istniejącego konta,
   a następnie naciśnij **Uruchom grę**.

Adres `127.0.0.1` oznacza, że serwer jest dostępny tylko na tym komputerze.
Ta konfiguracja nie udostępnia gry innym graczom przez internet. Nie otwieraj
portów Redis `6379` ani gry `8123` na routerze.

## 2. Pierwsze kroki w grze

1. Po wczytaniu klienta utwórz postać i wybierz jej nazwę oraz wygląd.
2. Zapoznaj się z ikonami i zadaniami wyświetlanymi przez aktualny klient.
   Zależnie od wersji część ekranów lub funkcji może nie działać w Ruffle.
3. Ubrania zmienia się przez szafę. Wygląd postaci, np. fryzurę, kolor włosów
   i makijaż, zmienia się w salonie piękności, jeśli dana funkcja jest dostępna.
4. Wykonuj dostępne zadania i codzienne aktywności, aby rozwijać konto.
   W lokalnym kodzie poziom jest wyliczany z doświadczenia, ale nie znaleziono
   kompletnego systemu przyznawania XP za wszystkie aktywności.
5. Mieszkanie urządza się w edytorze pokoju. Najpierw wybierz pokój, następnie
   ustaw posiadane meble i zapisz zmiany, jeśli klient udostępnia taką opcję.
6. Korzystaj z listy znajomych, odwiedzin, prezentów i wydarzeń tylko wtedy,
   gdy dana funkcja działa w tej lokalnej wersji serwera.

## 3. Energia, poziomy i mieszkanie

Wskazówki przekazane dla starszej wersji gry mówią o regeneracji energii
`1 punkt/min`, zakupie `100` energii za `3` złote monety oraz odblokowywaniu
pokoi na poziomach `3, 5, 7, 9` i limicie `5` pokoi. Nie potwierdzono tych
wartości w kodzie lokalnego forka; sprawdź liczby w samym kliencie przed
wydaniem waluty. W tej kopii nowe konto otrzymuje początkowe wartości
zdefiniowane w `utils/bot_common.py`, które mogą różnić się od oryginalnej
gry.

## 4. Panel właściciela

1. Zaloguj się na konto, które ma należeć do właścicielki serwera.
2. Wybierz **Panel właściciela** na stronie gry albo otwórz
   `http://127.0.0.1:8080/admin`.
3. Jeżeli właściciel nie został jeszcze wybrany, kliknij **Ustaw moje konto
   jako właściciela** tylko po upewnieniu się, że zalogowano właściwe konto.
   To jednorazowe przypisanie jest zapisywane w Redisie; panel nie udostępnia
   zmiany właściciela przez WWW.
4. Odśwież panel, aby zobaczyć liczbę i listę aktualnie zalogowanych graczy.
   Lista opisuje wyłącznie lokalny serwer i nie oznacza, że serwer jest
   dostępny publicznie.
5. W sekcji **Moderacja** podaj UID gracza. Czas w minutach wybiera się przy
   każdym działaniu; `0` oznacza karę bezterminową. Można nakładać i zdejmować
   bany oraz wyciszenia bez limitu liczby akcji. Ostrzeżenie można wysłać
   graczowi, który jest online.
6. W sekcji **Poziom gracza** wpisz UID i poziom. Zmiana zapisuje XP
   odpowiadające wybranemu poziomowi. Nie ustawia automatycznie poziomu
   właścicielki. Bardzo wysokie poziomy są ograniczone technicznym zakresem
   liczby XP obsługiwanym przez serwer.
7. Ogłoszenia są wysyłane do graczy online. Odśwież stronę, aby odczytać
   aktualny stan połączeń.

Panel WWW wymaga zalogowania, tokenu formularza i lokalnego połączenia.
Hasło/token konta nie jest wyświetlane w panelu. Właściciel nie powinien
udostępniać danych logowania ani portu Redis.

### Komendy moderatora w czacie

Jeżeli konto ma odpowiednią rolę, komendy wpisuje się jako wiadomość na czacie:

| Komenda | Działanie |
|---|---|
| `!players` | Pokazuje liczbę graczy online; wymaga roli administratora. |
| `!ban UID` | Nakłada bezterminową blokadę konta. |
| `!unban UID` | Zdejmuje blokadę. |
| `!mute UID MINUTY` | Wycisza na podaną liczbę minut; `0` oznacza bezterminowo. |
| `!unmute UID` | Zdejmuje wyciszenie. |
| `!ssm treść` | Wysyła wiadomość systemową; wymaga uprawnienia administratora. |

Bany i wyciszenia z panelu oraz komend są przechowywane w Redisie i nie
znikają po restarcie procesu. Niektóre starsze funkcje społecznościowe mogą
być niekompletne; historia działań moderatorów w protokole gry nie jest
pełnym dziennikiem audytowym.

## 5. Gdy gra zatrzyma się na ładowaniu

Sam pasek postępu lub ekran preloadera nie oznacza, że postać została
uruchomiona. Sprawdź logi, status połączenia oraz czy Ruffle obsługuje
konkretną funkcję klienta. Nie instaluj starego Adobe Flash Playera ani
nieznanych dodatków. Błąd zgodności klienta nie jest naprawiany przez
przyznawanie wyższego poziomu ani rolą administratora.
